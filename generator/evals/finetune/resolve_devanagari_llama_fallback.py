from __future__ import annotations

"""
One-off follow-up to build_devanagari_front_end.py: resolves the words that
qwen3:8b left `null` in devanagari_front_end_checkpoint.json (275/5264 misses
after 2 attempts each, see FINAL STATS from the 2026-07-23 full-vocab run)
via a SECOND LLM fallback -- llama3.1:8b -- using the exact same
prompt/schema/protocol probe_lever_l2_devanagari_hybrid.py already used (and
had graduate) for junoon/registan/jheel/udaasi specifically. Two of those
four flagship collision words (junoon, registan) landed in this qwen3:8b
miss set, so without this pass the full-vocab table would not even cover the
words L2 exists to fix.

Never fabricates: a word llama3.1:8b also misses stays `null`, exactly like
build_devanagari_front_end.py's own contract.

Run (from generator/, VM must have llama3.1:8b pulled):
    uv run python -m evals.finetune.resolve_devanagari_llama_fallback
"""

import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path

from evals.finetune.pmi_mine import (
    LLM_BATCH_SIZE,
    _DEVANAGARI_BATCH_SCHEMA,
    _DEVANAGARI_PROMPT,
)
from vocab import load_hien_vocab

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
CHECKPOINT_PATH = DATA_DIR / "devanagari_front_end_checkpoint.json"
OUT_PATH = DATA_DIR / "devanagari_front_end_vocab_table.json"

OLLAMA_URL = "http://localhost:11434/api/generate"
CALL_TIMEOUT_SECONDS = 180


def _llm_devanagari_batch_llama(words: list[str]) -> dict[str, str]:
    """Line-for-line match of probe_lever_l2_devanagari_hybrid.py's
    _llm_devanagari_batch_llama, just with the longer 180s timeout this
    session's build already established works better than 90s."""
    prompt = _DEVANAGARI_PROMPT.format(words=", ".join(words))
    body = json.dumps(
        {
            "model": "llama3.1:8b",
            "prompt": prompt,
            "stream": False,
            "format": _DEVANAGARI_BATCH_SCHEMA,
            "options": {"temperature": 0.2},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=CALL_TIMEOUT_SECONDS) as response:  # noqa: S310
            outer = json.loads(response.read())
        raw = json.loads(outer.get("response", ""))
    except (urllib.error.URLError, ConnectionError, TimeoutError, json.JSONDecodeError):
        logger.exception("llama3.1:8b batch call failed")
        return {}
    if not isinstance(raw, list):
        return {}
    out: dict[str, str] = {}
    for rec in raw:
        if (
            isinstance(rec, dict)
            and isinstance(rec.get("word"), str)
            and isinstance(rec.get("devanagari"), str)
            and rec["devanagari"].strip()
        ):
            out[rec["word"].strip().lower()] = rec["devanagari"].strip()
    return out


def main() -> None:
    checkpoint: dict[str, str | None] = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    nulls = [w for w, v in checkpoint.items() if v is None]
    logger.info("%d words still null in checkpoint -- attempting llama3.1:8b fallback", len(nulls))

    for i in range(0, len(nulls), LLM_BATCH_SIZE):
        batch = nulls[i : i + LLM_BATCH_SIZE]
        batch_num = i // LLM_BATCH_SIZE + 1
        total_batches = (len(nulls) + LLM_BATCH_SIZE - 1) // LLM_BATCH_SIZE
        t0 = time.monotonic()
        result = _llm_devanagari_batch_llama(batch)
        elapsed = time.monotonic() - t0
        checkpoint.update(result)
        CHECKPOINT_PATH.write_text(
            json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info(
            "batch %d/%d done in %.1fs: %d/%d resolved, checkpoint saved",
            batch_num,
            total_batches,
            elapsed,
            len(result),
            len(batch),
        )

    vocab = load_hien_vocab()
    final_table = {w: checkpoint.get(w) for w in vocab}
    still_null = [w for w in vocab if final_table[w] is None]
    OUT_PATH.write_text(json.dumps(final_table, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "FINAL: %d/%d resolved, %d still unresolved after both LLM fallbacks: %s",
        len(vocab) - len(still_null),
        len(vocab),
        len(still_null),
        still_null[:30],
    )


if __name__ == "__main__":
    main()
