from __future__ import annotations

"""
Deterministic, seeded rival-path solver for Mindmeld Phase 4.

The rival simulates a plausible human-ish convergence toward rank 1.
Seed: sha1(secret + date + 'rival') — one seed per puzzle.
Three tiers produce distinct paths. Paths expose only rank + band integers,
never word strings — ensuring spoiler-safety.
"""

import hashlib
import random


def _rival_seed(secret: str, puzzle_date_iso: str) -> bytes:
    """Return 20 raw bytes: sha1(secret + date + 'rival')."""
    raw = f"{secret.lower()}{puzzle_date_iso}rival"
    return hashlib.sha1(raw.encode()).digest()  # noqa: S324


def scorching_cutoff(n: int) -> int:
    """The tightest 'near' threshold: rank <= max(50, n * 0.001) is 'scorching'."""
    return max(50, int(n * 0.001))


def band_for_rank(rank: int, n: int) -> int:
    """
    Python mirror of Dart's bandForRank().

    Returns TemperatureBand ordinal: 0=win, 1=scorching, 2=hot, 3=warm, 4=cold, 5=freezing.

    Thresholds (match AppConfig constants in config.dart):
      win:       rank == 1
      scorching: rank <= max(50, n * 0.001)
      hot:       rank <= max(500, n * 0.01)
      warm:      rank <= max(1050, n * 0.05)
      cold:      rank <= n * 0.25
      freezing:  else

    warm's 1050-rank floor (added alongside scorching's/hot's existing floors,
    same max(floor, fraction) shape) fixes a band-calibration bug: for small
    vocabs (e.g. hi-en, n~10,495) hot's 500-rank floor already consumes most
    of the un-floored n*0.05=525 warm ceiling, squeezing Warm down to a
    24-rank sliver (0.23% of vocab) versus EN's healthy 2,200-rank/4.0% Warm
    band at n=55,000. A floor of 900 (original fix, commit 894f63e) left EN's
    own thresholds byte-for-byte unchanged (55,000 * 0.05 = 2,750 >> 900, so
    the floor never binds there) while giving hi-en a ~400-rank/3.8% Warm
    band. The floor was later widened 900 -> 1050 after a threshold-boundary
    grid search (evals/finetune/optimize_band_thresholds.py) against the
    shipped model's bake-off checkpoint found this the only candidate that
    clears a strict zero-regression gate: +4 fixed / 0 broken, Near/Far
    confusion-matrix rows byte-identical before/after, Warm recall 8.3% ->
    13.1% (directionally real, not CI-significant at n=84 mid-tier records).
    EN remains untouched by the same margin (2,750 >> 1050). See
    docs/known-limitations.md #18,
    evals/finetune/data/calibration_threshold_report.md, and PLAN.md for the
    full before/after calibration data.
    """
    if rank == 1:
        return 0
    if rank <= scorching_cutoff(n):
        return 1
    hot_max = max(500, int(n * 0.01))
    if rank <= hot_max:
        return 2
    warm_max = max(1050, int(n * 0.05))
    if rank <= warm_max:
        return 3
    cold_max = int(n * 0.25)
    if rank <= cold_max:
        return 4
    return 5


# Per-tier: (start_pct, lateral_prob, early_factor, late_factor)
# start_pct    — initial rank as fraction of vocab size n
# lateral_prob — probability of a regression (backslide) step
# early_factor — fractional rank reduction per step when rank > warm_threshold (cold/freezing)
# late_factor  — fractional rank reduction per step when rank <= hot_threshold (hot/scorching)
#
# Calibration target (median over 30-day window, both en and hi-en):
#   even:  par ∈ [4, 16], median 8–12
#   chill: chill.solveAt - par ∈ [2, 8]
#   sharp: par - sharp.solveAt ∈ [1, 5]
#
# Adaptive jump model: large reductions when cold (orienting sweep) and finer
# adjustments when hot/scorching (precision tuning near the secret). This mirrors
# how a competent human actually plays, yielding much lower par than the old fixed
# jump_mean=0.43 which required ~17 geometric steps from rank 22000 to rank 1.
_TIER_PARAMS: dict[str, tuple[float, float, float, float]] = {
    # (start_pct, lateral_prob, early_factor, late_factor)
    #
    # lateral_prob=0 for all tiers: the gate test requires every puzzle across
    # the 30-day window to satisfy chill_spread ∈ [2,8] and sharp_spread ∈ [1,5].
    # With any non-zero lateral_prob, a single unlucky RNG draw (2+ regressions on
    # even tier) can violate the sharp_spread upper bound deterministically. The
    # Gaussian noise on early/late factors already provides enough path variety.
    "sharp": (0.20, 0.00, 0.90, 0.84),
    "even": (0.40, 0.00, 0.85, 0.62),
    "chill": (0.60, 0.00, 0.75, 0.42),
}

# Independent per-tier seed offsets so tiers don't share correlated RNG state.
_TIER_OFFSETS: dict[str, int] = {
    "even": 0x0000_0000,
    "chill": 0xCAFE_BABE,
    "sharp": 0xDEAD_BEEF,
}

_MAX_PATH_STEPS = 40


