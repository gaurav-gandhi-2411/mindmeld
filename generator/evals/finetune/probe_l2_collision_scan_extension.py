from __future__ import annotations

"""
Gated extension attempt for lever L2's Devanagari-embedding patch
(spec-model-excellence.md WORKSTREAM B, item 8, Part 2) -- STAGING ONLY.
This script NEVER writes to the live vocab/hi-en-devanagari-patch.txt; its
only on-disk outputs are evals/finetune/data/devanagari_patch_candidate.txt
(a staging copy) and this run's own eval_result.json.

Background: the current live L2 patch covers only 4 hand-picked words
(junoon/registan/jheel/udaasi). A prior attempt to patch ~5,231 dict-
coverable words (probe_l2_dict_only_front_end.py) applied the Devanagari
substitution to EVERY dict-coverable word regardless of whether that word
showed the collision signature, and CI-significantly REGRESSED dim1
Spearman (0.6568 -> 0.4731, 19 broken pairs) -- see vocab/hi-en-devanagari-
patch.txt's header comment. This script is a fundamentally different,
GATED design: only words `collision_scan.py` actually flagged as
collision-prone (collision_score >= its calibrated threshold) are
candidates, and the extension only ships (as a recommendation, never
auto-applied to the live file) if it clears BOTH the old dim1/dim2
regression floor (regression.py, zero broken pairs) AND a paired-bootstrap
check on Workstream A's full top-heavy metric suite vs the unpatched
shipped-model baseline.

Candidate curation (step 1): every word `collision_scan.py` flagged is
looked up in evals/finetune/data/devanagari_front_end_vocab_table.json.
Following the SAME precedent GG already set for the full-vocab attempt
(probe_l2_dict_only_front_end.py's documented 2026-07-23 decision): only
DICT-SOURCED entries (pmi_mine.build_romanized_to_devanagari, built from
the real Aksharantar transliteration corpus) are trusted; LLM-fallback-only
entries are excluded by default (a 40-word audit of that subset found a
20% quality-issue rate -- 5% outright garbage, 15% translations instead of
transliterations). The 4 already-shipped flagship words are always
included, using their ALREADY-GRADUATED Devanagari spellings from
probe_lever_l2_devanagari_hybrid.eval_result.json (their table entries are
themselves LLM-fallback garbage -- documented in probe_l2_dict_only_front_
end.py's docstring -- so the table is never trusted for these 4).

Mechanism for evaluating a CANDIDATE (not live) patch file: mirrors
probe_lever_l2_devanagari_hybrid.py's hybrid-vocab pattern exactly (that
module's `_resolve_actuals_hybrid`/`_dim2_for_pairs_hybrid` are reused
verbatim, since they are already parameterized on an arbitrary
matrix/word_to_idx, not hardcoded to the 4 target words) -- vocab.py's
`load_devanagari_patch`/`apply_devanagari_patch` (the LIVE-file-reading
production path) are never called here.

Run (from generator/):
    uv run python -m evals.finetune.probe_l2_collision_scan_extension
"""

import json
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from embeddings import embed_vocab
from evals.finetune.benchmark_bakeoff import combined_dim2_pairs, load_combined_dim1_scenarios
from evals.finetune.bootstrap_ci import N_BOOT, SEED, _dim1_by_secret
from evals.finetune.collision_scan import COLLISION_THRESHOLD
from evals.finetune.pmi_mine import AKSHARANTAR_PATH, build_romanized_to_devanagari
from evals.finetune.probe_lever_l2_devanagari_hybrid import (
    _dim2_for_pairs_hybrid,
    _resolve_actuals_hybrid,
)
from evals.finetune.regression import dim1_regression_floor, dim2_regression_floor
from evals.finetune.split import load_split
from evals.harness import topheavy
from vocab import load_hien_vocab

