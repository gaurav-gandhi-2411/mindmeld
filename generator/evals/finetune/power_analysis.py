from __future__ import annotations

"""
spec-model-excellence.md WORKSTREAM D, item 12 -- statistical power analysis.

Context (see probe_l2_patch_l5_combined.eval_result.json's
dim1_delta_vs_shipped): the L2-patch + L5 production wrapper's dim1
Spearman improvement on the frozen 34-secret PUBLIC benchmark
(gauravgandhi2411/hinglish-relatedness-benchmark) is delta_point=+0.0602,
95% CI [-0.00167, +0.1435], n_clusters=34 -- a near-miss (the lower bound
missed zero by only 0.0017). This module asks: how much benchmark
expansion would it take for an effect of that magnitude to reliably clear
significance, and what does the empirical CI-width-vs-n relationship
measured off REAL data actually look like (as opposed to an assumed
formula)?

Three distinct secret pools exist in this repo (do not conflate them):
  (a) 25-secret production set (evals/scenarios/dim1_hien.json)
  (b) 34-secret PUBLIC benchmark, frozen/published content
      (evals/finetune/data/public_benchmark_staging/dim1_hien.json --
      confirmed the FINAL post-scrub content per
      public_benchmark_reverify.py's docstring; NOT the same content as
      evals/scenarios/dim1_benchmark_supplement_hien.json, which is the
      PRE-swap engineering copy still used as the "production" supplement
      file by benchmark_bakeoff.py -- 302 vs 306 records, verified by
      direct diff, same 34 secrets)
  (c) 42-secret INTERNAL-ONLY combined pool (8 test-split secrets from (a)
      + 34 from the pre-swap supplement file, per
      benchmark_bakeoff.load_combined_dim1_scenarios) -- never published,
      but the LARGEST pool available for measuring how CI width empirically
      shrinks with n, so Step 1/2's empirical (non-extrapolated) results
      are computed against (c) and reused via the already-checkpointed
      evals/finetune/data/bakeoff_raw/gauravgandhi2411__hinglish-
      relatedness-sbert.json (no re-embedding). Conclusions are reported in
      terms of what they mean for (b), the 34-secret PUBLIC benchmark,
      since that is the pool the spec's "34 secrets couldn't clear
      significance" complaint (item 12) is actually about.

Four steps, run in order (see main()):
  1. Empirical CI-width-vs-n curve: subsample k secrets (without
     replacement) from pool (c)'s 42, run the SAME cluster-bootstrap CI
     machinery bootstrap_ci.py already uses, record CI width. Median/IQR
     per k -- grounded in real data, no synthetic effect needed.
  2. Minimum-detectable-effect (MDE) simulation: inject a paired effect
     into k-secret subsamples and measure what fraction of repeated draws
     yield a CI lower bound > 0 ("detected"), for effect sizes
     {0.04, 0.06, 0.10}. TWO curves are computed:
       (a) real-data curve, k in {20,25,30,34}: uses the ACTUAL observed
           per-secret L2-patch+L5 effect (reconstructed from
           probe_lever_l2_devanagari_hybrid.py's hybrid-matrix machinery
           with the already-resolved Devanagari spellings hardcoded below
           -- qwen3:8b is not pulled in this environment so the live LLM
           fallback can't be re-run, but the dict-primary resolution path
           plus these frozen, already-resolved spellings reproduce the
           EXACT matrix the original probe used; verified below by
           reproducing delta_point=0.060180439686178366 byte-for-byte
           against probe_l2_patch_l5_combined.eval_result.json). Limited to
           k<=34 because real per-secret effect data only exists for the 34
           public-benchmark secrets -- it does not naturally extend to
           secrets outside that set.
       (b) calibrated-synthetic curve, ALL k in {20,25,30,34,38,42}: a
           parametric rank-shift injection (see inject_synthetic_effect),
           with its single intensity parameter CALIBRATED so that at k=34
           it reproduces each target effect size's magnitude (validated by
           comparing calibration-curve output at k=34, effect_size~0.06
           against the real curve's own k=34 point -- see
           "calibration_validation" in the report). This is the fallback
           the task spec explicitly sanctions when real per-secret data
           can't cover the full k range: "failing that, synthetically
           perturb ... calibrated to reproduce roughly the same +0.06
           pooled delta magnitude". Used as the PRIMARY curve for the "how
           many more secrets" conclusion because it is the only one that
           covers k>34.
  3. Extrapolation: fit width(n) = C / sqrt(n) to the Step 1 empirical
     curve (n<=42 only), extrapolate to n=50/60/80. Labelled an
     EXTRAPOLATION (parametric assumption) throughout -- distinct from the
     measured n<=42 results.
  4. Conclusion: plain-language recommendation for GG (does NOT author any
     new benchmark secrets -- that is a separate, deliberate content-
     authoring effort per the mechanical-cost research cited in the spec).

Run (from generator/):
    uv run python -m evals.finetune.power_analysis
"""

