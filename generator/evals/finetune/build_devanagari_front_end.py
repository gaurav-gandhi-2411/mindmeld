from __future__ import annotations

"""
Standalone builder for the full hi-en vocab -> Devanagari-spelling
transliteration table (a dedicated GCP session's ONLY deliverable — no
scoring, no retraining, see spec-residual-attack.md and
data/l2_full_vocab_rebaseline_phase0_finding.json for why this is split out
as its own artifact/session rather than folded into pmi_mine.py's build()).

Pipeline:
  1. Load the full 10,495-word hi-en vocab (vocab.load_hien_vocab).
  2. Resolve each word's Devanagari spelling via
     pmi_mine.build_romanized_to_devanagari's Aksharantar dict (~5,231 direct
     hits per the Phase-0 finding above).
  3. For the ~5,264 dict misses, fall back to pmi_mine.llm_devanagari_batch,
     LLM_BATCH_SIZE (25) words per call, run SEQUENTIALLY — the Phase-0
     finding confirmed 4-way parallelism makes CPU-bound Ollama inference
     WORSE, not better, so no concurrency is attempted here.
  4. Checkpoint the accumulating {word: devanagari_or_None} table to disk
     after EVERY batch (not just periodically) so a VM/connection failure
     never loses more than one in-flight batch's progress. The checkpoint
     file doubles as a resume point: re-running this script skips any miss
     already present in the checkpoint.
  5. Never fabricate: a word that still has no LLM answer after
     MAX_ATTEMPTS_PER_BATCH attempts on its batch is recorded as an explicit
     `null` in the final table, not silently dropped or guessed.

Per-call timeout: the Phase-0 finding measured a single 25-word batch at
87.8s against llm_augment's default 90s TIMEOUT_SECONDS -- a 2.2s margin
that caused spurious timeout-retries on calls that would have succeeded
given a few more seconds. This script raises the timeout (module-level
monkeypatch of evals.finetune.llm_augment.TIMEOUT_SECONDS, since pmi_mine's
llm_devanagari_batch/_call_ollama read that name from llm_augment's own
module globals at call time, not a value copied at import time) to
CALL_TIMEOUT_SECONDS before running anything.

Run (from the generator/ directory, so `evals`/`vocab`/etc. resolve as
top-level packages/modules — same convention as pmi_mine.py/split.py):
    uv run python -m evals.finetune.build_devanagari_front_end
"""

import json
import logging
import time
from pathlib import Path

from evals.finetune import llm_augment, pmi_mine
from vocab import load_hien_vocab

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
CHECKPOINT_PATH = DATA_DIR / "devanagari_front_end_checkpoint.json"
OUT_PATH = DATA_DIR / "devanagari_front_end_vocab_table.json"

# Raised from llm_augment.TIMEOUT_SECONDS's default of 90s -- see module
# docstring. A live GCP run at 170s still hit the timeout on batch 1's first
# attempt (337.9s total: 170s timeout + a 167.8s successful retry), so this is
# raised again to 180s to reduce spurious timeout-then-retry churn -- a
# timing-calibration session (see PLAN.md) will confirm whether this actually
# lowers the retry rate.
CALL_TIMEOUT_SECONDS = 180

# 1 initial attempt + this many retries per batch, applied only to the words
# still unresolved after the previous attempt (so a batch that resolves
# 20/25 on attempt 1 only re-sends the remaining 5 on attempt 2).
MAX_RETRIES_PER_BATCH = 1


