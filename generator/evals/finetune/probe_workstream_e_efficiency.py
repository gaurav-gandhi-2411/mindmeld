from __future__ import annotations

"""
Workstream E (spec-model-excellence.md item 15): efficiency assessment for
the shipped hi-en model (gauravgandhi2411/hinglish-relatedness-sbert).

SCOPING NOTE (read before touching this file): this is a DIFFERENT thing
from tests/test_quantization.py / payload.quantize/dequantize, which
quantize similarity SCORES (floats) into uint16 for the game payload's wire
format. This module quantizes the embedding MODEL's weights/vectors, and
never imports payload.py.

HONEST FRAMING NOTE on "latency": payload.py PRECOMPUTES every word's rank/
similarity for the ENTIRE vocab ONCE per secret at payload-build time (a
batch job); the live game only ever does O(1) hash-lookups against that
precomputed data. There is NO live per-user embedding inference in
production today. "Latency" measured here is therefore about (a) the
offline payload-build step's wall-clock cost, and (b) the practical
implication for any FUTURE feature needing live inference (free-text
similarity, on-device use) or for a contributor/recruiter trying to run
this model locally -- NOT a live-user-facing bottleneck that exists today.

Three questions, three sections:

Step 1 -- baseline: model size on disk + embed_vocab() wall-clock (cold =
includes model load, warm = subsequent call) for the full 10,495-word hi-en
vocab on CPU (this repo's own $0/local-CPU default, per train.py's
docstring). Two latency numbers are reported per model, deliberately:
  (a) "embed_vocab() wall-clock" -- the LITERAL production entry point,
      including its persistent disk cache (embeddings.py). The "warm" call
      here is a cache HIT (an np.load), not a measure of model inference
      speed -- reported for completeness/transparency about what the cache
      buys in practice, not used for any quantization comparison.
  (b) "pure inference latency" -- SentenceTransformer(...).encode(vocab)
      called directly, bypassing the disk cache entirely. "cold" = fresh
      model construction + first encode (one timed block); "warm" = same
      already-loaded model instance, encode called again. THIS is the
      number quantization variants below are compared against, since a
      disk-cache hit would trivially equalise every model's "warm" number
      and hide any real inference-speed difference.

Step 2 -- post-hoc quantization, no retraining:
  2a. Embedding-VECTOR quantization (sentence_transformers.util.quantization.
      quantize_embeddings, int8/binary) applied to the PRECOMPUTED vocab
      embeddings -- matches production's actual usage (embed once, reuse
      many times per secret). Ranking is recomputed from the quantized
      vectors directly (int8 -> integer dot product; binary -> Hamming
      distance, lower = more similar) -- NOT by dequantizing back to
      float32, since that would defeat the point of measuring what the
      quantized representation's OWN similarity ordering looks like.
  2b. Model-WEIGHT quantization (torch.quantization.quantize_dynamic on the
      transformer's nn.Linear layers -- built into torch, already a
      dependency; neither `optimum` nor `onnxruntime` is installed or
      locked in this repo (verified: `uv run python -c "import optimum"` /
      `import onnxruntime` both raise ModuleNotFoundError, and `uv.lock`
      has zero hits for either name) so this deliberately avoids adding a
      new dependency per this repo's lean-startup conventions.

Both gate on the FULL Workstream A metric suite (NDCG/MRR/Recall/Precision@k,
band calibration/ECE, Spearman, dim1/dim2 pass-rate) on the SAME 42-secret
combined test set benchmark_bakeoff.py uses (paired bootstrap vs the
UNQUANTIZED shipped model, zero-net-regression gate) -- reusing
benchmark_bakeoff's already-checkpointed shipped-model result
(evals/finetune/data/bakeoff_raw/gauravgandhi2411__hinglish-relatedness-sbert
.json) as the baseline, rather than recomputing it.

Step 3 -- distillation candidate (run only if Step 2 leaves room to explore
further -- see this run's eval_result.json for the actual decision and its
justification): fine-tune sentence-transformers/paraphrase-multilingual-
MiniLM-L12-v2 (already in benchmark_bakeoff.CANDIDATE_MODELS, already
locally cached) with the EXACT SAME recipe/data as the shipped model (LoRA
r=8/alpha=16/lr=2e-4/4 epochs/seed=42, train_mnrl_pairs.jsonl +
train_graded_pairs.jsonl -- the ORIGINAL production files, never the
`_variant_augmented` ones) via train_lib.run_training(TrainConfig(
base_model=MINILM_CANDIDATE, ...)) (train_lib.TrainConfig.base_model added
by this workstream, defaulting to the existing OFF_THE_SHELF_MODEL so every
other caller is unaffected). Saved to checkpoints/minilm_student/model --
NEVER checkpoints/obj_hard_neg/model/ or evals/finetune/model/ (the shipped
model), both left byte-identical (verified by this module's own
`verify_protected_files_untouched`).

Nothing here publishes to HuggingFace or overwrites the shipped model/
checkpoint -- any promotion-worthy result is a recommendation, not an action.

Run (from generator/):
    uv run python -m evals.finetune.probe_workstream_e_efficiency --baseline
    uv run python -m evals.finetune.probe_workstream_e_efficiency --quantize
    uv run python -m evals.finetune.probe_workstream_e_efficiency --distill-train
    uv run python -m evals.finetune.probe_workstream_e_efficiency --distill-eval
    uv run python -m evals.finetune.probe_workstream_e_efficiency --verify-untouched
"""

