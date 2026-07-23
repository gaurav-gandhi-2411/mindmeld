from __future__ import annotations

"""
Comparative bake-off: 8 candidate embedding models evaluated on the SAME
expanded 50-secret held-out test set (spec-hinglish-benchmark.md Phase 1b),
producing ONE comparison table with bootstrap-CI'd metrics plus paired-
bootstrap deltas against the shipped model.

Combines two sources into ONE test-set evaluation per model, since the
50-secret held-out test set (evals/finetune/data/split.json's expanded
test_secrets, commit 704cabd) spans both the original production dim1/dim2
fixtures AND the new benchmark-supplement fixtures
(evals/gen_dim1_benchmark_supplement.py):

  - dim1: evals/scenarios/dim1_hien.json (production, 25 secrets) +
    evals/scenarios/dim1_benchmark_supplement_hien.json (34 new secrets),
    both filtered to test_secrets, actual ranks resolved via the SAME
    `_resolve_actuals` dimension1_ranking.py/eval_model.py already use
    (reused, not reimplemented), then concatenated into one record list.
    n = 8 secrets/73 scenarios (production) + 34 secrets/306 scenarios
    (supplement) = 42 secrets/379 scenarios (verified empirically).
  - dim2: the original test-secret EN-HI daily-schedule pairs (however
    eval_model.py/split.json already define them: `load_daily_pairs()`
    filtered to test_secrets, n=16) union BENCHMARK_SUPPLEMENT_PAIRS
    filtered to test_secrets (n=34) = 50 pairs, zero duplicates. This is
    verified byte-identical to split.json's own precomputed `test_pairs`
    field (build_split_with_supplement() computes the exact same union) --
    reconstructed here explicitly rather than trusting the persisted field,
    so this script has no hidden coupling to split.py's internals beyond
    `load_split()`.

Methodology (spec-mandated, do not add per-model prompt prefixes): every
model is embedded with plain `model.encode(vocab)` -- no e5 "query:"/
"passage:" prefixes, no Qwen3 instruction-aware prompting -- because
production embeddings.py's embed_vocab() calls
`SentenceTransformer(model_name).encode(vocab)` uniformly with zero
per-model special-casing, and the original 9-candidate bake-off (see
PLAN.md) used the same "raw romanized input, no custom prompting"
discipline for every candidate. This measures TRUE drop-in
replaceability, not each candidate's best-case leaderboard performance --
some candidates may underperform their published numbers as a direct
consequence of this choice. State this whenever these numbers are quoted.

Crash-resilience: each model's raw records + computed metrics are saved to
evals/finetune/data/bakeoff_raw/{model_slug}.json IMMEDIATELY after that
model finishes (before moving to the next) -- a network hiccup or timeout
mid-run only costs the in-flight model, not prior progress. Re-running this
script skips any model with a valid existing checkpoint (see
`_load_valid_checkpoint`).

Usage (from generator/):
    uv run python -m evals.finetune.benchmark_bakeoff --model "<hf-model-id>"
        # evaluate + checkpoint ONE model, skip if already checkpointed
    uv run python -m evals.finetune.benchmark_bakeoff --all
        # evaluate all 8 CANDIDATE_MODELS sequentially (checkpoint-skip
        # per model), then build the final comparison table/json
    uv run python -m evals.finetune.benchmark_bakeoff --report
        # rebuild the comparison table/json from existing checkpoints only
        # (no model loading/embedding at all) -- for a quick re-render
        # after a manual per-model run
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np

from evals.finetune.bootstrap_ci import (
    bootstrap_band_ece_ci,
    bootstrap_dim1_spearman_ci,
    bootstrap_dim2_pass_rate_ci,
    bootstrap_top_weighted_correlation_ci,
    bootstrap_topheavy_ci,
    paired_bootstrap_dim1_delta,
    paired_bootstrap_dim2_delta,
)
from evals.finetune.eval_model import _model_override, dim2_for_pairs
from evals.finetune.split import load_split
from evals.gen_dim1_benchmark_supplement import BENCHMARK_SUPPLEMENT_PAIRS
from evals.harness import topheavy
from evals.harness.dimension1_ranking import _band_accuracy, _resolve_actuals
from evals.harness.pairs import load_daily_pairs
from vocab import load_hien_vocab

FINETUNE_DIR = Path(__file__).parent
DATA_DIR = FINETUNE_DIR / "data"
RAW_DIR = DATA_DIR / "bakeoff_raw"
SCENARIOS_DIR = FINETUNE_DIR.parent / "scenarios"
PROD_DIM1_PATH = SCENARIOS_DIR / "dim1_hien.json"
SUPP_DIM1_PATH = SCENARIOS_DIR / "dim1_benchmark_supplement_hien.json"

SHIPPED_MODEL = "gauravgandhi2411/hinglish-relatedness-sbert"

# The 8 candidates named in spec-hinglish-benchmark.md Phase 1b: 5 off-the-
# shelf baselines from the original bake-off, 2 newer candidates released
# since, and our shipped fine-tune (the incumbent this benchmark exists to
# evaluate). Order here is the order rendered in the final table.
CANDIDATE_MODELS: list[str] = [
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "l3cube-pune/indic-sentence-bert-nli",
    "google/muril-base-cased",
    "BAAI/bge-m3",
    "intfloat/multilingual-e5-large",
    "ibm-granite/granite-embedding-311m-multilingual-r2",
    "Qwen/Qwen3-Embedding-0.6B",
    SHIPPED_MODEL,
]

# A checkpoint missing any of these keys is treated as incomplete/corrupt
# and recomputed rather than trusted (crash-resilience requirement).
REQUIRED_CHECKPOINT_KEYS = {
    "model",
    "dim1_spearman_ci",
    "dim2_pass_rate_ci",
    "band_accuracy",
    "near_far_separation",
    "dim1_records",
    "dim2_records",
    "n_dim1_secrets",
    "n_dim1_scenarios",
    "n_dim2_pairs",
    # spec-model-excellence.md WORKSTREAM A — task-appropriate top-heavy
    # ranking + band-calibration metrics. Adding these keys correctly
    # invalidates every pre-existing checkpoint (they predate this change),
    # forcing a full recompute rather than silently reusing incomplete data.
    "topheavy_ci",
    "top_weighted_correlation_ci",
    "band_confusion",
    "per_band_pr",
    "band_ece_ci",
}


def _slug(model_name: str) -> str:
    """Filesystem-safe checkpoint filename for a HF model id (e.g.
    'BAAI/bge-m3' -> 'BAAI__bge-m3')."""
    return model_name.replace("/", "__")


def checkpoint_path(model_name: str) -> Path:
    """Path to the on-disk checkpoint for one model's bake-off results."""
    return RAW_DIR / f"{_slug(model_name)}.json"


