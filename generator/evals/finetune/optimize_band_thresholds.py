from __future__ import annotations

"""
Deterministic band-threshold search + candidate evaluation --
spec-metrics-ceiling-calibration.md WORKSTREAM 3 ("Calibration as the next
improvement frontier").

Scope discipline: this module NEVER edits `rival.band_for_rank` in place.
It replays already-checkpointed shipped-model dim1 records (`evals/finetune/
data/bakeoff_raw/{shipped_slug}.json` -- no re-embedding) against arbitrary
candidate (hot_max, warm_max, cold_max) threshold sets, using the SAME
`max(floor, n * fraction)` functional shape rival.py already uses for
scorching/hot/warm, so a winning candidate is a drop-in constant change, not
a new formula shape. Findings, the winning candidate (if any), and the
regression-floor/bootstrap/reachability evidence are written to
`evals/finetune/data/calibration_threshold_results.json` by this module's
`main()` (`uv run python -m evals.finetune.optimize_band_thresholds`); the
prose write-up living alongside it,
`evals/finetune/data/calibration_threshold_report.md`, is hand-authored
FROM that JSON's numbers (not auto-generated) so it can carry the diagnosis
narrative -- every number quoted there traces back to a field in the JSON.
Production `rival.py` is left untouched; the proposed diff (if a candidate
clears every gate) is reported as text, never applied.

CRITICAL correctness note (found the hard way while building this): the
`actual_band`/`in_expected_band` fields ALREADY PRESENT in `bakeoff_raw/*.
json` were computed at bake-off time and were NEVER refreshed in place when
the 900-rank warm floor shipped (commit 894f63e) -- only a separate report
(`current_state_report.json`) recomputed them. Using the raw checkpoint's
own `actual_band` field as "current shipped behaviour" would silently
compare candidates against the OLD (pre-floor) formula and misattribute
some of that floor fix's own already-known Far-tier cost (95.7% -> 93.3%)
to whatever candidate is being tested here. Every function in this module
therefore recomputes bands FRESH from `actual_rank` via `rival.band_for_rank`
(or a candidate parameterisation) rather than trusting the stored field --
see `load_shipped_records()` and `recompute_bands()`.

Run (from generator/):
    uv run python -m evals.finetune.optimize_band_thresholds
"""

import hashlib
import json
import random
from pathlib import Path
from typing import TypedDict

import numpy as np

from evals.finetune.bootstrap_ci import N_BOOT, SEED
from evals.harness import topheavy
from packs import load_pack_secrets, load_packs_meta
from rival import band_for_rank, scorching_cutoff
from schedule import load_schedule
from vocab import load_hien_vocab

DATA_DIR = Path(__file__).parent / "data"
RAW_DIR = DATA_DIR / "bakeoff_raw"
SHIPPED_MODEL = "gauravgandhi2411/hinglish-relatedness-sbert"
SHIPPED_SLUG = SHIPPED_MODEL.replace("/", "__")

_TIERS = ("near", "mid", "far")


class ThresholdParams(TypedDict):
    """One candidate boundary set -- same functional shape as production
    rival.band_for_rank (max(floor, n * fraction)) for hot/warm/cold, so any
    winning candidate is a constant swap, not a new formula. Scorching is
    deliberately NOT parameterised: it is untouched by the diagnosis (see
    module docstring / report) and the spec scopes this search to
    hot_max/warm_max/cold_max."""

    hot_floor: int
    hot_frac: float
    warm_floor: int
    warm_frac: float
    cold_floor: int
    cold_frac: float


# The currently-shipped thresholds, expressed in the same parameter shape,
# so "candidate == baseline" is a valid, checkable grid point.
CURRENT_PARAMS: ThresholdParams = {
    "hot_floor": 500,
    "hot_frac": 0.01,
    "warm_floor": 1050,  # shipped 2026-07-25 (spec-metrics-ceiling-calibration.md
    # WS3): widened from the original 900-rank floor per this module's own
    # zero-broken grid search, commit 0d9efb3. Keep in sync with rival.py.
    "warm_frac": 0.05,
    "cold_floor": 0,
    "cold_frac": 0.25,
}


