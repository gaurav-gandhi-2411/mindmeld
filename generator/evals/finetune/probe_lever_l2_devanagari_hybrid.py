from __future__ import annotations

"""
Cheap, read-only INFERENCE-TIME probe -- no training, no checkpoint. Tests
whether the "subword-tokenization-collision" residual documented for
junoon/registan/jheel/udaasi (public_benchmark_phase1_report.md's v1.1
addendum: each word's ROMANIZED spelling fragments into subword pieces that
collide with unrelated English words -- e.g. junoon -> "after"+"noon") can be
fixed purely by feeding the base tokenizer its native script instead of a
training intervention: does substituting these 4 words' EMBEDDING INPUT with
their DEVANAGARI transliteration (instead of the romanized spelling used
everywhere else in the vocab) fix their relatedness ranks under the SAME
shipped model, with zero net regression on the other 30 public-benchmark
secrets?

Mechanism: `embeddings.embed_vocab(vocab, lang)` embeds a vocab list
POSITIONALLY -- row i of the returned matrix is `model.encode(vocab)[i]`.
This probe builds a "hybrid" vocab list identical to the production hi-en
vocab (`vocab.load_hien_vocab()`) EXCEPT the 4 target words' list entries are
replaced with their Devanagari string before being handed to `embed_vocab`.
The resulting matrix's rows are still positionally aligned to the ORIGINAL
(romanized) vocab list, so a `word_to_idx` dict built from the romanized
vocab correctly looks up each row -- the substitution is invisible to every
downstream consumer (rank tables, dim1/dim2 scoring) except the literal text
that was fed into the encoder for those 4 rows. This is why the scoring
functions below (`_resolve_actuals_hybrid` / `_dim2_for_pairs_hybrid`) are
line-for-line clones of `evals.harness.dimension1_ranking._resolve_actuals`
and `evals.finetune.eval_model.dim2_for_pairs`, just parameterized on a
caller-supplied matrix instead of calling `embed_vocab` internally --
cloning the FROZEN SCORING pattern (per probe_subword_collision.py's
`evaluate_probe`), not the training pattern, since there is nothing to train
here.

Devanagari resolution: dict-primary (`pmi_mine.build_romanized_to_devanagari`,
built from data/raw/aksharantar_hi.jsonl) with an LLM fallback on dict miss.
All 4 target words missed the dict (verified below). The canonical fallback
`pmi_mine.llm_devanagari_batch` calls Ollama model qwen3:8b -- NOT pulled in
this environment (only llama3.1:8b and gemma2:9b were available locally, see
`ollama list` / `curl localhost:11434/api/tags` at probe time), so it returns
{} (caught LLMUnavailableError). DEVIATION (documented, not silent): rather
than reporting all 4 UNRESOLVED, this probe re-issues the exact same prompt/
schema (`pmi_mine._DEVANAGARI_PROMPT` / `_DEVANAGARI_BATCH_SCHEMA`, imported
read-only, not modified) against the locally-available llama3.1:8b model via
a probe-local `_llm_devanagari_batch_llama()` -- same protocol as
`llm_augment._call_ollama`, different model. This is a reversible,
zero-blast-radius substitution (this probe is read-only and trains nothing);
every resolved spelling is tagged with its exact source ("dict" / "llm:
llama3.1:8b") so provenance is never ambiguous. If Ollama itself is
unreachable (server down), no fallback is attempted and affected words are
reported UNRESOLVED and excluded from the hybrid substitution -- never
fabricated.

No-leakage: read-only against every data/training file and config.py. Never
writes anywhere except this probe's own eval_result.json. No git operations.

Run (from generator/):
    uv run python -m evals.finetune.probe_lever_l2_devanagari_hybrid
"""

import json
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from embeddings import cosine_similarities, embed_vocab
from evals.finetune.bootstrap_ci import (
    bootstrap_dim1_spearman_ci,
    bootstrap_dim2_pass_rate_ci,
    paired_bootstrap_dim1_delta,
    paired_bootstrap_dim2_delta,
)
from evals.finetune.eval_model import _model_override
from evals.finetune.llm_augment import LLMUnavailableError
from evals.finetune.pmi_mine import (
    AKSHARANTAR_PATH,
    _DEVANAGARI_BATCH_SCHEMA,
    _DEVANAGARI_PROMPT,
    build_romanized_to_devanagari,
    llm_devanagari_batch,
)
from evals.finetune.regression import dim1_regression_floor, dim2_regression_floor
from rival import band_for_rank
from vocab import load_hien_vocab

DATA_DIR = Path(__file__).parent / "data"
STAGING_DIR = DATA_DIR / "public_benchmark_staging"
BAKEOFF_RAW_DIR = DATA_DIR / "bakeoff_raw"
RUN_NAME = "probe_lever_l2_devanagari_hybrid"