def _denormalize_topheavy_k_keys(data: dict) -> None:
    """JSON object keys are always strings, so `topheavy_ci`'s per-k
    sub-dicts (topheavy.K_VALUES = (10, 50, 100), used as dict keys
    in-memory) round-trip through a checkpoint file as {"10": ..., "50":
    ..., "100": ...} instead of {10: ..., 50: ..., 100: ...}. Mutates
    `data["topheavy_ci"]` in place back to int keys so every downstream
    consumer (build_comparison, callers) can rely on int keys regardless
    of whether the result came from a fresh evaluate_one_model() call or a
    reloaded checkpoint. No-op if topheavy_ci is absent (older/invalid
    checkpoint, already rejected by the required-keys check) or already
    int-keyed."""
    th = data.get("topheavy_ci")
    if not isinstance(th, dict):
        return
    for metric in ("ndcg", "recall", "precision"):
        section = th.get(metric)
        if isinstance(section, dict):
            th[metric] = {int(k): v for k, v in section.items()}


def _load_valid_checkpoint(model_name: str) -> dict | None:
    """Return the checkpoint dict if it exists and is well-formed, else
    None (missing file, corrupt JSON, or missing required keys are all
    treated as "needs (re)computation", never trusted silently)."""
    path = checkpoint_path(model_name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not REQUIRED_CHECKPOINT_KEYS.issubset(data.keys()):
        return None
    _denormalize_topheavy_k_keys(data)
    return data


def load_combined_dim1_scenarios(test_secrets: set[str]) -> list[dict]:
    """Raw (unresolved) dim1 scenarios for `test_secrets`, concatenated from
    the production fixture (25 secrets) and the benchmark-supplement
    fixture (34 secrets). Pure file-IO + filtering only -- no model/
    embedding call involved, so this is independently unit-testable without
    any network access or model download.
    """
    prod = json.loads(PROD_DIM1_PATH.read_text(encoding="utf-8"))
    supp = json.loads(SUPP_DIM1_PATH.read_text(encoding="utf-8"))
    prod_filtered = [r for r in prod if r["secret"] in test_secrets]
    supp_filtered = [r for r in supp if r["secret"] in test_secrets]
    return prod_filtered + supp_filtered


def combined_dim2_pairs(test_secrets: set[str]) -> list[tuple[str, str]]:
    """(en_secret, hien_secret) pairs for `test_secrets`: the original
    daily-schedule test pairs union BENCHMARK_SUPPLEMENT_PAIRS. Verified
    (see module docstring) to be set-identical to split.json's own
    precomputed `test_pairs` field. Pure -- no model call.
    """
    daily_pairs = load_daily_pairs()
    original = [(en, hien) for en, hien in daily_pairs if hien in test_secrets]
    supplement = [
        (en, hien) for hien, en, _domain in BENCHMARK_SUPPLEMENT_PAIRS if hien in test_secrets
    ]
    combined = original + supplement
    assert len(combined) == len(set(combined)), "duplicate dim2 pair across sources"
    return combined


def near_far_separation(dim1_records: list[dict], vocab_size: int) -> float | None:
    """
    near_far_separation = mean(rank_percentile | tier == "far")
                         - mean(rank_percentile | tier == "near")
    where rank_percentile = actual_rank / vocab_size (~0 = ranked most
    related to the secret, ~1 = ranked least related). Computed over
    resolved records only (actual_rank is not None), pooled across the
    combined test-set records for one model.

    Larger positive = better separation: far-tier words are correctly
    ranked farther away (higher percentile) than near-tier words. ~0 or
    negative means the model fails to distinguish near from far.

    Returns None if either tier has zero resolved records (can't compute a
    meaningful mean).
    """
    near_pcts = [
        r["actual_rank"] / vocab_size
        for r in dim1_records
        if r["tier"] == "near" and r["actual_rank"] is not None
    ]
    far_pcts = [
        r["actual_rank"] / vocab_size
        for r in dim1_records
        if r["tier"] == "far" and r["actual_rank"] is not None
    ]
    if not near_pcts or not far_pcts:
        return None
    return float(np.mean(far_pcts) - np.mean(near_pcts))


def evaluate_one_model(model_name: str, test_secrets: set[str], vocab_size: int) -> dict:
    """Full combined-set evaluation for one model: dim1 Spearman+CI, dim2
    pass-rate+CI, band-accuracy (overall/near/mid/far), near/far
    separation -- plus the raw record lists (needed later for paired-
    bootstrap deltas against the shipped model).

    Both dim1 and dim2 resolution happen inside ONE `_model_override` block
    so both reuse the SAME cached hi-en vocab embedding matrix (embed_vocab
    caches by (model_name, vocab) -- dim1's `_resolve_actuals` call embeds
    the full vocab first, dim2_for_pairs's internal embed_vocab call is then
    a cache hit), so each model only pays the download+inference cost once.
    """
    with _model_override(model_name):
        raw_scenarios = load_combined_dim1_scenarios(test_secrets)
        dim1_records = _resolve_actuals(raw_scenarios, "hi-en")
        dim2_pairs = combined_dim2_pairs(test_secrets)
        dim2_result = dim2_for_pairs(dim2_pairs)

    dim1_ci = bootstrap_dim1_spearman_ci(dim1_records)
    dim2_ci = bootstrap_dim2_pass_rate_ci(dim2_result["records"])

    by_tier = {t: [r for r in dim1_records if r["tier"] == t] for t in ("near", "mid", "far")}
    band_accuracy = {
        "overall": _band_accuracy(dim1_records),
        "near": _band_accuracy(by_tier["near"]),
        "mid": _band_accuracy(by_tier["mid"]),
        "far": _band_accuracy(by_tier["far"]),
    }

    # spec-model-excellence.md WORKSTREAM A — task-appropriate top-heavy
    # ranking metrics (NDCG/MRR/Recall/Precision@k, top-emphasising
    # correlation) and band-calibration metrics (confusion matrix, per-band
    # P/R, ECE), all bootstrap-CI'd where applicable. See evals/harness/topheavy.py.
    topheavy_ci = bootstrap_topheavy_ci(dim1_records)
    top_weighted_correlation_ci = bootstrap_top_weighted_correlation_ci(dim1_records)
    band_confusion = topheavy.band_confusion_matrix(dim1_records)
    per_band_pr = topheavy.per_band_precision_recall(dim1_records)
    band_ece_ci = bootstrap_band_ece_ci(dim1_records, vocab_size)

    return {
        "model": model_name,
        "n_dim1_secrets": len({r["secret"] for r in dim1_records}),
        "n_dim1_scenarios": len(dim1_records),
        "n_dim2_pairs": len(dim2_pairs),
        "dim1_spearman_ci": dim1_ci,
        "dim2_pass_rate_ci": dim2_ci,
        "band_accuracy": band_accuracy,
        "near_far_separation": near_far_separation(dim1_records, vocab_size),
        "topheavy_ci": topheavy_ci,
        "top_weighted_correlation_ci": top_weighted_correlation_ci,
        "band_confusion": band_confusion,
        "per_band_pr": per_band_pr,
        "band_ece_ci": band_ece_ci,
        "dim1_records": dim1_records,
        "dim2_records": dim2_result["records"],
    }


def run_model(model_name: str, test_secrets: set[str], vocab_size: int) -> dict:
    """Load an existing valid checkpoint if present, else evaluate the model
    and save its checkpoint immediately -- this must fully complete (write
    to disk) for model N before model N+1 starts, per the crash-resilience
    requirement (a killed/interrupted run resumes from the last saved
    checkpoint instead of losing all prior progress)."""
    cached = _load_valid_checkpoint(model_name)
    if cached is not None:
        print(f"[checkpoint hit] {model_name}")
        return cached

    print(f"[running] {model_name}")
    t0 = time.monotonic()
    result = evaluate_one_model(model_name, test_secrets, vocab_size)
    result["wall_clock_seconds"] = round(time.monotonic() - t0, 1)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    checkpoint_path(model_name).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"[checkpoint saved] {model_name} ({result['wall_clock_seconds']}s)")
    return result