def band_for_rank_params(rank: int, n: int, params: ThresholdParams) -> int:
    """Parameterised mirror of rival.band_for_rank. Identical output to
    rival.band_for_rank(rank, n) when called with CURRENT_PARAMS (verified
    by test_optimize_band_thresholds.py) -- diverges only for candidate
    threshold sets under evaluation here, never affecting the production
    function itself.
    """
    if rank == 1:
        return 0
    if rank <= scorching_cutoff(n):
        return 1
    hot_max = max(params["hot_floor"], int(n * params["hot_frac"]))
    if rank <= hot_max:
        return 2
    warm_max = max(params["warm_floor"], int(n * params["warm_frac"]), hot_max)
    if rank <= warm_max:
        return 3
    cold_max = max(params["cold_floor"], int(n * params["cold_frac"]), warm_max)
    if rank <= cold_max:
        return 4
    return 5


def load_shipped_records() -> tuple[list[dict], int]:
    """Load the shipped model's resolved dim1 records (actual_rank is not
    None) from the checkpointed bake-off, plus the real hi-en vocab size.
    Confirmed (see report) that every secret in this checkpoint is drawn
    from the hi-en scenario fixtures -- this bake-off has no EN-language
    records, so per-language optimisation is hi-en-only with this data
    (see report's "EN scope" note)."""
    path = RAW_DIR / f"{SHIPPED_SLUG}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    records = [r for r in raw["dim1_records"] if r["actual_rank"] is not None]
    n = len(load_hien_vocab())
    return records, n


def recompute_bands(
    records: list[dict], n: int, params: ThresholdParams | None = None
) -> list[dict]:
    """Return a NEW list of records with actual_band/in_expected_band
    recomputed from actual_rank under `params` (CURRENT_PARAMS if None,
    i.e. the real shipped rival.band_for_rank). Does not mutate the input.
    """
    fn = band_for_rank if params is None else lambda r, nn: band_for_rank_params(r, nn, params)
    out: list[dict] = []
    for r in records:
        b = fn(r["actual_rank"], n)
        rec = dict(r)
        rec["actual_band"] = b
        rec["in_expected_band"] = b in r["expected_bands"]
        out.append(rec)
    return out


def tier_accuracy(records: list[dict]) -> dict[str, float | None]:
    """in_expected_band rate per tier (near/mid/far), None if a tier has 0
    resolved records in this record set."""
    out: dict[str, float | None] = {}
    for t in _TIERS:
        sub = [r for r in records if r["tier"] == t]
        out[t] = (sum(1 for r in sub if r["in_expected_band"]) / len(sub)) if sub else None
    return out


def macro_tier_accuracy(records: list[dict]) -> float | None:
    """Mean of the (up to 3) per-tier accuracies -- weights near/mid/far
    equally regardless of raw record count, so far's larger n (208 vs
    mid's 84) cannot dominate the objective the way a pooled accuracy
    would. This is the joint objective used by the grid search."""
    acc = tier_accuracy(records)
    vals = [v for v in acc.values() if v is not None]
    return sum(vals) / len(vals) if vals else None