import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np
import torch
from numpy.typing import NDArray
from sentence_transformers import SentenceTransformer

import config
from embeddings import _cache_key, cosine_similarities, embed_vocab
from evals.finetune.benchmark_bakeoff import (
    _load_valid_checkpoint,
    combined_dim2_pairs,
    load_combined_dim1_scenarios,
)
from evals.finetune.bootstrap_ci import (
    bootstrap_band_ece_ci,
    bootstrap_dim1_spearman_ci,
    bootstrap_dim2_pass_rate_ci,
    bootstrap_top_weighted_correlation_ci,
    bootstrap_topheavy_ci,
    paired_bootstrap_dim1_delta,
    paired_bootstrap_dim2_delta,
)
from evals.finetune.regression import dim1_regression_floor, dim2_regression_floor
from evals.finetune.split import load_split
from evals.finetune.train_lib import TrainConfig, run_training
from evals.harness import topheavy
from evals.harness.dimension1_ranking import _band_accuracy
from rival import band_for_rank
from vocab import load_hien_vocab

FINETUNE_DIR = Path(__file__).parent
DATA_DIR = FINETUNE_DIR / "data"
MODEL_DIR = FINETUNE_DIR / "model"
PROTECTED_MODEL_SAFETENSORS = MODEL_DIR / "model.safetensors"
PROTECTED_OBJ_HARD_NEG_SAFETENSORS = (
    FINETUNE_DIR / "checkpoints" / "obj_hard_neg" / "model" / "model.safetensors"
)
PROTECTED_TRAIN_MNRL = DATA_DIR / "train_mnrl_pairs.jsonl"
PROTECTED_TRAIN_GRADED = DATA_DIR / "train_graded_pairs.jsonl"

SHIPPED_MODEL = "gauravgandhi2411/hinglish-relatedness-sbert"
MINILM_CANDIDATE = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
RUN_NAME = "probe_workstream_e_efficiency"
_GOOD_BANDS = {1, 2}  # win/scorching count as "consistent" for dim2, matches eval_model.py