import json
from pathlib import Path

import numpy as np

from evals.finetune.bootstrap_ci import (
    _dim1_by_secret,
    _dim1_spearman_for_secrets,
    bootstrap_dim1_spearman_ci,
    paired_bootstrap_dim1_delta,
)
from evals.finetune.probe_lever_l2_devanagari_hybrid import (
    _public_benchmark_dim1_records_hybrid,
    _shipped_model_dim1_records_34,
    build_hybrid_matrix,
)
from vocab import load_hien_vocab

FINETUNE_DIR = Path(__file__).parent
DATA_DIR = FINETUNE_DIR / "data"
BAKEOFF_RAW_DIR = DATA_DIR / "bakeoff_raw"
SHIPPED_CHECKPOINT_PATH = BAKEOFF_RAW_DIR / "gauravgandhi2411__hinglish-relatedness-sbert.json"
OUT_JSON = DATA_DIR / "power_analysis_report.json"
OUT_MD = DATA_DIR / "power_analysis_report.md"

SEED = 42
K_VALUES: tuple[int, ...] = (20, 25, 30, 34, 38, 42)
EXTRAPOLATE_N: tuple[int, ...] = (50, 60, 80)
EFFECT_SIZES: tuple[float, ...] = (0.04, 0.06, 0.10)
DETECTION_TARGET = 0.80

# Reduced vs bootstrap_ci.N_BOOT (10000) -- this module runs the bootstrap
# machinery thousands of times (once per subsample draw), so a full 10000
# inner iterations per draw is computationally infeasible at this scale.
# 400 is a documented computational-budget tradeoff: stable enough for a
# median/IQR summary over many draws and for a binary "did the CI lower
# bound cross zero" decision, not intended to replace the module's own
# 10000-iteration default when computing a single headline CI.
INNER_N_BOOT = 400

N_DRAWS_CI_WIDTH = 200  # step 1: subsample draws per k
N_DRAWS_CI_WIDTH_FULL_POOL = 30  # k == pool size: only bootstrap-RNG noise varies
N_SIMS_MDE = 150  # step 2: simulated draws per (k, effect_size)

CALIBRATION_K = 34  # matches the real observed effect's n_clusters=34
CALIBRATION_TRIALS = 15
CALIBRATION_INTENSITY_GRID: tuple[float, ...] = (
    0.005,
    0.01,
    0.02,
    0.03,
    0.05,
    0.08,
    0.12,
    0.18,
    0.25,
    0.35,
    0.50,
)
AFFECTED_SECRET_FRAC = 0.4  # fraction of a k-subsample's secrets that carry the injected effect

# Frozen, already-resolved Devanagari spellings for L2's 4 target words, copied
# verbatim from evals/finetune/data/probe_l2_patch_l5_combined.eval_result.json's
# l2_devanagari_resolution field. resolve_target_devanagari() cannot be re-run
# live in this environment (qwen3:8b is not pulled locally -- confirmed by a
# live "Could not reach local Ollama ... model=qwen3:8b" failure when this
# module was written), but the dict-primary resolution path is deterministic
# and these 4 spellings are the ORIGINAL run's actual resolved values, so
# hardcoding them here reproduces the exact hybrid matrix the original probe
# built. Verified below (see reconstruct_real_l2_l5_effect) to reproduce
# delta_point=0.060180439686178366 byte-for-byte against the checked-in
# probe_l2_patch_l5_combined.eval_result.json.
_FROZEN_L2_DEVANAGARI_RESOLUTION: dict[str, dict[str, str]] = {
    "junoon": {"devanagari": "जुनून", "source": "llm:qwen3:8b"},
    "registan": {"devanagari": "रेगिस्तान", "source": "llm:qwen3:8b"},
    "jheel": {"devanagari": "झील", "source": "llm:qwen3:8b"},
    "udaasi": {"devanagari": "उदासी", "source": "llm:qwen3:8b"},
}
# from probe_l2_patch_l5_combined.eval_result.json's dim1_delta_vs_shipped.delta_point
_EXPECTED_REAL_DELTA_POINT = 0.060180439686178366