def diagnose_warm_asymmetry(records: list[dict], n: int) -> dict:
    """Step 1 of the workstream: for every mid-tier record NOT currently
    landing in Warm under the real shipped formula, bucket its actual_rank
    into a rank-distribution histogram and classify it as:
      - "too_close" (lands in scorching/hot, rank <= hot_max): NOT a
        threshold-placement problem -- no widening of Warm can rescue a
        record the model already ranked as MORE related than "mid" implies.
        This is a ranking-confound between near-tier and mid-tier at the
        low-rank end (see report).
      - "near_miss" (lands in cold, hot_max < rank <= current warm_max +
        1500): plausibly threshold-placement-fixable by widening warm_max
        moderately.
      - "deep_tail" (rank > current warm_max + 1500, i.e. deep in cold or
        in freezing): a genuine mid-range ranking error -- no defensible
        threshold width would reach these without swallowing most of
        Cold/Freezing.
    Returns histogram bins plus the bucket counts and an explicit verdict
    string (grounded in the counts, not asserted).
    """
    baseline = recompute_bands(records, n, params=None)
    mid = [r for r in baseline if r["tier"] == "mid"]
    not_warm = [r for r in mid if r["actual_band"] != 3]

    hot_max = max(CURRENT_PARAMS["hot_floor"], int(n * CURRENT_PARAMS["hot_frac"]))
    warm_max = max(CURRENT_PARAMS["warm_floor"], int(n * CURRENT_PARAMS["warm_frac"]))
    near_miss_ceiling = warm_max + 1500

    too_close = [r for r in not_warm if r["actual_rank"] <= hot_max]
    near_miss = [r for r in not_warm if hot_max < r["actual_rank"] <= near_miss_ceiling]
    deep_tail = [r for r in not_warm if r["actual_rank"] > near_miss_ceiling]

    bin_edges = [0, 50, hot_max, warm_max, near_miss_ceiling, 5000, n]
    ranks = sorted(r["actual_rank"] for r in not_warm)
    hist: list[dict] = []
    for lo, hi in zip(bin_edges[:-1], bin_edges[1:], strict=True):
        count = sum(1 for r in ranks if lo < r <= hi)
        hist.append({"lo": lo, "hi": hi, "count": count})

    n_mid = len(mid)
    n_not_warm = len(not_warm)
    frac_too_close = len(too_close) / n_not_warm if n_not_warm else None
    frac_near_miss = len(near_miss) / n_not_warm if n_not_warm else None
    frac_deep_tail = len(deep_tail) / n_not_warm if n_not_warm else None

    if n_not_warm == 0:
        verdict = "no missed mid-tier records to diagnose"
    elif frac_near_miss is not None and frac_near_miss >= 0.5:
        verdict = "predominantly threshold-placement -- widening warm_max is the primary lever"
    elif (
        frac_too_close is not None
        and frac_deep_tail is not None
        and (frac_too_close + frac_deep_tail) >= 0.5
    ):
        verdict = (
            "predominantly genuine ranking error (too-close near-tier confound + deep-tail "
            "misses), NOT threshold placement -- only a minority is recoverable by widening "
            "warm_max"
        )
    else:
        verdict = "mixed -- a minority is threshold-placement-recoverable, majority is not"

    return {
        "n_mid_total": n_mid,
        "n_mid_not_in_warm": n_not_warm,
        "hot_max": hot_max,
        "warm_max": warm_max,
        "near_miss_ceiling": near_miss_ceiling,
        "buckets": {
            "too_close": {"n": len(too_close), "fraction_of_missed": frac_too_close},
            "near_miss": {"n": len(near_miss), "fraction_of_missed": frac_near_miss},
            "deep_tail": {"n": len(deep_tail), "fraction_of_missed": frac_deep_tail},
        },
        "histogram": hist,
        "sorted_missed_ranks": ranks,
        "verdict": verdict,
    }