DATA_DIR = Path(__file__).parent / "data"
BAKEOFF_RAW_DIR = DATA_DIR / "bakeoff_raw"
COLLISION_REPORT_PATH = DATA_DIR / "collision_scan_report.json"
FLAGSHIP_PROBE_RESULT_PATH = DATA_DIR / "probe_lever_l2_devanagari_hybrid.eval_result.json"
CANDIDATE_PATCH_PATH = DATA_DIR / "devanagari_patch_candidate.txt"

SHIPPED_MODEL = "gauravgandhi2411/hinglish-relatedness-sbert"
SHIPPED_CHECKPOINT_PATH = BAKEOFF_RAW_DIR / "gauravgandhi2411__hinglish-relatedness-sbert.json"

FLAGSHIP_WORDS: tuple[str, ...] = ("junoon", "registan", "jheel", "udaasi")

# Bisection prefix sizes tried, in order, if the full batch fails the gate
# (largest-first so the first success found is reported; sizes chosen to
# give a reasonable "safe up to roughly here" characterization without an
# exhaustive binary search, per the task's own stated time-box).
BISECTION_PREFIX_SIZES: tuple[int, ...] = (40, 20, 10, 5)


# ---------------------------------------------------------------------------
# Step 1: candidate curation.
# ---------------------------------------------------------------------------


def load_flagship_patch() -> dict[str, str]:
    """The 4 already-shipped words' Devanagari spellings, sourced from the
    ALREADY GRADUATED 4-word probe's own result file (not re-guessed, not
    re-run) -- their devanagari_front_end_vocab_table.json entries are LLM-
    fallback garbage (documented in probe_l2_dict_only_front_end.py), so the
    table is never consulted for these 4."""
    result = json.loads(FLAGSHIP_PROBE_RESULT_PATH.read_text(encoding="utf-8"))
    resolution = result["devanagari_resolution"]
    patch: dict[str, str] = {}
    for w in FLAGSHIP_WORDS:
        deva = resolution[w]["devanagari"]
        if not deva:
            raise AssertionError(f"flagship word {w!r} has no graduated Devanagari resolution")
        patch[w] = deva
    return patch


def load_collision_prone_words() -> list[dict]:
    """Full_scan entries at/above collision_scan.COLLISION_THRESHOLD, most
    severe (highest collision_score) first -- requires collision_scan.py to
    have already been run (raises FileNotFoundError otherwise, never
    silently recomputes with different parameters)."""
    if not COLLISION_REPORT_PATH.exists():
        raise FileNotFoundError(
            f"{COLLISION_REPORT_PATH} missing -- run `uv run python -m "
            "evals.finetune.collision_scan` first"
        )
    report = json.loads(COLLISION_REPORT_PATH.read_text(encoding="utf-8"))
    return [r for r in report["full_scan"] if r["collision_score"] >= COLLISION_THRESHOLD]


def build_candidate_patch() -> tuple[dict[str, str], dict[str, str]]:
    """Returns (patch, excluded) where `patch` = flagship 4 (graduated
    spellings) UNION dict-sourced Devanagari for every collision-prone word
    NOT already in the flagship set, and `excluded` = {word: reason} for
    every collision-prone word that did NOT make it in (no table entry at
    all, or only an LLM-fallback entry -- see module docstring for why
    LLM-fallback entries are not trusted here)."""
    flagship = load_flagship_patch()
    collision_prone = load_collision_prone_words()
    rom_to_deva = build_romanized_to_devanagari(AKSHARANTAR_PATH)

    patch = dict(flagship)
    excluded: dict[str, str] = {}
    for r in collision_prone:
        w = r["word"]
        if w in patch:
            continue  # already covered by the flagship set
        if w in rom_to_deva:
            patch[w] = rom_to_deva[w]
        else:
            excluded[w] = "no Aksharantar dict entry (LLM-fallback-only or fully unresolved)"
    return patch, excluded