def load_combined_dim1_records() -> list[dict]:
    """dim1_records for the shipped model on pool (c), the 42-secret internal
    combined pool -- reused as-is from the already-checkpointed bakeoff_raw
    file (benchmark_bakeoff.evaluate_one_model's output). No re-embedding."""
    data = json.loads(SHIPPED_CHECKPOINT_PATH.read_text(encoding="utf-8"))
    return data["dim1_records"]


def reconstruct_real_l2_l5_effect() -> tuple[list[dict], list[dict]]:
    """Reconstruct the REAL (not synthetic) shipped-vs-L2-patched dim1 record
    pairs for the 34-secret PUBLIC benchmark, by rebuilding the exact hybrid
    embedding matrix probe_l2_patch_l5_combined.py used (L2's 4 target words
    substituted with their Devanagari spelling, everything else unchanged --
    see build_hybrid_matrix). Uses the frozen already-resolved Devanagari
    spellings above rather than a live LLM call. Returns
    (shipped_dim1_records_34, hybrid_dim1_records_34).

    Sanity-checked against the checked-in eval_result.json: this must
    reproduce delta_point=0.060180439686178366 exactly (both runs are
    deterministic given the same frozen Devanagari resolution and the same
    shipped-model checkpoint), or the reconstruction is wrong and should not
    be trusted as "real data" downstream.
    """
    matrix, word_to_idx = build_hybrid_matrix(_FROZEN_L2_DEVANAGARI_RESOLUTION)
    hybrid_dim1 = _public_benchmark_dim1_records_hybrid(matrix, word_to_idx)
    shipped_dim1 = _shipped_model_dim1_records_34()
    check = paired_bootstrap_dim1_delta(shipped_dim1, hybrid_dim1, n_boot=INNER_N_BOOT, seed=SEED)
    if abs(check["delta_point"] - _EXPECTED_REAL_DELTA_POINT) > 1e-9:
        raise RuntimeError(
            "reconstructed L2+L5 hybrid dim1 records do not reproduce the checked-in "
            f"probe_l2_patch_l5_combined.eval_result.json delta_point "
            f"({check['delta_point']!r} vs expected {_EXPECTED_REAL_DELTA_POINT!r}) -- "
            "the reconstruction is stale or wrong, do not trust it as real data"
        )
    return shipped_dim1, hybrid_dim1


# ---------------------------------------------------------------------------
# Step 1: empirical CI-width-vs-n curve.
# ---------------------------------------------------------------------------


def _ci_width_for_subsample(
    records_by_secret: dict[str, list[dict]], secrets: list[str], seed: int
) -> float:
    recs = [r for s in secrets for r in records_by_secret[s]]
    ci = bootstrap_dim1_spearman_ci(recs, n_boot=INNER_N_BOOT, seed=seed)
    lo, hi = ci["ci_95"]
    return hi - lo


def empirical_ci_width_curve(records: list[dict], k_values: tuple[int, ...] = K_VALUES) -> dict:
    """For each k, repeatedly subsample k secrets WITHOUT replacement from
    the full pool, run the cluster-bootstrap dim1 Spearman CI on that
    subsample, and record the CI width. Returns median/IQR/n_draws per k --
    this is the measured (not assumed) relationship between benchmark size
    and CI width."""
    by_secret = _dim1_by_secret(records)
    all_secrets = sorted(by_secret)
    pool_size = len(all_secrets)
    rng = np.random.default_rng(SEED)
    out: dict[int, dict] = {}
    for k in k_values:
        if k > pool_size:
            continue
        n_draws = N_DRAWS_CI_WIDTH_FULL_POOL if k == pool_size else N_DRAWS_CI_WIDTH
        widths = []
        for i in range(n_draws):
            sample = rng.choice(all_secrets, size=k, replace=False).tolist()
            widths.append(_ci_width_for_subsample(by_secret, sample, seed=SEED + i))
        arr = np.array(widths)
        out[k] = {
            "median_width": float(np.median(arr)),
            "iqr_low": float(np.percentile(arr, 25)),
            "iqr_high": float(np.percentile(arr, 75)),
            "n_draws": n_draws,
            "note": (
                "k == pool size: the secret SET is deterministic (only one 42-choose-42 "
                "combination exists), so this spread reflects bootstrap-RNG noise only, "
                "not secret-selection noise -- unlike k < pool size."
                if k == pool_size
                else None
            ),
        }
    return out