def regression_floor(baseline_records: list[dict], candidate_records: list[dict]) -> dict:
    """Same 'N fixed / M broken' methodology this repo already uses for
    every prior band/retraining gate (see PLAN.md, e.g. commit 894f63e's
    own before/after). baseline_records and candidate_records MUST be two
    band-recomputed views of the exact same underlying records (same order,
    same secret/word/actual_rank identity) -- typically both produced by
    recompute_bands() on the same `records` list. A record is:
      fixed:  baseline in_expected_band False -> candidate True
      broken: baseline in_expected_band True  -> candidate False
    Returns per-tier and overall counts plus the full flip detail list (for
    audit / spot-check), never silently averaged away.
    """
    fixed = 0
    broken = 0
    by_tier_fixed = dict.fromkeys(_TIERS, 0)
    by_tier_broken = dict.fromkeys(_TIERS, 0)
    detail: list[dict] = []
    for base_r, cand_r in zip(baseline_records, candidate_records, strict=True):
        assert (base_r["secret"], base_r["word"], base_r["actual_rank"]) == (
            cand_r["secret"],
            cand_r["word"],
            cand_r["actual_rank"],
        ), (
            "baseline/candidate record lists are not aligned -- pass matched "
            "recompute_bands() outputs"
        )
        cur_ok = base_r["in_expected_band"]
        new_ok = cand_r["in_expected_band"]
        if not cur_ok and new_ok:
            fixed += 1
            by_tier_fixed[base_r["tier"]] += 1
            detail.append(
                {
                    "outcome": "fixed",
                    "tier": base_r["tier"],
                    "secret": base_r["secret"],
                    "word": base_r["word"],
                    "actual_rank": base_r["actual_rank"],
                    "baseline_band": base_r["actual_band"],
                    "candidate_band": cand_r["actual_band"],
                }
            )
        elif cur_ok and not new_ok:
            broken += 1
            by_tier_broken[base_r["tier"]] += 1
            detail.append(
                {
                    "outcome": "broken",
                    "tier": base_r["tier"],
                    "secret": base_r["secret"],
                    "word": base_r["word"],
                    "actual_rank": base_r["actual_rank"],
                    "baseline_band": base_r["actual_band"],
                    "candidate_band": cand_r["actual_band"],
                }
            )
    return {
        "fixed": fixed,
        "broken": broken,
        "net": fixed - broken,
        "fixed_by_tier": by_tier_fixed,
        "broken_by_tier": by_tier_broken,
        "detail": detail,
    }


def grid_search(
    records: list[dict],
    n: int,
    hot_floors: list[int],
    hot_fracs: list[float],
    warm_floors: list[int],
    warm_fracs: list[float],
) -> list[dict]:
    """Evaluate every (hot_floor, hot_frac, warm_floor, warm_frac) combo
    against the CURRENT shipped formula (cold left at CURRENT_PARAMS
    throughout -- see report: cold_max provably cannot affect this
    objective, because far's expected_bands=[4,5] accept EITHER cold OR
    freezing, so moving the cold/freezing boundary alone never changes
    whether a far-tier record counts as correct). Returns EVERY combo's
    regression-floor result, sorted by (net desc, broken asc, fixed desc)
    -- the caller decides how to apply gates, this function does not
    filter or hide non-winning candidates.
    """
    baseline = recompute_bands(records, n, params=None)
    results: list[dict] = []
    for hot_floor in hot_floors:
        for hot_frac in hot_fracs:
            for warm_floor in warm_floors:
                for warm_frac in warm_fracs:
                    params: ThresholdParams = {
                        "hot_floor": hot_floor,
                        "hot_frac": hot_frac,
                        "warm_floor": warm_floor,
                        "warm_frac": warm_frac,
                        "cold_floor": CURRENT_PARAMS["cold_floor"],
                        "cold_frac": CURRENT_PARAMS["cold_frac"],
                    }
                    candidate = recompute_bands(records, n, params=params)
                    rf = regression_floor(baseline, candidate)
                    results.append(
                        {
                            "params": params,
                            "fixed": rf["fixed"],
                            "broken": rf["broken"],
                            "net": rf["net"],
                            "macro_tier_accuracy": macro_tier_accuracy(candidate),
                        }
                    )
    results.sort(key=lambda r: (-r["net"], r["broken"], -r["fixed"]))
    return results


# ---------------------------------------------------------------------------
# Bootstrap CI for per-band precision/recall (cluster-by-secret, same pattern
# as bootstrap_ci.py's other cluster bootstraps -- no equivalent existed yet
# for per-band P/R specifically).
# ---------------------------------------------------------------------------