def _fmt_ci(point: float | None, ci: list[float] | None) -> str:
    if point is None or ci is None:
        return "n/a"
    return f"{point:.4f} [{ci[0]:.4f}, {ci[1]:.4f}]"


def _fmt_band(band: dict) -> str:
    def f(v: float | None) -> str:
        return f"{v:.3f}" if v is not None else "n/a"

    return f"{f(band['overall'])} / {f(band['near'])} / {f(band['mid'])} / {f(band['far'])}"


def _verdict(delta: dict) -> str:
    if delta["ci_significant_improvement"]:
        return "sig. improve"
    if delta["ci_significant_regression"]:
        return "sig. regress"
    return "not sig."


def _fmt_leaf(leaf: dict | None) -> str:
    """Format a bootstrap_topheavy_ci-style leaf {"point", "ci_95",
    "n_valid_bootstrap_draws", "n_secrets_point_estimate"} (or the
    n_clusters-keyed shape used by bootstrap_top_weighted_correlation_ci /
    bootstrap_band_ece_ci) as "point [lo, hi] (n=k)"."""
    if leaf is None:
        return "n/a"
    base = _fmt_ci(leaf["point"], leaf["ci_95"])
    n = leaf.get("n_secrets_point_estimate", leaf.get("n_clusters"))
    if base == "n/a" or n is None:
        return base
    return f"{base} (n={n})"