# ---------------------------------------------------------------------------
# Step 2a: MDE using the REAL observed L2+L5 effect (k <= 34 only).
# ---------------------------------------------------------------------------


def mde_real_effect_curve(
    shipped_34: list[dict], hybrid_34: list[dict], k_values: tuple[int, ...] = K_VALUES
) -> dict:
    """Detection-rate-vs-k using the ACTUAL observed L2+L5 per-secret effect
    (reconstruct_real_l2_l5_effect's output), restricted to k <= 34 (real
    per-secret effect data only exists for the 34 public-benchmark secrets).
    """
    base_by_secret = _dim1_by_secret(shipped_34)
    cand_by_secret = _dim1_by_secret(hybrid_34)
    secrets = sorted(set(base_by_secret) & set(cand_by_secret))
    pool_size = len(secrets)
    rng = np.random.default_rng(SEED + 1000)
    out: dict[int, dict] = {}
    for k in k_values:
        if k > pool_size:
            continue
        n_draws = N_DRAWS_CI_WIDTH_FULL_POOL if k == pool_size else N_SIMS_MDE
        detections = 0
        for i in range(n_draws):
            sample = rng.choice(secrets, size=k, replace=False).tolist()
            b = [r for s in sample for r in base_by_secret[s]]
            c = [r for s in sample for r in cand_by_secret[s]]
            delta = paired_bootstrap_dim1_delta(b, c, n_boot=INNER_N_BOOT, seed=SEED + i)
            if delta["ci_significant_improvement"]:
                detections += 1
        out[k] = {"detection_rate": detections / n_draws, "n_sims": n_draws}
    return out


# ---------------------------------------------------------------------------
# Step 2b: MDE using a calibrated synthetic injection (full k range).
# ---------------------------------------------------------------------------


def inject_synthetic_effect(
    records: list[dict],
    secrets: list[str],
    vocab_size: int,
    intensity: float,
    rng: np.random.Generator,
) -> list[dict]:
    """Return a copy of `records` (restricted to `secrets`) with a synthetic
    rank-improving effect applied to a random AFFECTED_SECRET_FRAC fraction
    of `secrets` -- mirroring how a real targeted fix (like the L2 patch)
    only touches SOME secrets, not all. For near/mid-tier records of an
    affected secret, actual_rank is decreased (moved toward rank 1, i.e.
    "more related") by intensity * vocab_size; for far-tier records it is
    increased (pushed toward the bottom) by the same amount. Both are
    clipped to [1, vocab_size]. This raises the pooled Spearman correlation
    between tier-ordinal and actual_rank in the same DIRECTION a genuine
    ranking improvement would.
    """
    n_affected = max(1, round(AFFECTED_SECRET_FRAC * len(secrets)))
    affected = set(rng.choice(secrets, size=n_affected, replace=False).tolist())
    shift = intensity * vocab_size
    by_secret = records_by_secret(records)
    out: list[dict] = []
    for s in secrets:
        for r in by_secret[s]:
            rec = dict(r)
            if s in affected and rec["actual_rank"] is not None:
                if rec["tier"] in ("near", "mid"):
                    rec["actual_rank"] = int(np.clip(rec["actual_rank"] - shift, 1, vocab_size))
                else:  # far
                    rec["actual_rank"] = int(np.clip(rec["actual_rank"] + shift, 1, vocab_size))
            out.append(rec)
    return out


def records_by_secret(records: list[dict]) -> dict[str, list[dict]]:
    """Thin wrapper so inject_synthetic_effect reads like the rest of this
    module without re-deriving the by-secret grouping inline each call."""
    return _dim1_by_secret(records)


def _point_delta_for_injection(
    records: list[dict],
    secrets: list[str],
    vocab_size: int,
    intensity: float,
    rng: np.random.Generator,
) -> float:
    """Cheap (no bootstrap) point-estimate delta for calibration -- avoids
    paying the full bootstrap cost thousands of times during grid search."""
    by_secret = _dim1_by_secret(records)
    baseline = [r for s in secrets for r in by_secret[s]]
    candidate = inject_synthetic_effect(records, secrets, vocab_size, intensity, rng)
    base_by_secret = _dim1_by_secret(baseline)
    cand_by_secret = _dim1_by_secret(candidate)
    b = _dim1_spearman_for_secrets(base_by_secret, secrets)
    c = _dim1_spearman_for_secrets(cand_by_secret, secrets)
    return c - b