def write_candidate_patch_file(patch: dict[str, str], path: Path = CANDIDATE_PATCH_PATH) -> None:
    """Write `patch` to a STAGING file, same 'word: devanagari' format as
    the live vocab/hi-en-devanagari-patch.txt -- never writes to the live
    file itself."""
    lines = [
        "# STAGING candidate patch (evals.finetune.probe_l2_collision_scan_extension) --",
        "# NOT the live patch. Generated for gated-extension evaluation only; see",
        "# this module's docstring. Words ordered by collision_score descending",
        "# (flagship 4 first, unchanged from the live file).",
        "#",
        "# Format: romanized_word: devanagari_spelling",
    ]
    for w, deva in patch.items():
        lines.append(f"{w}: {deva}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Step 2/3: hybrid embedding + frozen-benchmark scoring (reuses
# probe_lever_l2_devanagari_hybrid.py's _resolve_actuals_hybrid /
# _dim2_for_pairs_hybrid verbatim -- both already parameterized on an
# arbitrary matrix/word_to_idx, not hardcoded to the 4 flagship words).
# ---------------------------------------------------------------------------


def build_hybrid_matrix(patch: dict[str, str]) -> tuple[NDArray[np.float32], dict[str, int]]:
    """Embed the full production hi-en vocab with the shipped model, except
    every `patch` word's vocab-list ENTRY is swapped for its Devanagari
    string before encoding (same positional-alignment mechanism as
    vocab.apply_devanagari_patch, reimplemented here so the LIVE file/
    load_devanagari_patch() cache is never touched for this one-off
    candidate-patch eval)."""
    hien_vocab = load_hien_vocab()
    hybrid_vocab = [patch.get(w, w) for w in hien_vocab]
    matrix = embed_vocab(hybrid_vocab, "hi-en")
    word_to_idx = {w: i for i, w in enumerate(hien_vocab)}
    return matrix, word_to_idx


def _shipped_baseline() -> dict:
    """The shipped model's already-computed bakeoff_raw checkpoint (42-
    secret/379-scenario combined test set, UNPATCHED -- benchmark_bakeoff.py
    evaluates every model with plain romanized vocab, no Devanagari
    substitution). No re-embedding of the baseline."""
    return json.loads(SHIPPED_CHECKPOINT_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Step 4: gates -- old dim1/dim2 regression floor (regression.py, reused
# verbatim) + Workstream A's full top-heavy metric suite via a paired
# bootstrap (no existing paired-topheavy-delta helper in bootstrap_ci.py,
# so one is added here, same cluster-by-secret resampling pattern as
# bootstrap_ci.paired_bootstrap_dim1_delta).
# ---------------------------------------------------------------------------


def paired_bootstrap_topheavy_delta(
    baseline_records: list[dict],
    candidate_records: list[dict],
    n_boot: int = N_BOOT,
    seed: int = SEED,
) -> dict:
    """Paired cluster-bootstrap (by secret) CI on the delta for every
    compute_topheavy_metrics submetric (NDCG@k/Recall@k/Precision@k/MRR),
    baseline vs candidate, evaluated on the SAME shared secret set. Same
    resample-once-apply-to-both pattern as
    bootstrap_ci.paired_bootstrap_dim1_delta, generalized to topheavy's
    multi-submetric shape.
    """
    base_by_secret = _dim1_by_secret(baseline_records)
    cand_by_secret = _dim1_by_secret(candidate_records)
    secrets = sorted(set(base_by_secret) & set(cand_by_secret))
    missing = set(base_by_secret) ^ set(cand_by_secret)

    base_point = topheavy.compute_topheavy_metrics([base_by_secret[s] for s in secrets])
    cand_point = topheavy.compute_topheavy_metrics([cand_by_secret[s] for s in secrets])

    rng = np.random.default_rng(seed)
    ndcg_deltas: dict[int, list[float]] = {k: [] for k in topheavy.K_VALUES}
    recall_deltas: dict[int, list[float]] = {k: [] for k in topheavy.K_VALUES}
    precision_deltas: dict[int, list[float]] = {k: [] for k in topheavy.K_VALUES}
    mrr_deltas: list[float] = []

    for _ in range(n_boot):
        resample = rng.choice(secrets, size=len(secrets), replace=True).tolist()
        base_draw = topheavy.compute_topheavy_metrics([base_by_secret[s] for s in resample])
        cand_draw = topheavy.compute_topheavy_metrics([cand_by_secret[s] for s in resample])
        for k in topheavy.K_VALUES:
            b, c = base_draw["ndcg"][k]["mean"], cand_draw["ndcg"][k]["mean"]
            if b is not None and c is not None:
                ndcg_deltas[k].append(c - b)
            b, c = base_draw["recall"][k]["mean"], cand_draw["recall"][k]["mean"]
            if b is not None and c is not None:
                recall_deltas[k].append(c - b)
            b, c = base_draw["precision"][k]["mean"], cand_draw["precision"][k]["mean"]
            if b is not None and c is not None:
                precision_deltas[k].append(c - b)
        b, c = base_draw["mrr"]["mean"], cand_draw["mrr"]["mean"]
        if b is not None and c is not None:
            mrr_deltas.append(c - b)

    def _leaf(base_leaf: dict, cand_leaf: dict, deltas: list[float]) -> dict:
        b, c = base_leaf["mean"], cand_leaf["mean"]
        if b is None or c is None or len(deltas) < 2:
            return {"baseline_point": b, "candidate_point": c, "delta_point": None, "ci_95": None}
        lo, hi = float(np.percentile(deltas, 2.5)), float(np.percentile(deltas, 97.5))
        return {
            "baseline_point": b,
            "candidate_point": c,
            "delta_point": c - b,
            "ci_95": [lo, hi],
            "ci_significant_improvement": lo > 0,
            "ci_significant_regression": hi < 0,
            "n_valid_bootstrap_draws": len(deltas),
        }

    return {
        "n_clusters": len(secrets),
        "secret_mismatch": sorted(missing) if missing else None,
        "ndcg": {
            k: _leaf(base_point["ndcg"][k], cand_point["ndcg"][k], ndcg_deltas[k])
            for k in topheavy.K_VALUES
        },
        "recall": {
            k: _leaf(base_point["recall"][k], cand_point["recall"][k], recall_deltas[k])
            for k in topheavy.K_VALUES
        },
        "precision": {
            k: _leaf(base_point["precision"][k], cand_point["precision"][k], precision_deltas[k])
            for k in topheavy.K_VALUES
        },
        "mrr": _leaf(base_point["mrr"], cand_point["mrr"], mrr_deltas),
    }


def _no_topheavy_regression(topheavy_delta: dict) -> bool:
    """True iff none of the topheavy submetrics show a CI-significant
    REGRESSION (an improvement, or a non-significant delta, both pass)."""
    for metric in ("ndcg", "recall", "precision"):
        for k in topheavy.K_VALUES:
            leaf = topheavy_delta[metric][k]
            if leaf.get("ci_significant_regression"):
                return False
    return not topheavy_delta["mrr"].get("ci_significant_regression", False)


def evaluate_candidate(patch: dict[str, str], test_secrets: set[str]) -> dict:
    """Full gate evaluation for one candidate patch dict: dim1/dim2 regression
    floor (zero-broken-pairs gate) + paired-bootstrap topheavy delta
    (Workstream A's full metric suite), both vs the unpatched shipped-model
    baseline, on the same 42-secret/379-scenario combined test set
    benchmark_bakeoff.py uses."""
    baseline = _shipped_baseline()
    matrix, word_to_idx = build_hybrid_matrix(patch)

    raw_scenarios = load_combined_dim1_scenarios(test_secrets)
    cand_dim1 = _resolve_actuals_hybrid(raw_scenarios, matrix, word_to_idx)
    dim2_pairs = combined_dim2_pairs(test_secrets)
    cand_dim2 = _dim2_for_pairs_hybrid(dim2_pairs, matrix, word_to_idx)

    dim1_floor = dim1_regression_floor(baseline["dim1_records"], cand_dim1)
    dim2_floor = dim2_regression_floor(baseline["dim2_records"], cand_dim2["records"])
    topheavy_delta = paired_bootstrap_topheavy_delta(baseline["dim1_records"], cand_dim1)

    zero_net_regression = (
        dim1_floor["zero_regression_strict"]
        and dim2_floor["zero_regression_strict"]
        and _no_topheavy_regression(topheavy_delta)
    )

    return {
        "n_patch_words": len(patch),
        "patch_words": sorted(patch),
        "dim1_regression_floor": dim1_floor,
        "dim2_regression_floor": dim2_floor,
        "topheavy_paired_delta": topheavy_delta,
        "zero_net_regression_verdict": zero_net_regression,
    }


# ---------------------------------------------------------------------------
# Step 5: bisection fallback if the full batch fails the gate.
# ---------------------------------------------------------------------------


def run_bisection(
    ranked_new_words: list[str],
    flagship: dict[str, str],
    full_patch: dict[str, str],
    test_secrets: set[str],
) -> dict:
    """Try progressively smaller prefixes of `ranked_new_words` (most-severe
    first) added on top of `flagship`, largest prefix first, stopping at the
    first prefix size that clears the gate. Returns {"attempts": [...],
    "safe_prefix_size": int | None} -- None if even the smallest tried
    prefix fails."""
    attempts = []
    safe_size = None
    for size in BISECTION_PREFIX_SIZES:
        prefix_words = ranked_new_words[:size]
        patch = dict(flagship)
        for w in prefix_words:
            patch[w] = full_patch[w]
        result = evaluate_candidate(patch, test_secrets)
        attempts.append({"prefix_size": size, **result})
        print(
            f"  bisection prefix={size}: zero_net_regression="
            f"{result['zero_net_regression_verdict']}, "
            f"dim1_broken={result['dim1_regression_floor']['n_broken']}, "
            f"dim2_broken={result['dim2_regression_floor']['n_broken']}"
        )
        if result["zero_net_regression_verdict"] and safe_size is None:
            safe_size = size
            break
    return {"attempts": attempts, "safe_prefix_size": safe_size}


def main() -> None:
    split = load_split()
    test_secrets = set(split["test_secrets"])

    flagship = load_flagship_patch()
    full_patch, excluded = build_candidate_patch()
    write_candidate_patch_file(full_patch)
    print(f"candidate patch: {len(full_patch)} words ({len(full_patch) - len(flagship)} new "
          f"+ {len(flagship)} flagship), {len(excluded)} collision-prone words excluded")
    print(f"wrote {CANDIDATE_PATCH_PATH}")

    print("evaluating FULL batch ...")
    full_result = evaluate_candidate(full_patch, test_secrets)
    print(
        f"FULL batch: zero_net_regression={full_result['zero_net_regression_verdict']}, "
        f"dim1 fixed={full_result['dim1_regression_floor']['n_fixed']} "
        f"broken={full_result['dim1_regression_floor']['n_broken']}, "
        f"dim2 fixed={full_result['dim2_regression_floor']['n_fixed']} "
        f"broken={full_result['dim2_regression_floor']['n_broken']}"
    )

    bisection = None
    if not full_result["zero_net_regression_verdict"]:
        print("FULL batch failed the gate -- running bisection fallback ...")
        ranked_new_words = [w for w in full_patch if w not in flagship]
        bisection = run_bisection(ranked_new_words, flagship, full_patch, test_secrets)
        print(f"bisection safe_prefix_size={bisection['safe_prefix_size']}")

    result = {
        "test_secrets_n": len(test_secrets),
        "excluded_candidates": excluded,
        "full_batch_result": full_result,
        "bisection": bisection,
    }
    out_path = DATA_DIR / "probe_l2_collision_scan_extension.eval_result.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