def _fmt_band_confusion(confusion: dict) -> str:
    """Render a 3x6 band-confusion matrix as a compact markdown table."""
    header = "| tier | " + " | ".join(confusion["bands"]) + " |"
    sep = "|---|" + "---|" * len(confusion["bands"])
    rows = [header, sep]
    for tier, row in zip(confusion["tiers"], confusion["matrix"], strict=True):
        rows.append(f"| {tier} | " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(rows) + "\n"


def _fmt_per_band_pr(per_band: dict) -> str:
    """Render per-band precision/recall as a compact markdown table."""
    lines = [
        "| band | precision | recall | n_predicted | n_expected |",
        "|---|---|---|---|---|",
    ]
    for band, stats in per_band.items():
        p = f"{stats['precision']:.3f}" if stats["precision"] is not None else "n/a"
        r = f"{stats['recall']:.3f}" if stats["recall"] is not None else "n/a"
        lines.append(f"| {band} | {p} | {r} | {stats['n_predicted']} | {stats['n_expected']} |")
    return "\n".join(lines) + "\n"


def build_comparison(results: dict[str, dict]) -> tuple[str, dict]:
    """Build the final markdown table + raw JSON summary from all models'
    (possibly-failed) results. Computes paired dim1/dim2 deltas of the
    SHIPPED model vs every other successfully-evaluated model (delta =
    shipped - other; positive + ci_significant_improvement means the
    shipped model leads that candidate with statistical significance)."""
    shipped = results.get(SHIPPED_MODEL)
    paired_deltas: dict[str, dict] = {}
    if shipped is not None and shipped.get("error") is None:
        for name, res in results.items():
            if name == SHIPPED_MODEL or res.get("error") is not None:
                continue
            # baseline=other model, candidate=shipped -> delta_point = shipped - other
            dim1_delta = paired_bootstrap_dim1_delta(res["dim1_records"], shipped["dim1_records"])
            dim2_delta = paired_bootstrap_dim2_delta(res["dim2_records"], shipped["dim2_records"])
            paired_deltas[name] = {"dim1": dim1_delta, "dim2": dim2_delta}

    lines = [
        "| model | dim1 Spearman [95% CI] | dim2 pass-rate [95% CI] | "
        "band-acc (overall/near/mid/far) | near/far separation | delta vs shipped |",
        "|---|---|---|---|---|---|",
    ]
    for name in CANDIDATE_MODELS:
        res = results.get(name)
        if res is None or res.get("error") is not None:
            err = res.get("error") if res else "not run"
            lines.append(f"| {name} | FAILED | FAILED | FAILED | FAILED | {err} |")
            continue
        dim1_str = _fmt_ci(res["dim1_spearman_ci"]["point"], res["dim1_spearman_ci"]["ci_95"])
        dim2_str = _fmt_ci(res["dim2_pass_rate_ci"]["point"], res["dim2_pass_rate_ci"]["ci_95"])
        band_str = _fmt_band(res["band_accuracy"])
        sep = res["near_far_separation"]
        sep_str = f"{sep:.4f}" if sep is not None else "n/a"
        if name == SHIPPED_MODEL:
            delta_str = "—"
        elif name in paired_deltas:
            d1, d2 = paired_deltas[name]["dim1"], paired_deltas[name]["dim2"]
            delta_str = (
                f"dim1 {d1['delta_point']:+.4f} ({_verdict(d1)}); "
                f"dim2 {d2['delta_point']:+.4f} ({_verdict(d2)})"
            )
        else:
            delta_str = "n/a (shipped model failed)"
        lines.append(f"| {name} | {dim1_str} | {dim2_str} | {band_str} | {sep_str} | {delta_str} |")

    # ------------------------------------------------------------------
    # spec-model-excellence.md WORKSTREAM A — second table: top-heavy
    # ranking + calibration metrics. Kept as its own table rather than
    # widening the table above (8 models x ~15 metric columns is
    # unreadable as one flat table); same row order/model names as above.
    # ------------------------------------------------------------------
    topheavy_lines = [
        "| model | NDCG@10 | NDCG@50 | NDCG@100 | MRR | Recall@10 | Recall@50 | Recall@100 | "
        "Precision@10 | Precision@50 | Precision@100 | top-weighted corr | band ECE |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name in CANDIDATE_MODELS:
        res = results.get(name)
        if res is None or res.get("error") is not None:
            err = res.get("error") if res else "not run"
            topheavy_lines.append(f"| {name} | " + " FAILED |" * 11 + f" {err} |")
            continue
        th = res["topheavy_ci"]
        row = [
            _fmt_leaf(th["ndcg"][10]),
            _fmt_leaf(th["ndcg"][50]),
            _fmt_leaf(th["ndcg"][100]),
            _fmt_leaf(th["mrr"]),
            _fmt_leaf(th["recall"][10]),
            _fmt_leaf(th["recall"][50]),
            _fmt_leaf(th["recall"][100]),
            _fmt_leaf(th["precision"][10]),
            _fmt_leaf(th["precision"][50]),
            _fmt_leaf(th["precision"][100]),
            _fmt_leaf(res["top_weighted_correlation_ci"]),
            _fmt_leaf(res["band_ece_ci"]),
        ]
        topheavy_lines.append(f"| {name} | " + " | ".join(row) + " |")
    topheavy_table_md = "\n".join(topheavy_lines) + "\n"

    # ------------------------------------------------------------------
    # Band confusion matrix + per-band precision/recall: SHIPPED model only
    # (rendering all 8 models' full confusion matrices would be excessive
    # for this deliverable -- explicitly scoped per spec-model-excellence.md
    # WORKSTREAM A, item 2/4).
    # ------------------------------------------------------------------
    shipped_calibration_md = ""
    if shipped is not None and shipped.get("error") is None:
        shipped_calibration_md = (
            f"\n### Band calibration -- shipped model ({SHIPPED_MODEL}) only\n\n"
            "Band-confusion matrix (rows = human-authored tier, cols = model-predicted band, "
            "cell = record count):\n\n"
            f"{_fmt_band_confusion(shipped['band_confusion'])}\n"
            "Per-band precision/recall (does the model say Warm when a human meant Warm?):\n\n"
            f"{_fmt_per_band_pr(shipped['per_band_pr'])}"
        )

    table_md = "\n".join(lines) + "\n\n" + topheavy_table_md + shipped_calibration_md
    summary = {
        "models": CANDIDATE_MODELS,
        "shipped_model": SHIPPED_MODEL,
        "results": {
            name: {k: v for k, v in res.items() if k not in ("dim1_records", "dim2_records")}
            for name, res in results.items()
        },
        "paired_deltas_vs_shipped": paired_deltas,
    }
    return table_md, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="Evaluate/checkpoint ONE model by HF id, then exit")
    parser.add_argument("--all", action="store_true", help="Evaluate all 8 CANDIDATE_MODELS")
    parser.add_argument(
        "--report",
        action="store_true",
        help="Rebuild the comparison table/json from existing checkpoints only (no model runs)",
    )
    args = parser.parse_args()

    split = load_split()
    test_secrets = set(split["test_secrets"])
    vocab_size = len(load_hien_vocab())

    if args.model:
        run_model(args.model, test_secrets, vocab_size)
        return

    results: dict[str, dict] = {}
    if args.report:
        for name in CANDIDATE_MODELS:
            cached = _load_valid_checkpoint(name)
            results[name] = (
                cached if cached is not None else {"model": name, "error": "no checkpoint found"}
            )
    else:
        for name in CANDIDATE_MODELS:
            try:
                results[name] = run_model(name, test_secrets, vocab_size)
            # Broad except is deliberate here: one candidate's load/download/OOM
            # failure must be recorded and reported, never silently abort the
            # whole 8-model sweep or drop that model from the final table.
            except Exception as exc:  # noqa: BLE001
                print(f"[FAILED] {name}: {exc}")
                results[name] = {"model": name, "error": str(exc)}

    table_md, summary = build_comparison(results)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "bakeoff_comparison.md").write_text(table_md, encoding="utf-8")
    (DATA_DIR / "bakeoff_comparison.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(table_md)
    print(f"Wrote {DATA_DIR / 'bakeoff_comparison.md'} and bakeoff_comparison.json")


if __name__ == "__main__":
    main()