def calibrate_intensities(
    records: list[dict], vocab_size: int, effect_sizes: tuple[float, ...] = EFFECT_SIZES
) -> dict:
    """Grid-search a single `intensity` value per target effect size so that,
    at k=CALIBRATION_K (matching the real observed effect's n_clusters=34),
    the synthetic injection's mean point-estimate delta is CLOSEST to that
    target. Approximate ("roughly reproduce" per spec), not an exact solve.
    """
    by_secret = _dim1_by_secret(records)
    all_secrets = sorted(by_secret)
    rng = np.random.default_rng(SEED + 2000)
    grid_means: dict[float, float] = {}
    for intensity in CALIBRATION_INTENSITY_GRID:
        deltas = []
        for _ in range(CALIBRATION_TRIALS):
            sample = rng.choice(all_secrets, size=CALIBRATION_K, replace=False).tolist()
            deltas.append(_point_delta_for_injection(records, sample, vocab_size, intensity, rng))
        grid_means[intensity] = float(np.mean(deltas))
    calibrated: dict[float, dict] = {}
    for target in effect_sizes:
        best_intensity = min(CALIBRATION_INTENSITY_GRID, key=lambda i: abs(grid_means[i] - target))
        calibrated[target] = {
            "intensity": best_intensity,
            "calibration_mean_delta_at_k34": grid_means[best_intensity],
        }
    return {"grid": grid_means, "calibrated": calibrated}


def mde_synthetic_curve(
    records: list[dict],
    vocab_size: int,
    calibrated: dict[float, dict],
    k_values: tuple[int, ...] = K_VALUES,
) -> dict:
    """Detection-rate-vs-k for each calibrated effect size, using the
    synthetic injection, across the FULL k range (unlike the real-effect
    curve, which is capped at k=34)."""
    by_secret = _dim1_by_secret(records)
    all_secrets = sorted(by_secret)
    pool_size = len(all_secrets)
    out: dict[float, dict] = {}
    for effect_size, cal in calibrated.items():
        intensity = cal["intensity"]
        rng = np.random.default_rng(SEED + 3000 + int(effect_size * 1000))
        per_k: dict[int, dict] = {}
        for k in k_values:
            if k > pool_size:
                continue
            n_draws = N_DRAWS_CI_WIDTH_FULL_POOL if k == pool_size else N_SIMS_MDE
            detections = 0
            for i in range(n_draws):
                sample = rng.choice(all_secrets, size=k, replace=False).tolist()
                baseline = [r for s in sample for r in by_secret[s]]
                candidate = inject_synthetic_effect(records, sample, vocab_size, intensity, rng)
                delta = paired_bootstrap_dim1_delta(
                    baseline, candidate, n_boot=INNER_N_BOOT, seed=SEED + i
                )
                if delta["ci_significant_improvement"]:
                    detections += 1
            per_k[k] = {"detection_rate": detections / n_draws, "n_sims": n_draws}
        out[effect_size] = per_k
    return out


# ---------------------------------------------------------------------------
# Step 3: 1/sqrt(n) extrapolation.
# ---------------------------------------------------------------------------


def fit_inverse_sqrt_n(
    ci_width_curve: dict, extrapolate_n: tuple[int, ...] = EXTRAPOLATE_N
) -> dict:
    """Fit width(n) = C / sqrt(n) to the empirical median-width points (least
    squares on C using width_i * sqrt(n_i) averaged across measured k), then
    extrapolate to `extrapolate_n`. Also reports fit residuals at the
    MEASURED k values, so fit quality is visible, not asserted."""
    ks = sorted(ci_width_curve)
    widths = np.array([ci_width_curve[k]["median_width"] for k in ks])
    ns = np.array(ks, dtype=float)
    c_estimates = widths * np.sqrt(ns)
    c_fit = float(np.mean(c_estimates))
    predicted_at_measured = {int(k): float(c_fit / np.sqrt(k)) for k in ks}
    residuals = {
        int(k): float(ci_width_curve[k]["median_width"] - predicted_at_measured[k]) for k in ks
    }
    extrapolated = {int(n): float(c_fit / np.sqrt(n)) for n in extrapolate_n}
    return {
        "c_fit": c_fit,
        "c_estimates_per_k": {int(k): float(v) for k, v in zip(ks, c_estimates, strict=True)},
        "predicted_width_at_measured_k": predicted_at_measured,
        "residuals_at_measured_k": residuals,
        "extrapolated_width": extrapolated,
        "note": (
            "EXTRAPOLATION (parametric 1/sqrt(n) assumption) -- distinct from the "
            "measured, not-assumed results at n<=42 above."
        ),
    }