def bootstrap_per_band_pr_ci(
    records: list[dict], n_boot: int = N_BOOT, seed: int = SEED
) -> dict[str, dict]:
    """Cluster-bootstrap (by secret) 95% CI for every band's precision and
    recall (topheavy.per_band_precision_recall). `records` must already
    carry the desired actual_band/in_expected_band (i.e. pass the output of
    recompute_bands(), not raw checkpoint records).
    """
    point = topheavy.per_band_precision_recall(records)
    by_secret = topheavy.group_by_secret(records)
    secrets = sorted(by_secret)
    rng = np.random.default_rng(seed)

    band_names = list(point.keys())
    prec_draws: dict[str, list[float]] = {b: [] for b in band_names}
    rec_draws: dict[str, list[float]] = {b: [] for b in band_names}

    for _ in range(n_boot):
        resample = rng.choice(secrets, size=len(secrets), replace=True).tolist()
        flat: list[dict] = []
        for s in resample:
            flat.extend(by_secret[s])
        draw = topheavy.per_band_precision_recall(flat)
        for b in band_names:
            if draw[b]["precision"] is not None:
                prec_draws[b].append(draw[b]["precision"])
            if draw[b]["recall"] is not None:
                rec_draws[b].append(draw[b]["recall"])

    out: dict[str, dict] = {}
    for b in band_names:
        pd, rd = prec_draws[b], rec_draws[b]
        out[b] = {
            "precision_point": point[b]["precision"],
            "precision_ci_95": (
                [float(np.percentile(pd, 2.5)), float(np.percentile(pd, 97.5))]
                if len(pd) >= 2
                else None
            ),
            "recall_point": point[b]["recall"],
            "recall_ci_95": (
                [float(np.percentile(rd, 2.5)), float(np.percentile(rd, 97.5))]
                if len(rd) >= 2
                else None
            ),
            "n_predicted": point[b]["n_predicted"],
            "n_expected": point[b]["n_expected"],
        }
    return out


# ---------------------------------------------------------------------------
# Realistic-guess-distribution reachability simulation (step 4c). Player
# model mirrors evals/harness/dimension5_winrate.py's adaptive-reduction +
# stall-probability noisy trajectory (same shape used for the prior 900-
# floor fix's own guess-distribution validation, per PLAN.md) -- reused
# here to check band REACHABILITY rather than win-rate: every band from 0
# (win) to 5 (freezing) must actually appear at nonzero frequency across a
# realistic population of guesses, under BOTH the current and any candidate
# threshold set, using the identical simulated trajectories for both so the
# comparison is apples-to-apples.
# ---------------------------------------------------------------------------

_SIM_STALL_PROB = 0.15
_SIM_MAX_STEPS = 60