SHIPPED_MODEL = "gauravgandhi2411/hinglish-relatedness-sbert"
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"

TARGET_WORDS: tuple[str, ...] = ("junoon", "registan", "jheel", "udaasi")

PUBLIC_BENCHMARK_34_SECRETS: frozenset[str] = frozenset(
    {
        "registan",
        "jheel",
        "chattan",
        "dhoop",
        "patta",
        "sharm",
        "chinta",
        "mazaa",
        "junoon",
        "udaasi",
        "azaadi",
        "insaaf",
        "waqt",
        "sawaal",
        "kanoon",
        "chaabi",
        "sandook",
        "thaali",
        "tokri",
        "chimni",
        "sadak",
        "sarhad",
        "basti",
        "mohalla",
        "dehat",
        "mithai",
        "dahi",
        "paneer",
        "besan",
        "khichdi",
        "mausi",
        "bhanja",
        "bhanji",
        "judwaa",
    }
)

_GOOD_BANDS = {1, 2}  # scorching or hot -- same threshold as eval_model.dim2_for_pairs


# ---------------------------------------------------------------------------
# Step 0: Ollama liveness + Devanagari resolution (dict-primary, LLM fallback)
# ---------------------------------------------------------------------------


def check_ollama_up() -> bool:
    """True iff a local Ollama server answers /api/tags. Never assumed."""
    try:
        with urllib.request.urlopen(OLLAMA_TAGS_URL, timeout=5) as resp:  # noqa: S310
            return resp.status == 200
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return False


def _llm_devanagari_batch_llama(words: list[str]) -> dict[str, str]:
    """Fallback-of-the-fallback: same prompt/schema as
    `pmi_mine.llm_devanagari_batch`/`llm_augment._call_ollama`'s protocol,
    pointed at llama3.1:8b instead of qwen3:8b (not pulled in this
    environment -- see module docstring's documented deviation). Returns {}
    on any failure, same contract as the function it mirrors -- callers
    never receive a fabricated entry."""
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
        with urllib.request.urlopen(request, timeout=90) as response:  # noqa: S310
            outer = json.loads(response.read())
        raw = json.loads(outer.get("response", ""))
    except (urllib.error.URLError, ConnectionError, TimeoutError, json.JSONDecodeError):
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


def resolve_target_devanagari(words: tuple[str, ...]) -> dict[str, dict]:
    """Resolve each of `words` to its Devanagari spelling: dict hit first
    (`pmi_mine.build_romanized_to_devanagari`), then LLM fallback on miss.
    Returns {word: {"devanagari": str | None, "source": str}} -- source is
    one of "dict", "llm:qwen3:8b", "llm:llama3.1:8b", or "unresolved". Never
    fabricates a spelling: a word with no dict hit and no reachable LLM is
    reported "unresolved" with devanagari=None."""
    rom_to_deva = build_romanized_to_devanagari(AKSHARANTAR_PATH)
    result: dict[str, dict] = {}
    misses = [w for w in words if w not in rom_to_deva]
    for w in words:
        if w in rom_to_deva:
            result[w] = {"devanagari": rom_to_deva[w], "source": "dict"}

    if misses:
        ollama_up = check_ollama_up()
        if not ollama_up:
            for w in misses:
                result[w] = {"devanagari": None, "source": "unresolved (ollama unreachable)"}
        else:
            qwen_results = llm_devanagari_batch(misses)
            still_missing = [w for w in misses if w not in qwen_results]
            for w in misses:
                if w in qwen_results:
                    result[w] = {"devanagari": qwen_results[w], "source": "llm:qwen3:8b"}
            if still_missing:
                llama_results = _llm_devanagari_batch_llama(still_missing)
                for w in still_missing:
                    if w in llama_results:
                        result[w] = {"devanagari": llama_results[w], "source": "llm:llama3.1:8b"}
                    else:
                        result[w] = {
                            "devanagari": None,
                            "source": "unresolved (qwen3:8b + llama3.1:8b both missed)",
                        }
    return result


# ---------------------------------------------------------------------------
# Step 1/2: hybrid embedding -- swap in Devanagari text at the target words'
# vocab positions, embed with the SAME shipped model, keep romanized keys
# for every downstream lookup.
# ---------------------------------------------------------------------------