# ---------------------------------------------------------------------------
# Step 4: conclusion.
# ---------------------------------------------------------------------------


def _smallest_k_crossing_target(
    per_k: dict[int, dict], target: float = DETECTION_TARGET
) -> int | None:
    for k in sorted(per_k):
        if per_k[k]["detection_rate"] >= target:
            return k
    return None


def ci_width_crossing_n(c_fit: float, target_effect_size: float) -> float:
    """Rough cross-check, DERIVED FROM THE EXTRAPOLATION FIT (not a formal
    power calculation): assuming (a) the point-estimate delta stays at
    ~`target_effect_size` as n grows and (b) the bootstrap CI stays
    APPROXIMATELY symmetric around the point estimate (both are
    simplifications -- the real CI in probe_l2_patch_l5_combined.eval_
    result.json is mildly asymmetric), the CI's lower bound crosses zero
    once width/2 < target_effect_size, i.e. width < 2*target_effect_size.
    Given width(n) = c_fit / sqrt(n), solving for n:
        n > (c_fit / (2 * target_effect_size)) ** 2
    Returned as a float (not rounded) so callers can decide how to present
    it; explicitly an EXTRAPOLATION-derived heuristic, not a direct
    simulation result.
    """
    return (c_fit / (2.0 * target_effect_size)) ** 2


def build_conclusion(mde_synthetic: dict, mde_real: dict, extrapolation: dict) -> dict:
    """
    IMPORTANT, measured (not assumed) finding this function must not paper
    over: the calibrated-synthetic MDE curve (Step 2b) and the REAL-effect
    MDE curve (Step 2a) DISAGREE SHARPLY at the one k value where they
    overlap in spirit (k=34, the full real-effect pool) -- the synthetic
    curve claims ~100% detection power for a ~0.06 effect at k=34, while
    the REAL observed L2+L5 effect, evaluated on the SAME 34 secrets,
    detects at only ~27-32%. This is not noise-explainable by a few percent;
    it means the synthetic injection (a smooth, uniform rank shift applied
    to a fixed 40% of secrets every draw) is a systematically CLEANER,
    lower-variance signal than the real world's per-secret-heterogeneous
    effect (a targeted fix that only truly helps 4 hand-picked collision
    words, with everything else picking up incidental, noisy knock-on
    movement). Consequence: the synthetic curve's "k=20 is already enough"
    claim is almost certainly OPTIMISTIC and should not be treated as an
    actionable target on its own -- it is reported below as a LOWER BOUND
    (best case, if a future fix's effect were unrealistically uniform), not
    a point recommendation. A second, independent cross-check
    (ci_width_crossing_n, derived from the Step 3 extrapolation fit) is
    used instead to anchor the plain-language recommendation, since it does
    not depend on any assumption about how the effect is distributed across
    secrets.
    """
    six_pct = min(EFFECT_SIZES, key=lambda e: abs(e - 0.06))
    curve_006 = mde_synthetic[six_pct]
    smallest_k_synthetic = _smallest_k_crossing_target(curve_006)
    k34_synthetic_rate = curve_006.get(34, {}).get("detection_rate")
    k34_real_rate = mde_real.get(34, {}).get("detection_rate")
    real_rates = [mde_real[k]["detection_rate"] for k in sorted(mde_real)]
    max_real_rate = max(real_rates) if real_rates else None

    n_ci_width_crossing = ci_width_crossing_n(extrapolation["c_fit"], six_pct)

    plain_language = (
        f"The two MDE curves disagree sharply at k=34: the calibrated-synthetic curve claims "
        f"{_fmt_pct(k34_synthetic_rate)} detection power there, but the REAL observed L2+L5 "
        f"effect (same 34 secrets) only detects {_fmt_pct(k34_real_rate)} of the time -- "
        "the synthetic injection's uniform per-secret shift is a much cleaner signal than "
        "real per-secret heterogeneity, so the synthetic curve's 'k=20 is already enough' claim "
        "is treated here as an OPTIMISTIC LOWER BOUND, not an actionable target. The REAL curve "
        f"itself never exceeds {_fmt_pct(max_real_rate)} detection across all tested k<=34 "
        "(no clear rising trend within the tested range, given real per-secret noise + limited "
        "sims), so it cannot pin down a 'crosses 80%' k either. The most defensible number here "
        "comes from a THIRD, independent cross-check: extrapolating the Step 3 1/sqrt(n) CI-"
        "width fit to find the n at which a ~0.06 point estimate's own CI width would plausibly "
        f"clear zero (assuming the point estimate holds and the CI stays roughly symmetric) "
        f"gives n~{n_ci_width_crossing:.0f} -- i.e. roughly "
        f"{max(0, round(n_ci_width_crossing - 34))} MORE secrets beyond the current 34, an "
        "EXTRAPOLATION-derived estimate distinct from either measured MDE curve above."
    )

    return {
        "target_effect_size": six_pct,
        "smallest_k_reaching_80pct_power_synthetic_curve": smallest_k_synthetic,
        "detection_rate_at_k34_synthetic": k34_synthetic_rate,
        "detection_rate_at_k34_real_effect": k34_real_rate,
        "max_detection_rate_real_effect_any_tested_k": max_real_rate,
        "ci_width_extrapolation_crossing_n": n_ci_width_crossing,
        "recommended_additional_secrets_via_ci_width_extrapolation": max(
            0, round(n_ci_width_crossing - 34)
        ),
        "plain_language": plain_language,
        "synthetic_curve_caveat": (
            "The calibrated-synthetic curve is a documented computational-budget fallback (see "
            "module docstring) and, per the discrepancy above, should be read as an optimistic "
            "lower bound on secrets needed, NOT a reliable point estimate."
        ),
        "caveat": (
            "This is a measurement/recommendation for GG to weigh against the mechanical cost of "
            "authoring new benchmark secrets (domain tuple + 4 hand-picked EN words + no-leakage "
            "grep + two scrub-script passes + GG review of any new advisory rank-10 hits per "
            "secret) -- NOT something acted on in this task. No new benchmark secrets were "
            "authored here."
        ),
    }