# Baseline byte-hashes recorded BEFORE this workstream touched anything
# (2026-07-24, `sha256sum` on each path). Used by verify_protected_files_
# untouched() as ground truth, not re-derived at import time, so a run of
# this module can never accidentally "bless" a mutation that already
# happened.
_BASELINE_HASHES = {
    str(MODEL_DIR / "model.safetensors"): (
        "9a31e8af295b4dba7c429f2c89a8e02fe56aff79346300f30651eb847e966f08"
    ),
    str(PROTECTED_OBJ_HARD_NEG_SAFETENSORS): (
        "9b29c785654aba26048c9c78243f41cf722ccd48ad1d9ac793cfb81164b72b34"
    ),
    str(PROTECTED_TRAIN_MNRL): "98fbce616e2a5d2da98264c4930f45f6ab0c6ae3ae60a2459df643be4644b968",
    str(PROTECTED_TRAIN_GRADED): "1ed0c7343bc4cb73464c478520349082cb37d9c3c3a94402d75dd5b2ab06f7c3",
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_protected_files_untouched() -> dict:
    """Recompute sha256 for every path in _BASELINE_HASHES and compare
    against the value recorded before this workstream started. Never
    trusts git diff for these paths -- evals/finetune/model/ and evals/
    finetune/checkpoints/ are both gitignored (see .gitignore lines 27-28),
    so a byte-level hash is the only real evidence of "untouched"."""
    results = {}
    all_match = True
    for path_str, expected in _BASELINE_HASHES.items():
        path = Path(path_str)
        actual = _sha256(path) if path.exists() else None
        match = actual == expected
        all_match = all_match and match
        results[path_str] = {"expected": expected, "actual": actual, "match": match}
    return {"all_untouched": all_match, "files": results}


# ---------------------------------------------------------------------------
# Step 1a: model size on disk.
# ---------------------------------------------------------------------------


def model_dir_size_bytes(model_dir: Path = MODEL_DIR) -> dict:
    """Total on-disk size of every file under `model_dir` -- the shipped
    model's real footprint (weights + tokenizer + config), not just the
    weight file."""
    files = [f for f in model_dir.rglob("*") if f.is_file()]
    total = sum(f.stat().st_size for f in files)
    largest = max(files, key=lambda f: f.stat().st_size)
    return {
        "model_dir": str(model_dir),
        "total_bytes": total,
        "total_mb": total / 1e6,
        "total_mib": total / (1024**2),
        "n_files": len(files),
        "largest_file": largest.name,
        "largest_file_bytes": largest.stat().st_size,
    }


# ---------------------------------------------------------------------------
# Step 1b: latency -- both the literal embed_vocab() wall-clock (with its
# persistent disk cache) and pure model-inference latency (bypassing that
# cache, the number comparable across quantized variants).
# ---------------------------------------------------------------------------


def measure_embed_vocab_wallclock(vocab: list[str], lang: str = "hi-en") -> dict:
    """Literal wall-clock of production's embeddings.embed_vocab() for the
    model currently configured for `lang` (config.MODELS[lang]). Deletes
    any pre-existing cache file for this exact (model, vocab) key first, so
    "cold" is a genuine cache MISS (full model load + full-vocab
    inference); "warm" is the immediately following call, a cache HIT (an
    np.load) -- NOT a measure of the model's own inference speed. This
    deletes/rewrites a shared, regenerable build artifact (embeddings.py's
    file cache), never source data."""
    model_name = config.MODELS[lang]
    key = _cache_key(vocab, model_name)
    cache_path = config.CACHE_DIR / f"{lang}-{key}.npy"
    cache_pre_existed = cache_path.exists()
    if cache_pre_existed:
        cache_path.unlink()

    t0 = time.monotonic()
    embed_vocab(vocab, lang, show_progress=False)
    cold_s = time.monotonic() - t0

    t0 = time.monotonic()
    embed_vocab(vocab, lang, show_progress=False)
    warm_s = time.monotonic() - t0

    n = len(vocab)
    return {
        "model": model_name,
        "n_words": n,
        "cache_pre_existed_before_this_measurement": cache_pre_existed,
        "cold_seconds": cold_s,
        "cold_ms_per_word": 1000 * cold_s / n,
        "warm_seconds": warm_s,
        "warm_ms_per_word": 1000 * warm_s / n,
        "note": "warm here is a disk-cache HIT (np.load), not inference speed -- "
        "see measure_inference_latency for the comparable pure-inference number",
    }


def measure_inference_latency(
    model_name_or_path: str, vocab: list[str], batch_size: int = 512
) -> dict:
    """Pure SentenceTransformer inference latency, bypassing embeddings.
    embed_vocab's persistent disk cache entirely (a fresh model.encode call
    every time) so this number is comparable across quantized variants that
    are never written through that cache. "cold" = fresh model construction
    + first encode call, timed as one block (captures model-load overhead);
    "warm" = same already-loaded model instance, encode called again."""
    t0 = time.monotonic()
    model = SentenceTransformer(model_name_or_path, token=os.environ.get("HF_TOKEN"))
    matrix_cold = model.encode(
        vocab,
        batch_size=batch_size,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    cold_s = time.monotonic() - t0

    t0 = time.monotonic()
    model.encode(
        vocab,
        batch_size=batch_size,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    warm_s = time.monotonic() - t0

    n = len(vocab)
    return {
        "model": model_name_or_path,
        "n_words": n,
        "embedding_dim": int(matrix_cold.shape[1]),
        "cold_seconds": cold_s,
        "cold_ms_per_word": 1000 * cold_s / n,
        "warm_seconds": warm_s,
        "warm_ms_per_word": 1000 * warm_s / n,
    }


def run_baseline() -> dict:
    vocab = load_hien_vocab()
    size = model_dir_size_bytes()
    embed_vocab_wallclock = measure_embed_vocab_wallclock(vocab, "hi-en")
    inference_latency = measure_inference_latency(SHIPPED_MODEL, vocab)
    result = {
        "run": "baseline",
        "shipped_model": SHIPPED_MODEL,
        "n_vocab_words": len(vocab),
        "model_dir_size": size,
        "embed_vocab_wallclock": embed_vocab_wallclock,
        "inference_latency": inference_latency,
    }
    out_path = DATA_DIR / f"{RUN_NAME}.baseline.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"wrote {out_path}")
    return result


# ---------------------------------------------------------------------------
# Shared: full Workstream A metric suite + zero-regression gate, computed
# from an arbitrary (dim1_records, dim2_records) pair -- reused for every
# candidate (int8-quantized, binary-quantized, weight-quantized, distilled).
# ---------------------------------------------------------------------------


def compute_full_metric_suite(
    dim1_records: list[dict], dim2_records: list[dict], vocab_size: int
) -> dict:
    """Same metric set benchmark_bakeoff.evaluate_one_model computes:
    dim1 Spearman+CI, dim2 pass-rate+CI, band-accuracy, top-heavy ranking
    metrics (NDCG/MRR/Recall/Precision@k) + CI, band-calibration (confusion
    matrix, per-band P/R, ECE)+CI."""
    dim1_ci = bootstrap_dim1_spearman_ci(dim1_records)
    dim2_ci = bootstrap_dim2_pass_rate_ci(dim2_records)
    by_tier = {t: [r for r in dim1_records if r["tier"] == t] for t in ("near", "mid", "far")}
    band_accuracy = {
        "overall": _band_accuracy(dim1_records),
        "near": _band_accuracy(by_tier["near"]),
        "mid": _band_accuracy(by_tier["mid"]),
        "far": _band_accuracy(by_tier["far"]),
    }
    topheavy_ci = bootstrap_topheavy_ci(dim1_records)
    top_weighted_correlation_ci = bootstrap_top_weighted_correlation_ci(dim1_records)
    band_confusion = topheavy.band_confusion_matrix(dim1_records)
    per_band_pr = topheavy.per_band_precision_recall(dim1_records)
    band_ece_ci = bootstrap_band_ece_ci(dim1_records, vocab_size)
    return {
        "dim1_spearman_ci": dim1_ci,
        "dim2_pass_rate_ci": dim2_ci,
        "band_accuracy": band_accuracy,
        "topheavy_ci": topheavy_ci,
        "top_weighted_correlation_ci": top_weighted_correlation_ci,
        "band_confusion": band_confusion,
        "per_band_pr": per_band_pr,
        "band_ece_ci": band_ece_ci,
    }


def gate_vs_shipped(
    shipped_dim1: list[dict],
    shipped_dim2: list[dict],
    cand_dim1: list[dict],
    cand_dim2: list[dict],
) -> dict:
    """Paired-bootstrap deltas + per-pair regression floor (fixed/broken
    accounting, regression.py) of `cand` vs the UNQUANTIZED shipped model.
    Gate verdict PASSes only if neither dim1 nor dim2 shows a CI-significant
    regression AND both regression floors are net non-negative -- same
    "zero net regression" bar every other lever in this program is held to
    (spec-model-excellence.md Gates section)."""
    dim1_delta = paired_bootstrap_dim1_delta(shipped_dim1, cand_dim1)
    dim2_delta = paired_bootstrap_dim2_delta(shipped_dim2, cand_dim2)
    dim1_floor = dim1_regression_floor(shipped_dim1, cand_dim1)
    dim2_floor = dim2_regression_floor(shipped_dim2, cand_dim2)
    passed = (
        not dim1_delta["ci_significant_regression"]
        and not dim2_delta["ci_significant_regression"]
        and dim1_floor["zero_net_regression"]
        and dim2_floor["zero_net_regression"]
    )
    return {
        "dim1_delta_vs_shipped": dim1_delta,
        "dim2_delta_vs_shipped": dim2_delta,
        "dim1_regression_floor": dim1_floor,
        "dim2_regression_floor": dim2_floor,
        "gate_verdict": "PASS" if passed else "FAIL",
    }


def _shipped_baseline_records() -> tuple[list[dict], list[dict], int]:
    """The shipped model's ALREADY-CHECKPOINTED 42-secret combined-test-set
    records (evals/finetune/data/bakeoff_raw/gauravgandhi2411__hinglish-
    relatedness-sbert.json, produced by benchmark_bakeoff.py's Workstream A
    run) -- reused, not recomputed, since re-embedding the full vocab with
    the shipped model would just reproduce numbers already on disk."""
    cached = _load_valid_checkpoint(SHIPPED_MODEL)
    if cached is None:
        raise RuntimeError(
            f"no valid benchmark_bakeoff checkpoint for {SHIPPED_MODEL!r} -- run "
            "`uv run python -m evals.finetune.benchmark_bakeoff --model "
            f'"{SHIPPED_MODEL}"` first'
        )
    vocab_size = len(load_hien_vocab())
    return cached["dim1_records"], cached["dim2_records"], vocab_size


# ---------------------------------------------------------------------------
# Custom dim1/dim2 resolution parameterized on an arbitrary similarity
# function -- needed because quantized-vector ranking is NOT literal cosine
# similarity on a float32 matrix (int8 -> integer dot product, binary ->
# Hamming distance). Deliberately re-implemented rather than modifying
# evals/harness/dimension1_ranking.py's `_resolve_actuals` (which is
# production/test-covered code hardcoded to cosine_similarities on a
# float32 matrix) -- mirrors probe_lever_l4_distillation.py's own
# `_rank_of`/`_full_vocab_matrix` precedent of a probe-local re-
# implementation rather than widening a shared production function's
# surface for a one-off measurement.
# ---------------------------------------------------------------------------


def resolve_dim1_custom(
    raw_scenarios: list[dict],
    vocab: list[str],
    word_to_idx: dict[str, int],
    sim_fn,
) -> list[dict]:
    n = len(vocab)
    secrets = sorted({s["secret"] for s in raw_scenarios})
    rank_tables: dict[str, NDArray[np.int32]] = {}
    for secret in secrets:
        if secret not in word_to_idx:
            continue
        sims = sim_fn(word_to_idx[secret])
        order = np.argsort(-sims)
        ranks = np.empty(n, dtype=np.int32)
        for rank_minus1, idx in enumerate(order):
            ranks[idx] = rank_minus1 + 1
        rank_tables[secret] = ranks

    resolved: list[dict] = []
    for rec in raw_scenarios:
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


def resolve_dim2_custom(
    pairs: list[tuple[str, str]],
    vocab: list[str],
    word_to_idx: dict[str, int],
    sim_fn,
) -> dict:
    n = len(vocab)
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
        sims = sim_fn(word_to_idx[hien_secret])
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
    return {
        "n_pairs": len(pairs),
        "n_resolved": len(resolved),
        "pass_rate_scorching_or_hot": pass_rate,
        "records": records,
    }


# ---------------------------------------------------------------------------
# Step 2a: embedding-VECTOR quantization (int8, binary).
# ---------------------------------------------------------------------------

_POPCOUNT_TABLE = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint16)


def _make_int8_dot_sim_fn(int8_matrix: NDArray[np.int8]):
    """Factory returning a sim_fn(idx) closing over an int64-cast copy of
    `int8_matrix` computed ONCE (not per call) -- integer dot product is
    the standard scoring function for int8-quantized embeddings (used
    directly, not dequantized back to float, since the point is to measure
    what the quantized representation's OWN similarity ordering/speed looks
    like). Computed in int64 to avoid int8*int8 overflow (max |value| 127,
    dim 768 -> max |sum| ~768*127*127 ~= 1.24e7, comfortably within int64).
    Casting once here (not inside the returned closure) matters for the
    speed comparison in evaluate_embedding_vector_quantization: re-casting
    the full 10495x768 matrix on every one of 42 secret queries would
    measure the cast's cost, not the dot product's."""
    int64_matrix = int8_matrix.astype(np.int64)

    def sim_fn(idx: int) -> NDArray[np.int64]:
        return int64_matrix @ int64_matrix[idx]

    return sim_fn


def _make_hamming_sim_fn(packed_matrix: NDArray[np.int8]):
    """Factory returning a sim_fn(idx) closing over a uint8-cast copy of
    `packed_matrix` computed ONCE (see _make_int8_dot_sim_fn's docstring
    for why casting once, not per call, matters for the speed comparison).
    Negative Hamming distance (higher = more similar, consistent with every
    other sim_fn's ordering convention) between every row and row `idx` of
    a bit-packed binary-quantized matrix. XOR + popcount-by-lookup-table
    (numpy has no native popcount) -- the int8->uint8 cast reinterprets the
    same bit pattern (two's-complement-correct for same-width int<->uint
    casts), never re-derives a value."""
    u8_matrix = packed_matrix.astype(np.uint8)

    def sim_fn(idx: int) -> NDArray[np.int32]:
        xor = np.bitwise_xor(u8_matrix, u8_matrix[idx])
        return -_POPCOUNT_TABLE[xor].sum(axis=1).astype(np.int32)

    return sim_fn


def evaluate_embedding_vector_quantization(precision: str) -> dict:
    """precision: "int8" or "binary". Quantizes the shipped model's
    PRECOMPUTED full-vocab embedding matrix (embed_vocab, hi-en -- a cache
    hit if benchmark_bakeoff/eval_model already ran, matching production's
    actual usage: embed once per secret, reuse many times), recomputes
    dim1/dim2 ranking from the quantized vectors' own similarity ordering,
    then gates the result against the shipped model's cached 42-secret
    combined-test-set baseline."""
    from sentence_transformers.util import quantization as st_quantization

    vocab = load_hien_vocab()
    word_to_idx = {w: i for i, w in enumerate(vocab)}
    with _model_override_local(SHIPPED_MODEL):
        float_matrix = embed_vocab(vocab, "hi-en")
    float_bytes = float_matrix.nbytes

    quantized = st_quantization.quantize_embeddings(float_matrix, precision=precision)

    if precision == "int8":
        sim_fn = _make_int8_dot_sim_fn(quantized)
    elif precision == "binary":
        sim_fn = _make_hamming_sim_fn(quantized)
    else:
        raise ValueError(f"unsupported precision: {precision!r}")

    split = load_split()
    test_secrets = set(split["test_secrets"])
    raw_scenarios = load_combined_dim1_scenarios(test_secrets)
    dim1_records = resolve_dim1_custom(raw_scenarios, vocab, word_to_idx, sim_fn)
    dim2_pairs = combined_dim2_pairs(test_secrets)
    dim2_result = resolve_dim2_custom(dim2_pairs, vocab, word_to_idx, sim_fn)

    metrics = compute_full_metric_suite(dim1_records, dim2_result["records"], len(vocab))

    shipped_dim1, shipped_dim2, vocab_size = _shipped_baseline_records()
    gate = gate_vs_shipped(shipped_dim1, shipped_dim2, dim1_records, dim2_result["records"])

    # Pure similarity-computation speed: quantized dot-product/Hamming vs
    # float32 cosine, for ONE query against the full matrix, averaged over
    # every distinct secret in the combined test set (same secrets scored
    # above) -- this isolates ranking/lookup cost from embedding cost,
    # matching this model's actual production usage pattern (embed once,
    # rank many times per secret).
    secrets = sorted({s["secret"] for s in raw_scenarios} & set(word_to_idx))
    t0 = time.monotonic()
    for secret in secrets:
        cosine_similarities(float_matrix, float_matrix[word_to_idx[secret]])
    float_sim_s = time.monotonic() - t0
    t0 = time.monotonic()
    for secret in secrets:
        sim_fn(word_to_idx[secret])
    quantized_sim_s = time.monotonic() - t0

    result = {
        "precision": precision,
        "storage": {
            "float32_bytes": int(float_bytes),
            "quantized_bytes": int(quantized.nbytes),
            "reduction_factor": float_bytes / quantized.nbytes,
        },
        "similarity_speed": {
            "n_secrets_scored": len(secrets),
            "float32_cosine_seconds": float_sim_s,
            "quantized_seconds": quantized_sim_s,
            "speedup_factor": float_sim_s / quantized_sim_s if quantized_sim_s > 0 else None,
        },
        "metrics": metrics,
        "gate_vs_shipped": gate,
        "n_dim1_scenarios": len(dim1_records),
        "n_dim2_pairs": len(dim2_pairs),
    }
    out_path = DATA_DIR / f"{RUN_NAME}.quantize_embeddings_{precision}.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    reduction = result["storage"]["reduction_factor"]
    print(f"[{precision}] gate={gate['gate_verdict']} reduction={reduction:.1f}x")
    print(f"wrote {out_path}")
    return result


class _model_override_local:
    """Local copy of eval_model._model_override's contextmanager (same
    mechanism) so this module doesn't need to import a private helper by
    its leading-underscore name across modules for a one-line context
    manager."""

    def __init__(self, model_name_or_path: str) -> None:
        self.model_name_or_path = model_name_or_path
        self._original: str | None = None

    def __enter__(self) -> None:
        self._original = config.MODELS["hi-en"]
        config.MODELS["hi-en"] = self.model_name_or_path

    def __exit__(self, *exc: object) -> None:
        config.MODELS["hi-en"] = self._original


# ---------------------------------------------------------------------------
# Step 2b: model-WEIGHT quantization (torch.quantization.quantize_dynamic).
# ---------------------------------------------------------------------------


def transformer_state_dict_size_bytes(transformer: torch.nn.Module) -> int:
    """torch.save()'s pickled state_dict size for `transformer` -- the
    standard way to measure/report PyTorch dynamic-quantization size
    savings, since a dynamically-quantized nn.Linear holds a packed-int8
    PackedParams object that safetensors/HF's `save_pretrained` cannot
    serialize (confirmed: sentence-transformers' `model.save()` round-trips
    plain tensors only) -- this module therefore does NOT attempt to save a
    loadable HF checkpoint for the weight-quantized variant; it is
    measured/used in-memory only.

    IMPORTANT: called on BOTH the unquantized and quantized transformer with
    the identical method, so the reported delta isolates quantization's
    effect -- comparing it against `model_dir_size_bytes()` (a directory of
    safetensors + tokenizer.json + config files) would be an apples-to-
    oranges mistake (different serialization format AND the safetensors
    directory also includes ~6.4MB of tokenizer/config files this function
    never touches)."""
    import io

    buf = io.BytesIO()
    torch.save(transformer.state_dict(), buf)
    return buf.getbuffer().nbytes


def quantize_model_weights_dynamic(model_name_or_path: str) -> tuple[SentenceTransformer, int]:
    """Loads a fresh SentenceTransformer, measures its transformer body's
    state_dict size BEFORE mutating anything (the apples-to-apples
    "before" number), then applies dynamic (post-training, no-calibration-
    data) int8 quantization to every nn.Linear layer via torch.quantization.
    quantize_dynamic -- built into torch, zero new dependency (neither
    `optimum` nor `onnxruntime` is installed/locked in this repo, verified
    directly: `uv run python -c "import optimum"` / `import onnxruntime`
    both raise ModuleNotFoundError). Returns (mutated SentenceTransformer,
    unquantized_transformer_state_dict_bytes) -- the model is still
    callable via .encode() (dynamic quantization only changes HOW
    nn.Linear computes its forward pass, not the module's public
    interface)."""
    model = SentenceTransformer(model_name_or_path, token=os.environ.get("HF_TOKEN"))
    transformer = model[0].auto_model
    unquantized_bytes = transformer_state_dict_size_bytes(transformer)
    quantized_transformer = torch.quantization.quantize_dynamic(
        transformer, {torch.nn.Linear}, dtype=torch.qint8
    )
    # `auto_model` is a READ-ONLY property aliasing the real backing attribute
    # `model` (sentence_transformers.base.modules.transformer.Transformer) --
    # assigning `.auto_model` silently no-ops (nn.Module.__setattr__ stores it
    # under a throwaway `_modules` key without ever calling a property setter,
    # since there is none). This is the EXACT bug train_lib.py's
    # `_apply_capacity_control` already documents for the LoRA case -- caught
    # here empirically: a first run of this function reported IDENTICAL
    # before/after state_dict byte counts (950300721 == 950300721) and an
    # exact-zero paired-bootstrap delta vs the shipped model, which turned out
    # to mean `.encode()` was still calling the ORIGINAL unquantized
    # transformer the whole time. Must assign the real attribute `.model`.
    model[0].model = quantized_transformer
    return model, unquantized_bytes


def evaluate_weight_quantization() -> dict:
    """Full pipeline for model-weight quantization: quantize, measure size
    + pure inference latency (cold=fresh-quantize+first-encode, warm=same
    quantized instance re-encoded), embed the full vocab with the quantized
    model, recompute dim1/dim2 ranking via plain cosine_similarities on the
    resulting (still-float32-OUTPUT, since dynamic quantization only
    quantizes weights/activations internally, not the returned tensor)
    matrix, then gate vs the shipped baseline."""
    vocab = load_hien_vocab()
    word_to_idx = {w: i for i, w in enumerate(vocab)}

    t0 = time.monotonic()
    model, unquantized_transformer_bytes = quantize_model_weights_dynamic(SHIPPED_MODEL)
    matrix_cold = model.encode(
        vocab, batch_size=512, show_progress_bar=False, convert_to_numpy=True,
        normalize_embeddings=True,
    )
    cold_s = time.monotonic() - t0

    t0 = time.monotonic()
    matrix = model.encode(
        vocab, batch_size=512, show_progress_bar=False, convert_to_numpy=True,
        normalize_embeddings=True,
    )
    warm_s = time.monotonic() - t0

    quantized_transformer = model[0].auto_model
    quantized_transformer_bytes = transformer_state_dict_size_bytes(quantized_transformer)

    sim_fn = lambda idx: cosine_similarities(matrix, matrix[idx])  # noqa: E731

    split = load_split()
    test_secrets = set(split["test_secrets"])
    raw_scenarios = load_combined_dim1_scenarios(test_secrets)
    dim1_records = resolve_dim1_custom(raw_scenarios, vocab, word_to_idx, sim_fn)
    dim2_pairs = combined_dim2_pairs(test_secrets)
    dim2_result = resolve_dim2_custom(dim2_pairs, vocab, word_to_idx, sim_fn)

    metrics = compute_full_metric_suite(dim1_records, dim2_result["records"], len(vocab))
    shipped_dim1, shipped_dim2, _vocab_size = _shipped_baseline_records()
    gate = gate_vs_shipped(shipped_dim1, shipped_dim2, dim1_records, dim2_result["records"])

    n = len(vocab)
    word_embedding_params = model[0].auto_model.embeddings.word_embeddings.weight.numel()
    result = {
        "method": "torch.quantization.quantize_dynamic (nn.Linear, qint8)",
        "unquantized_model_dir_bytes": model_dir_size_bytes()["total_bytes"],
        "unquantized_transformer_state_dict_bytes": unquantized_transformer_bytes,
        "quantized_transformer_state_dict_bytes": quantized_transformer_bytes,
        "reduction_factor_transformer_body_only": (
            unquantized_transformer_bytes / quantized_transformer_bytes
        ),
        "reduction_factor_whole_model_dir_estimate": (
            model_dir_size_bytes()["total_bytes"]
            / (
                model_dir_size_bytes()["total_bytes"]
                - unquantized_transformer_bytes
                + quantized_transformer_bytes
            )
        ),
        "note": (
            "torch.quantization.quantize_dynamic only quantizes nn.Linear layers, NOT "
            "nn.Embedding -- and this model's word-embedding table "
            f"({word_embedding_params:,} params, vocab_size=197285 x hidden_size=768) is the "
            "dominant contributor to its 950MB+ size, not the 12-layer transformer body's "
            "Linear layers. So the TRANSFORMER-BODY-ONLY reduction (apples-to-apples pickled "
            "state_dict, see transformer_state_dict_size_bytes) is much larger than the "
            "WHOLE-MODEL reduction this technique actually delivers -- both are reported "
            "here, do not quote the body-only number as the whole-model saving."
        ),
        "latency": {
            "n_words": n,
            "cold_seconds": cold_s,
            "cold_ms_per_word": 1000 * cold_s / n,
            "warm_seconds": warm_s,
            "warm_ms_per_word": 1000 * warm_s / n,
            "sanity_matrix_allclose_cold_vs_warm": bool(
                np.allclose(matrix_cold, matrix, atol=1e-5)
            ),
        },
        "metrics": metrics,
        "gate_vs_shipped": gate,
        "n_dim1_scenarios": len(dim1_records),
        "n_dim2_pairs": len(dim2_pairs),
    }
    out_path = DATA_DIR / f"{RUN_NAME}.quantize_weights_dynamic.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"gate={gate['gate_verdict']} transformer body {unquantized_transformer_bytes} -> "
        f"{quantized_transformer_bytes} bytes "
        f"({result['reduction_factor_transformer_body_only']:.2f}x); whole-model estimate "
        f"reduction {result['reduction_factor_whole_model_dir_estimate']:.2f}x"
    )
    print(f"wrote {out_path}")
    return result


def run_quantize() -> dict:
    int8_result = evaluate_embedding_vector_quantization("int8")
    binary_result = evaluate_embedding_vector_quantization("binary")
    weight_result = evaluate_weight_quantization()
    return {
        "int8": int8_result,
        "binary": binary_result,
        "weight_dynamic": weight_result,
    }


# ---------------------------------------------------------------------------
# Step 3: distillation candidate (MiniLM student), same recipe/data.
# ---------------------------------------------------------------------------

DISTILL_RUN_NAME = "minilm_student"


def train_distillation_candidate() -> dict:
    """Trains MINILM_CANDIDATE with the EXACT SAME recipe as the shipped
    model (LoRA r=8/alpha=16/lr=2e-4/4 epochs/early_stopping_patience=2/
    seed=42) on the ORIGINAL production training files (train_lib.
    TrainConfig's own defaults: train_mnrl_pairs.jsonl + train_graded_
    pairs.jsonl -- never the `_variant_augmented` files from a separately
    rejected experiment). Saves to checkpoints/minilm_student/model (via
    cfg.name), never touching checkpoints/obj_hard_neg/model/ or evals/
    finetune/model/."""
    cfg = TrainConfig(
        name=DISTILL_RUN_NAME,
        base_model=MINILM_CANDIDATE,
        method="lora",
        lora_r=8,
        lora_alpha=16,
        learning_rate=2e-4,
        num_epochs=4,
        early_stopping_patience=2,
        seed=42,
    )
    t0 = time.monotonic()
    summary = run_training(cfg)
    elapsed = time.monotonic() - t0
    summary["_wall_clock_s"] = elapsed
    # run_training() already wrote RUNS_DIR/{name}.train_summary.json before this
    # key was added -- mirrors probe_lever_l4_distillation.py's documented bug fix
    # (re-write after augmenting, so evaluate_distillation_candidate() sees it).
    summary_path = DATA_DIR / "runs" / f"{DISTILL_RUN_NAME}.train_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "dev_curve"}, indent=2))
    print(f"training wall-clock: {elapsed:.1f}s")
    return summary


def evaluate_distillation_candidate() -> dict:
    """Gates the trained MiniLM student on the full metric suite vs the
    shipped model's cached 42-secret combined-test-set baseline, and
    reports its size/latency vs Step 1's baseline numbers."""
    summary_path = DATA_DIR / "runs" / f"{DISTILL_RUN_NAME}.train_summary.json"
    train_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    model_path = train_summary["output_dir"]

    vocab = load_hien_vocab()
    with _model_override_local(model_path):
        split = load_split()
        test_secrets = set(split["test_secrets"])
        raw_scenarios = load_combined_dim1_scenarios(test_secrets)
        matrix = embed_vocab(vocab, "hi-en")
    word_to_idx = {w: i for i, w in enumerate(vocab)}
    sim_fn = lambda idx: cosine_similarities(matrix, matrix[idx])  # noqa: E731
    dim1_records = resolve_dim1_custom(raw_scenarios, vocab, word_to_idx, sim_fn)
    dim2_pairs = combined_dim2_pairs(test_secrets)
    dim2_result = resolve_dim2_custom(dim2_pairs, vocab, word_to_idx, sim_fn)

    metrics = compute_full_metric_suite(dim1_records, dim2_result["records"], len(vocab))
    shipped_dim1, shipped_dim2, _vocab_size = _shipped_baseline_records()
    gate = gate_vs_shipped(shipped_dim1, shipped_dim2, dim1_records, dim2_result["records"])

    size = model_dir_size_bytes(Path(model_path))
    latency = measure_inference_latency(model_path, vocab)

    result = {
        "base_model": MINILM_CANDIDATE,
        "trained_checkpoint": model_path,
        "train_summary": {k: v for k, v in train_summary.items() if k != "dev_curve"},
        "model_dir_size": size,
        "inference_latency": latency,
        "metrics": metrics,
        "gate_vs_shipped": gate,
        "n_dim1_scenarios": len(dim1_records),
        "n_dim2_pairs": len(dim2_pairs),
    }
    out_path = DATA_DIR / f"{RUN_NAME}.distillation_eval.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"gate={gate['gate_verdict']}")
    print(f"wrote {out_path}")
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", action="store_true", help="Step 1: size + latency")
    parser.add_argument(
        "--quantize", action="store_true", help="Step 2: int8/binary + weight quantization"
    )
    parser.add_argument("--distill-train", action="store_true", help="Step 3: train MiniLM student")
    parser.add_argument(
        "--distill-eval", action="store_true", help="Step 3: gate the trained MiniLM student"
    )
    parser.add_argument(
        "--verify-untouched",
        action="store_true",
        help="sha256-verify the shipped model/checkpoint/training files were never mutated",
    )
    args = parser.parse_args()

    if args.baseline:
        run_baseline()
    if args.quantize:
        run_quantize()
    if args.distill_train:
        train_distillation_candidate()
    if args.distill_eval:
        evaluate_distillation_candidate()
    if args.verify_untouched:
        print(json.dumps(verify_protected_files_untouched(), indent=2))


if __name__ == "__main__":
    main()