def build_hybrid_matrix(
    resolved: dict[str, dict],
) -> tuple[NDArray[np.float32], dict[str, int]]:
    """Embed the full production hi-en vocab with the shipped model, except
    the resolved target words' list ENTRIES are swapped for their Devanagari
    string before encoding. Returns (matrix, word_to_idx) where word_to_idx
    keys are the ORIGINAL romanized vocab (rows stay positionally aligned to
    the unmodified vocab order, per embeddings.embed_vocab's cache-key
    contract) -- so every downstream consumer looks up words exactly as it
    always has, oblivious to which rows were computed from Devanagari text.
    """
    hien_vocab = load_hien_vocab()
    substitutions = {
        w: r["devanagari"] for w, r in resolved.items() if r["devanagari"] is not None
    }
    hybrid_vocab = [substitutions.get(w, w) for w in hien_vocab]
    with _model_override(SHIPPED_MODEL):
        matrix = embed_vocab(hybrid_vocab, "hi-en")
    word_to_idx = {w: i for i, w in enumerate(hien_vocab)}
    return matrix, word_to_idx


# ---------------------------------------------------------------------------
# Step 3: frozen-benchmark scoring -- clones of
# evals.harness.dimension1_ranking._resolve_actuals and
# evals.finetune.eval_model.dim2_for_pairs, parameterized on a caller-
# supplied matrix instead of an internal embed_vocab() call.
# ---------------------------------------------------------------------------


def _resolve_actuals_hybrid(
    scenarios: list[dict], matrix: NDArray[np.float32], word_to_idx: dict[str, int]
) -> list[dict]:
    n = matrix.shape[0]
    secrets = sorted({s["secret"] for s in scenarios})
    rank_tables: dict[str, np.ndarray] = {}
    for secret in secrets:
        if secret not in word_to_idx:
            continue
        sims = cosine_similarities(matrix, matrix[word_to_idx[secret]])
        order = np.argsort(-sims)
        ranks = np.empty(n, dtype=np.int32)
        for rank_minus1, idx in enumerate(order):
            ranks[idx] = rank_minus1 + 1
        rank_tables[secret] = ranks

    resolved: list[dict] = []
    for rec in scenarios:
        secret, word = rec["secret"], rec["word"]
        out = dict(rec)
        if secret not in rank_tables or word not in word_to_idx:
            out["actual_rank"] = None
            out["actual_band"] = None
            out["in_expected_band"] = False
            out["resolution_error"] = f"secret={secret!r} or word={word!r} not in vocab"
        else:
            rank = int(rank_tables[secret][word_to_idx[word]])
            band = band_for_rank(rank, n)
            out["actual_rank"] = rank
            out["actual_band"] = band
            out["in_expected_band"] = band in rec["expected_bands"]
            out["resolution_error"] = None
        resolved.append(out)
    return resolved


def _dim2_for_pairs_hybrid(
    pairs: list[tuple[str, str]], matrix: NDArray[np.float32], word_to_idx: dict[str, int]
) -> dict:
    n = matrix.shape[0]
    records: list[dict] = []
    for en_secret, hien_secret in pairs:
        if hien_secret not in word_to_idx or en_secret not in word_to_idx:
            records.append(
                {
                    "en_secret": en_secret,
                    "hien_secret": hien_secret,
                    "rank": None,
                    "band": None,
                    "consistent": None,
                    "resolution_error": "secret or translation missing from hi-en vocab",
                }
            )
            continue
        sims = cosine_similarities(matrix, matrix[word_to_idx[hien_secret]])
        order = np.argsort(-sims)
        ranks = np.empty(n, dtype=np.int32)
        for rank_minus1, idx in enumerate(order):
            ranks[idx] = rank_minus1 + 1
        rank = int(ranks[word_to_idx[en_secret]])
        band = band_for_rank(rank, n)
        records.append(
            {
                "en_secret": en_secret,
                "hien_secret": hien_secret,
                "rank": rank,
                "rank_percentile": round(100 * rank / n, 2),
                "band": band,
                "consistent": band in _GOOD_BANDS,
                "resolution_error": None,
            }
        )

    resolved = [r for r in records if r["resolution_error"] is None]
    consistent = [r for r in resolved if r["consistent"]]
    pass_rate = len(consistent) / len(resolved) if resolved else None
    ranks = [r["rank"] for r in resolved]
    return {
        "n_pairs": len(pairs),
        "n_resolved": len(resolved),
        "pass_rate_scorching_or_hot": pass_rate,
        "median_rank": float(np.median(ranks)) if ranks else None,
        "records": records,
    }


def _public_benchmark_dim1_records_hybrid(
    matrix: NDArray[np.float32], word_to_idx: dict[str, int]
) -> list[dict]:
    scenarios = json.loads((STAGING_DIR / "dim1_hien.json").read_text(encoding="utf-8"))
    return _resolve_actuals_hybrid(scenarios, matrix, word_to_idx)


def _public_benchmark_dim2_result_hybrid(
    matrix: NDArray[np.float32], word_to_idx: dict[str, int]
) -> dict:
    pairs_raw = json.loads((STAGING_DIR / "dim2_pairs.json").read_text(encoding="utf-8"))
    pairs = [(r["en_gloss"], r["hien_secret"]) for r in pairs_raw]
    return _dim2_for_pairs_hybrid(pairs, matrix, word_to_idx)