# ---------------------------------------------------------------------------
# Report rendering.
# ---------------------------------------------------------------------------


def _fmt_pct(x: float | None) -> str:
    return f"{x:.0%}" if x is not None else "n/a"


def render_markdown(result: dict) -> str:
    lines = [
        "# Statistical power analysis -- spec-model-excellence.md WORKSTREAM D item 12",
        "",
        "Measurement only. No new benchmark secrets were authored as part of this report.",
        "",
        "## Step 1 -- empirical CI-width-vs-n (measured, pool (c), 42 secrets, n<=42)",
        "",
        "| k | median CI width | IQR | n draws |",
        "|---|---|---|---|",
    ]
    for k in sorted(result["ci_width_curve"], key=int):
        row = result["ci_width_curve"][k]
        lines.append(
            f"| {k} | {row['median_width']:.4f} | "
            f"[{row['iqr_low']:.4f}, {row['iqr_high']:.4f}] | {row['n_draws']} |"
        )
    lines += [
        "",
        "## Step 2a -- MDE using the REAL observed L2+L5 effect (measured, k<=34 only)",
        "",
        "| k | detection rate (>=80% target) | n sims |",
        "|---|---|---|",
    ]
    for k in sorted(result["mde_real_effect_curve"], key=int):
        row = result["mde_real_effect_curve"][k]
        lines.append(f"| {k} | {_fmt_pct(row['detection_rate'])} | {row['n_sims']} |")

    lines += [
        "",
        "## Step 2b -- MDE using calibrated-synthetic injection (measured, full k range)",
        "",
        "Calibration (intensity per target effect size, at k=34):",
        "",
        "| target effect size | calibrated intensity | calibration mean delta @k=34 |",
        "|---|---|---|",
    ]
    for target, cal in sorted(result["calibration"]["calibrated"].items()):
        lines.append(
            f"| {target} | {cal['intensity']} | {cal['calibration_mean_delta_at_k34']:.4f} |"
        )
    header_cells = " | ".join(f"detect@{e}" for e in sorted(result["mde_synthetic_curve"]))
    lines += ["", f"| k | {header_cells} |"]
    lines.append("|---|" + "---|" * len(result["mde_synthetic_curve"]))
    all_ks = sorted({k for curve in result["mde_synthetic_curve"].values() for k in curve}, key=int)
    for k in all_ks:
        cells = []
        for e in sorted(result["mde_synthetic_curve"]):
            row = result["mde_synthetic_curve"][e].get(k)
            cells.append(_fmt_pct(row["detection_rate"]) if row else "n/a")
        lines.append(f"| {k} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "## Step 3 -- 1/sqrt(n) extrapolation beyond n=42 (EXTRAPOLATION, not measured)",
        "",
        f"Fitted C = {result['extrapolation']['c_fit']:.4f} (width(n) = C / sqrt(n))",
        "",
        "| n | extrapolated CI width |",
        "|---|---|",
    ]
    for n, w in sorted(result["extrapolation"]["extrapolated_width"].items()):
        lines.append(f"| {n} | {w:.4f} |")

    concl = result["conclusion"]
    lines += [
        "",
        "## Step 4 -- conclusion",
        "",
        f"- Target effect size analysed: ~{concl['target_effect_size']}",
        f"- Detection rate at k=34, calibrated-synthetic curve: "
        f"{_fmt_pct(concl['detection_rate_at_k34_synthetic'])}",
        f"- Detection rate at k=34, REAL observed effect: "
        f"{_fmt_pct(concl['detection_rate_at_k34_real_effect'])}",
        f"- Max detection rate, REAL observed effect, any tested k<=34: "
        f"{_fmt_pct(concl['max_detection_rate_real_effect_any_tested_k'])}",
        f"- Smallest k reaching {DETECTION_TARGET:.0%} power (synthetic curve, OPTIMISTIC "
        f"lower bound -- see caveat): {concl['smallest_k_reaching_80pct_power_synthetic_curve']}",
        "- CI-width-extrapolation crossing n (independent 3rd cross-check): "
        f"{concl['ci_width_extrapolation_crossing_n']:.1f} "
        f"(~{concl['recommended_additional_secrets_via_ci_width_extrapolation']} more secrets "
        "beyond 34)",
        "",
        f"**{concl['plain_language']}**",
        "",
        concl["synthetic_curve_caveat"],
        "",
        concl["caveat"],
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    vocab_size = len(load_hien_vocab())
    combined_records = load_combined_dim1_records()

    print("[1/4] empirical CI-width-vs-n curve ...")
    ci_width_curve = empirical_ci_width_curve(combined_records)

    print("[2a/4] reconstructing real L2+L5 hybrid effect ...")
    shipped_34, hybrid_34 = reconstruct_real_l2_l5_effect()
    mde_real = mde_real_effect_curve(shipped_34, hybrid_34)

    print("[2b/4] calibrating synthetic injection ...")
    calibration = calibrate_intensities(combined_records, vocab_size)
    print("[2b/4] running calibrated-synthetic MDE curve ...")
    mde_synthetic = mde_synthetic_curve(combined_records, vocab_size, calibration["calibrated"])

    print("[3/4] fitting 1/sqrt(n) extrapolation ...")
    extrapolation = fit_inverse_sqrt_n(ci_width_curve)

    print("[4/4] building conclusion ...")
    conclusion = build_conclusion(mde_synthetic, mde_real, extrapolation)

    result = {
        "pools": {
            "a_production_25_secrets": "evals/scenarios/dim1_hien.json",
            "b_public_benchmark_34_secrets": (
                "evals/finetune/data/public_benchmark_staging/dim1_hien.json"
            ),
            "c_internal_combined_42_secrets": (
                "evals/finetune/data/bakeoff_raw/gauravgandhi2411__hinglish-relatedness-sbert.json"
                " (dim1_records)"
            ),
        },
        "ci_width_curve": {str(k): v for k, v in ci_width_curve.items()},
        "mde_real_effect_curve": {str(k): v for k, v in mde_real.items()},
        "calibration": calibration,
        "mde_synthetic_curve": {
            e: {str(k): v for k, v in curve.items()} for e, curve in mde_synthetic.items()
        },
        "extrapolation": extrapolation,
        "conclusion": conclusion,
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md = render_markdown(
        {
            "ci_width_curve": ci_width_curve,
            "mde_real_effect_curve": mde_real,
            "calibration": calibration,
            "mde_synthetic_curve": mde_synthetic,
            "extrapolation": extrapolation,
            "conclusion": conclusion,
        }
    )
    OUT_MD.write_text(md, encoding="utf-8")
    print(f"wrote {OUT_JSON} and {OUT_MD}")


if __name__ == "__main__":
    main()