def _simulate_trajectory(n: int, rng: random.Random) -> list[int]:
    """One noisy player trajectory's visited ranks (mirrors dimension5_
    winrate._simulate_one's reduction model exactly, but returns every
    visited rank instead of only the win/lose outcome -- band reachability
    needs the whole path, not just the endpoint). Warm/hot thresholds used
    ONLY to shape the adaptive reduction schedule (same role they play in
    rival.py/dimension5_winrate.py) -- NOT the thresholds being tested for
    reachability; band membership is classified separately by the caller
    under whichever ThresholdParams is being checked.
    """
    warm_threshold = max(900, int(n * 0.05))
    hot_threshold = max(500, int(n * 0.01))

    start_noise = rng.uniform(-0.05, 0.05)
    rank = max(2, min(n - 1, int(n * (0.40 + start_noise))))
    visited = [rank]

    for _ in range(_SIM_MAX_STEPS):
        if rank == 1:
            break
        if rng.random() < _SIM_STALL_PROB:
            wobble = rng.randint(-max(1, rank // 50), max(1, rank // 20))
            rank = max(1, min(n - 1, rank + wobble))
            visited.append(rank)
            continue
        if rank > warm_threshold:
            base, noise_std = 0.70, 0.15
        elif rank > hot_threshold:
            base, noise_std = 0.60, 0.12
        else:
            base, noise_std = 0.50, 0.10
        reduction = max(0.02, min(0.95, base + rng.gauss(0.0, noise_std)))
        rank = max(1, int(rank * (1.0 - reduction)))
        visited.append(rank)

    return visited


def _hien_puzzle_secrets() -> list[str]:
    """Every real hi-en puzzle secret: the daily schedule plus all LIVE hi-en
    packs. Same puzzle universe the prior 900-floor fix used for its own
    guess-distribution validation (118 at the time, PLAN.md: '118 real hi-en
    puzzles'); it grows as packs go live, so callers must not hard-code it."""
    secrets = list(load_schedule("hi-en"))
    for pack in load_packs_meta():
        if pack.status == "live" and "hi-en" in pack.langs:
            secrets.extend(load_pack_secrets(pack, "hi-en"))
    return secrets


def band_reachability(params: ThresholdParams, n: int, n_sims: int = 100, seed: int = SEED) -> dict:
    """Tally how often each band ordinal (0-5) is visited across n_sims
    noisy trajectories for every real hi-en puzzle secret. Returns per-band
    visit counts/fractions and the set of unreached bands (empty if every
    band is non-degenerate)."""
    secrets = _hien_puzzle_secrets()
    counts = [0] * 6
    total_steps = 0
    for secret in secrets:
        for i in range(n_sims):
            digest = hashlib.sha1(f"{secret}reachability{i}".encode()).digest()  # noqa: S324
            sim_seed = int.from_bytes(digest[:8], "big") ^ seed
            rng = random.Random(sim_seed)
            for rank in _simulate_trajectory(n, rng):
                b = band_for_rank_params(rank, n, params)
                counts[b] += 1
                total_steps += 1
    band_names = ("win", "scorching", "hot", "warm", "cold", "freezing")
    per_band = {
        band_names[i]: {"count": counts[i], "fraction": counts[i] / total_steps} for i in range(6)
    }
    unreached = [band_names[i] for i in range(6) if counts[i] == 0]
    return {
        "n_puzzles": len(secrets),
        "n_sims_per_puzzle": n_sims,
        "total_steps": total_steps,
        "per_band": per_band,
        "unreached_bands": unreached,
        "all_bands_reachable": len(unreached) == 0,
    }


# Winning candidate: chosen by the strict-zero-broken gate (see report) --
# the interior of the [1002, 1064] zero-broken plateau found by the grid
# search below, so the choice isn't sitting right at a fixture-sensitive
# edge. hot/cold left at CURRENT_PARAMS: the joint grid search (see
# main()) found no hot_floor deviation that clears zero-broken, and
# cold_max provably cannot change this objective (far accepts either
# cold or freezing -- see grid_search docstring).
WINNING_CANDIDATE: ThresholdParams = {
    "hot_floor": CURRENT_PARAMS["hot_floor"],
    "hot_frac": CURRENT_PARAMS["hot_frac"],
    "warm_floor": 1050,
    "warm_frac": CURRENT_PARAMS["warm_frac"],
    "cold_floor": CURRENT_PARAMS["cold_floor"],
    "cold_frac": CURRENT_PARAMS["cold_frac"],
}

# The more aggressive candidate explored during the joint search (higher
# raw net-fixed count) but REJECTED -- it reproduces this workstream's own
# cautionary tale (the 900-floor fix trading away Far accuracy) by trading
# away Near accuracy instead. Kept here, evaluated, and reported for
# transparency rather than silently discarded.
REJECTED_AGGRESSIVE_CANDIDATE: ThresholdParams = {
    "hot_floor": 250,
    "hot_frac": CURRENT_PARAMS["hot_frac"],
    "warm_floor": 1050,
    "warm_frac": CURRENT_PARAMS["warm_frac"],
    "cold_floor": CURRENT_PARAMS["cold_floor"],
    "cold_frac": CURRENT_PARAMS["cold_frac"],
}


def _candidate_report(
    records: list[dict], n: int, baseline: list[dict], params: ThresholdParams
) -> dict:
    candidate = recompute_bands(records, n, params=params)
    rf = regression_floor(baseline, candidate)
    ece = topheavy.band_calibration_error(candidate, n)["ece"]
    ece_baseline = topheavy.band_calibration_error(baseline, n)["ece"]
    reach = band_reachability(params, n, n_sims=100, seed=SEED)
    return {
        "params": params,
        "tier_accuracy": tier_accuracy(candidate),
        "macro_tier_accuracy": macro_tier_accuracy(candidate),
        "band_confusion": topheavy.band_confusion_matrix(candidate),
        "per_band_pr_bootstrap": bootstrap_per_band_pr_ci(candidate, n_boot=N_BOOT, seed=SEED),
        "ece": ece,
        "ece_identical_to_baseline": ece == ece_baseline,
        "regression_floor": rf,
        "band_reachability": reach,
    }


def main() -> dict:
    """Run the full WORKSTREAM 3 analysis end-to-end and write
    evals/finetune/data/calibration_threshold_results.json. Every number in
    calibration_threshold_report.md is sourced from this JSON."""
    records, n = load_shipped_records()
    baseline = recompute_bands(records, n, params=None)

    print(f"Loaded {len(records)} resolved hi-en dim1 records, vocab n={n}")

    print("Step 1: diagnosing the Warm asymmetry...")
    diagnosis = diagnose_warm_asymmetry(records, n)

    print("Step 2/3: joint grid search over (hot_floor, warm_floor)...")
    hot_floors = list(range(200, 901, 25))
    warm_floors = list(range(900, 3510, 10))
    grid_results = grid_search(
        records,
        n,
        hot_floors=hot_floors,
        hot_fracs=[0.01],
        warm_floors=warm_floors,
        warm_fracs=[0.05],
    )
    top_by_net = grid_results[:15]
    zero_broken = [r for r in grid_results if r["broken"] == 0 and r["fixed"] > 0]
    zero_broken.sort(key=lambda r: -r["fixed"])

    print("Step 3/4: evaluating baseline, winning, and rejected-aggressive candidates...")
    baseline_report = {
        "params": CURRENT_PARAMS,
        "tier_accuracy": tier_accuracy(baseline),
        "macro_tier_accuracy": macro_tier_accuracy(baseline),
        "band_confusion": topheavy.band_confusion_matrix(baseline),
        "per_band_pr_bootstrap": bootstrap_per_band_pr_ci(baseline, n_boot=N_BOOT, seed=SEED),
        "ece": topheavy.band_calibration_error(baseline, n)["ece"],
        "band_reachability": band_reachability(CURRENT_PARAMS, n, n_sims=100, seed=SEED),
    }
    winner_report = _candidate_report(records, n, baseline, WINNING_CANDIDATE)
    rejected_report = _candidate_report(records, n, baseline, REJECTED_AGGRESSIVE_CANDIDATE)

    out = {
        "shipped_model": SHIPPED_MODEL,
        "vocab_size": n,
        "n_records": len(records),
        "en_scope_note": (
            "The bake-off checkpoint this analysis replays contains ONLY hi-en secrets "
            "(42 secrets, union of evals/scenarios/dim1_hien.json + "
            "dim1_benchmark_supplement_hien.json) -- confirmed by set-membership check "
            "against dim1_en.json/dim1_benchmark_supplement_en.json's secret lists (zero "
            "overlap). No EN-language actual_rank data exists in any bakeoff_raw checkpoint, "
            "so per-language optimisation is hi-en-only with this data (no re-embedding was "
            "run, per the task's determinism/no-retraining constraint). EN's own thresholds "
            "are algebraically unaffected by any warm_floor change explored here as long as "
            "the floor stays below EN's un-floored warm_max (55000*0.05=2750) -- true for "
            "every candidate in this report."
        ),
        "diagnosis": diagnosis,
        "grid_search": {
            "hot_floors_searched": hot_floors,
            "warm_floors_searched": [warm_floors[0], warm_floors[-1], "step=10"],
            "top_15_by_net": top_by_net,
            "zero_broken_candidates_by_fixed_desc": zero_broken[:15],
        },
        "baseline": baseline_report,
        "winning_candidate": winner_report,
        "rejected_aggressive_candidate": rejected_report,
    }

    out_path = DATA_DIR / "calibration_threshold_results.json"
    out_path.write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nWrote {out_path}")
    return out


if __name__ == "__main__":
    main()