def _shipped_model_dim1_records_34() -> list[dict]:
    """Reuse the shipped model's already-computed bakeoff_raw checkpoint --
    no re-embedding of the shipped/plain-romanized model, exactly the frozen
    comparator pattern probe_subword_collision.py uses."""
    checkpoint = json.loads(
        (BAKEOFF_RAW_DIR / "gauravgandhi2411__hinglish-relatedness-sbert.json").read_text(
            encoding="utf-8"
        )
    )
    return [r for r in checkpoint["dim1_records"] if r["secret"] in PUBLIC_BENCHMARK_34_SECRETS]


def _shipped_model_dim2_records_34() -> list[dict]:
    """See probe_subword_collision.py's identically-named function for the
    documented besan gloss-mismatch caveat (dropped from paired n, not
    silently misaligned) -- same source file, same caveat applies here."""
    checkpoint = json.loads(
        (BAKEOFF_RAW_DIR / "gauravgandhi2411__hinglish-relatedness-sbert.json").read_text(
            encoding="utf-8"
        )
    )
    return [
        r for r in checkpoint["dim2_records"] if r["hien_secret"] in PUBLIC_BENCHMARK_34_SECRETS
    ]


def _target_word_summary(dim1_records: list[dict], dim2_records: list[dict]) -> dict:
    out = {}
    for w in TARGET_WORDS:
        dim1_rows = [r for r in dim1_records if r["secret"] == w]
        dim2_rows = [r for r in dim2_records if r["hien_secret"] == w]
        out[w] = {
            "dim1_rows": dim1_rows,
            "dim2_row": dim2_rows[0] if dim2_rows else None,
        }
    return out


# ---------------------------------------------------------------------------
# Step 4/5: paired bootstrap vs shipped + regression floor across all 34.
# ---------------------------------------------------------------------------


def evaluate_probe() -> dict:
    resolved = resolve_target_devanagari(TARGET_WORDS)
    print(f"devanagari resolution: {json.dumps(resolved, ensure_ascii=False, indent=2)}")

    matrix, word_to_idx = build_hybrid_matrix(resolved)

    hybrid_dim1 = _public_benchmark_dim1_records_hybrid(matrix, word_to_idx)
    hybrid_dim2 = _public_benchmark_dim2_result_hybrid(matrix, word_to_idx)

    shipped_dim1 = _shipped_model_dim1_records_34()
    shipped_dim2 = _shipped_model_dim2_records_34()

    hybrid_dim1_ci = bootstrap_dim1_spearman_ci(hybrid_dim1)
    hybrid_dim2_ci = bootstrap_dim2_pass_rate_ci(hybrid_dim2["records"])
    shipped_dim1_ci = bootstrap_dim1_spearman_ci(shipped_dim1)
    shipped_dim2_ci = bootstrap_dim2_pass_rate_ci(shipped_dim2)

    dim1_delta = paired_bootstrap_dim1_delta(shipped_dim1, hybrid_dim1)
    dim2_delta = paired_bootstrap_dim2_delta(shipped_dim2, hybrid_dim2["records"])

    dim1_floor = dim1_regression_floor(shipped_dim1, hybrid_dim1)
    dim2_floor = dim2_regression_floor(shipped_dim2, hybrid_dim2["records"])

    target_before = _target_word_summary(shipped_dim1, shipped_dim2)
    target_after = _target_word_summary(hybrid_dim1, hybrid_dim2["records"])

    result = {
        "run_name": RUN_NAME,
        "shipped_model": SHIPPED_MODEL,
        "target_words": list(TARGET_WORDS),
        "devanagari_resolution": resolved,
        "n_dim1_secrets": len({r["secret"] for r in hybrid_dim1}),
        "n_dim1_scenarios": len(hybrid_dim1),
        "n_dim2_pairs": len(hybrid_dim2["records"]),
        "hybrid_dim1_spearman_ci": hybrid_dim1_ci,
        "hybrid_dim2_pass_rate_ci": hybrid_dim2_ci,
        "shipped_dim1_spearman_ci": shipped_dim1_ci,
        "shipped_dim2_pass_rate_ci": shipped_dim2_ci,
        "dim1_delta_vs_shipped": dim1_delta,
        "dim2_delta_vs_shipped": dim2_delta,
        "dim1_regression_floor_all_34": dim1_floor,
        "dim2_regression_floor_all_34": dim2_floor,
        "target_words_before_shipped": target_before,
        "target_words_after_hybrid": target_after,
    }
    out_path = DATA_DIR / f"{RUN_NAME}.eval_result.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")
    return result


def main() -> None:
    evaluate_probe()


if __name__ == "__main__":
    main()