def _generate_path(n: int, rng: random.Random, tier: str) -> list[dict]:
    """Generate a single rival path for one tier from a seeded RNG.

    Uses an adaptive jump model: large fractional reductions when far from the
    secret (cold/freezing) and progressively finer adjustments as rank improves
    (warm → hot → scorching). This mirrors how a competent human actually plays:
    orient fast with big sweeps, then zero in with precision near the secret.
    """
    start_pct, lateral_prob, early_factor, late_factor = _TIER_PARAMS[tier]

    noise_range = max(1, n // 20)
    noise = rng.randint(-noise_range, noise_range)
    start_rank = max(2, min(n - 1, int(n * start_pct) + noise))

    path: list[dict] = [{"rank": start_rank, "band": band_for_rank(start_rank, n)}]
    best_rank = start_rank

    # Band boundary ranks for adaptive convergence (mirror band_for_rank thresholds
    # -- warm_threshold must carry the same 1050-rank floor as band_for_rank's
    # warm_max, or this path's cold/warm transition would drift out of sync with
    # the band the player actually sees at that rank).
    hot_threshold = max(500, int(n * 0.01))
    warm_threshold = max(1050, int(n * 0.05))

    for _ in range(_MAX_PATH_STEPS - 1):
        if best_rank == 1:
            break

        if rng.random() < lateral_prob:
            # Regression step: slight backslide to simulate human dead ends.
            regression = rng.randint(1, max(2, best_rank // 6))
            next_rank = min(n - 1, best_rank + regression)
        else:
            # Adaptive reduction: scale aggressiveness by current distance from secret.
            if best_rank > warm_threshold:
                # Cold / freezing — big orienting sweeps.
                base = early_factor
                noise_std = 0.06
                lo, hi = 0.10, 0.97
            elif best_rank > hot_threshold:
                # Warm — transition zone.
                base = (early_factor + late_factor) / 2.0
                noise_std = 0.05
                lo, hi = 0.10, 0.97
            else:
                # Hot / scorching — precise fine-tuning near the secret.
                # Tight noise band keeps tiers well-separated so spread gates hold.
                base = late_factor
                noise_std = 0.03
                lo, hi = late_factor - 0.05, late_factor + 0.05

            reduction = max(lo, min(hi, base + rng.gauss(0.0, noise_std)))
            next_rank = max(1, int(best_rank * (1.0 - reduction)))

        path.append({"rank": next_rank, "band": band_for_rank(next_rank, n)})
        if next_rank < best_rank:
            best_rank = next_rank

    if best_rank > 1:
        path.append({"rank": 1, "band": 0})

    return path


def generate_rival_data(n: int, secret: str, puzzle_date_iso: str) -> tuple[dict, int]:
    """
    Generate all three rival paths and compute parGuesses.

    Parameters
    ----------
    n:
        Vocabulary size.
    secret:
        The secret word (lowercase).
    puzzle_date_iso:
        Puzzle date as "yyyy-mm-dd" ISO string.

    Returns
    -------
    (rival_dict, par_guesses) where:
      rival_dict = {
        "even":  {"path": [{rank, band}, ...], "solveAt": int},
        "chill": {"path": [{rank, band}, ...], "solveAt": int},
        "sharp": {"path": [{rank, band}, ...], "solveAt": int},
      }
      par_guesses = len of even tier path (step count to solve)

    Each step in path is {"rank": int, "band": int} — integers only, no words.
    Seed is sha1(secret + date + 'rival'); each tier uses an independent RNG
    derived via XOR with a tier-specific constant.
    """
    seed_bytes = _rival_seed(secret, puzzle_date_iso)
    seed_int = int.from_bytes(seed_bytes[:8], "big")

    rival: dict = {}
    for tier in ("even", "chill", "sharp"):
        tier_seed = seed_int ^ _TIER_OFFSETS[tier]
        rng = random.Random(tier_seed)
        path = _generate_path(n, rng, tier)
        rival[tier] = {"path": path, "solveAt": len(path)}

    par_guesses: int = rival["even"]["solveAt"]
    return rival, par_guesses


# maxGuesses scaling — shared by payload.py (production) and
# evals/harness/dimension5_winrate.py (win-rate simulation), so the two
# implementations can never drift apart.
#
# Calibrated via a grid search over k in [1.0, 1.7] and floor in [6, 14]
# against dimension5's win-rate simulation (220 real puzzles: 60 daily +
# 160 pack, both langs, par clustering in [6, 10] for this content set).
# A fixed `par + 6` offset produced median win-rate 93% (only 10.5% of
# puzzles in the target 75-85% band) — low-par puzzles got a
# disproportionately generous relative budget (par=6 -> 12 guesses is a
# 100% buffer). k=1.5 with floor=12 produces median 82.0% and 63.6% of
# puzzles in-band (vs 10.5% before) — the best trade-off found: it is a
# plateau (k=1.49-1.52 all produce the identical distribution, so this
# is not a knife-edge value), the floor keeps very-low-par puzzles from
# being punished (a par=4 puzzle gets the 12-guess floor rather than a
# tight 6-guess budget), and it leaves only a single puzzle across the
# whole 220-puzzle set below the 40% "unwinnable" outlier threshold (at
# 39% — one point under the cutoff, within simulation noise at
# n=100 sims/puzzle, sigma ~= 5pp). See PLAN.md for the full sweep.
MAX_GUESSES_K = 1.5
MAX_GUESSES_FLOOR = 12


def max_guesses_for_par(par_guesses: int) -> int:
    """Return the player-facing guess budget for a puzzle with `par_guesses`.

    Scales with par (rather than a fixed offset) so low-par puzzles aren't
    handed a disproportionately generous relative budget; floored so very-low
    -par puzzles still get a workable minimum. See module-level comment above
    for calibration details.
    """
    return max(MAX_GUESSES_FLOOR, round(par_guesses * MAX_GUESSES_K))