def load_checkpoint(path: Path) -> dict[str, str | None]:
    """Load an existing checkpoint file, or return an empty table if none exists yet."""
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_checkpoint(table: dict[str, str | None], path: Path) -> None:
    """Write `table` to `path` as pretty JSON, creating the parent dir if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_dict_hits(
    checkpoint: dict[str, str | None], dict_hits: dict[str, str]
) -> dict[str, str | None]:
    """
    Pure merge step: seed `checkpoint` (mutated copy) with every dict-hit
    word not already present, so the checkpoint file is self-contained (dict
    hits + LLM resolutions) rather than LLM-only. Dict hits are deterministic
    given a fixed Aksharantar snapshot, so an existing checkpoint entry for a
    dict-hit word (from a prior partial run) is left as-is rather than
    overwritten -- there is nothing to reconcile.
    """
    merged = dict(checkpoint)
    for word, deva in dict_hits.items():
        merged.setdefault(word, deva)
    return merged


def resolve_misses_batch(
    batch: list[str], max_retries: int = MAX_RETRIES_PER_BATCH
) -> dict[str, str | None]:
    """
    Resolve one batch of romanized words to Devanagari via
    pmi_mine.llm_devanagari_batch, retrying only the still-unresolved subset
    up to `max_retries` additional times. Returns {word: devanagari_or_None}
    for every word in `batch` -- words never answered are explicit None, not
    omitted (caller must not have to guess whether a missing key means
    "unresolved" or "not attempted").
    """
    pending = list(batch)
    resolved: dict[str, str] = {}
    for attempt in range(1, max_retries + 2):
        if not pending:
            break
        t0 = time.monotonic()
        try:
            result = pmi_mine.llm_devanagari_batch(pending)
        except Exception:  # noqa: BLE001 -- a single bad batch must never kill a 5+ hour run
            logger.exception("batch attempt %d raised an unexpected exception", attempt)
            result = {}
        elapsed = time.monotonic() - t0
        resolved.update(result)
        pending = [w for w in pending if w not in resolved]
        logger.info(
            "  attempt %d/%d: %.1fs, %d/%d resolved this attempt, %d still unresolved",
            attempt,
            max_retries + 1,
            elapsed,
            len(result),
            len(batch),
            len(pending),
        )
    return {w: resolved.get(w) for w in batch}


def resolve_misses(
    misses: list[str],
    checkpoint: dict[str, str | None],
    checkpoint_path: Path,
    batch_size: int = pmi_mine.LLM_BATCH_SIZE,
) -> dict[str, str | None]:
    """
    Sequentially resolve every word in `misses` not already in `checkpoint`,
    `batch_size` at a time, saving `checkpoint` to `checkpoint_path` after
    EVERY batch (mutates and returns `checkpoint`). Deliberately sequential
    -- see module docstring's Phase-0 parallelism finding.
    """
    pending = [w for w in misses if w not in checkpoint]
    if not pending:
        logger.info("all %d misses already resolved in checkpoint -- nothing to do", len(misses))
        return checkpoint

    total_batches = (len(pending) + batch_size - 1) // batch_size
    logger.info(
        "%d/%d misses already resolved from checkpoint; %d remain across %d batches",
        len(misses) - len(pending),
        len(misses),
        len(pending),
        total_batches,
    )
    for i in range(0, len(pending), batch_size):
        batch = pending[i : i + batch_size]
        batch_num = i // batch_size + 1
        logger.info("batch %d/%d (%d words) starting", batch_num, total_batches, len(batch))
        t0 = time.monotonic()
        batch_result = resolve_misses_batch(batch)
        elapsed = time.monotonic() - t0
        checkpoint.update(batch_result)
        save_checkpoint(checkpoint, checkpoint_path)
        n_resolved = sum(1 for v in batch_result.values() if v is not None)
        logger.info(
            "batch %d/%d done in %.1fs: %d/%d resolved, checkpoint saved (%d total entries)",
            batch_num,
            total_batches,
            elapsed,
            n_resolved,
            len(batch),
            len(checkpoint),
        )
    return checkpoint


def build_table() -> dict:
    """Full pipeline: vocab -> dict hits -> LLM fallback -> final merged table + stats."""
    logger.info("Loading hi-en vocab ...")
    vocab = load_hien_vocab()
    logger.info("vocab size: %d", len(vocab))

    logger.info("Building romanized->devanagari dict from Aksharantar ...")
    rom_to_deva = pmi_mine.build_romanized_to_devanagari(pmi_mine.AKSHARANTAR_PATH)
    logger.info("dict entries: %d", len(rom_to_deva))

    dict_hits = {w: rom_to_deva[w] for w in vocab if w in rom_to_deva}
    misses = [w for w in vocab if w not in rom_to_deva]
    logger.info("dict hits: %d, misses needing LLM: %d", len(dict_hits), len(misses))

    checkpoint = load_checkpoint(CHECKPOINT_PATH)
    checkpoint = merge_dict_hits(checkpoint, dict_hits)
    save_checkpoint(checkpoint, CHECKPOINT_PATH)

    checkpoint = resolve_misses(misses, checkpoint, CHECKPOINT_PATH)

    n_resolved_llm = sum(1 for w in misses if checkpoint.get(w) is not None)
    n_unresolved = sum(1 for w in misses if checkpoint.get(w) is None)
    logger.info(
        "LLM resolution complete: %d/%d resolved, %d unresolved",
        n_resolved_llm,
        len(misses),
        n_unresolved,
    )

    final_table = {w: checkpoint.get(w) for w in vocab}
    unresolved_words = [w for w in vocab if final_table[w] is None]

    OUT_PATH.write_text(json.dumps(final_table, ensure_ascii=False, indent=2), encoding="utf-8")
    stats = {
        "vocab_size": len(vocab),
        "dict_hits": len(dict_hits),
        "llm_attempted": len(misses),
        "llm_resolved": n_resolved_llm,
        "unresolved": n_unresolved,
        "unresolved_sample": unresolved_words[:30],
        "output_path": str(OUT_PATH),
    }
    logger.info("FINAL STATS: %s", json.dumps(stats, ensure_ascii=False))
    return stats


if __name__ == "__main__":
    llm_augment.TIMEOUT_SECONDS = CALL_TIMEOUT_SECONDS
    logger.info("llm_augment.TIMEOUT_SECONDS raised to %ds", llm_augment.TIMEOUT_SECONDS)
    build_table()
