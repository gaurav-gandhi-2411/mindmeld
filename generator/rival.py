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


def band_for_rank(rank: int, n: int) -> int:
    """
    Python mirror of Dart's bandForRank().

    Returns TemperatureBand ordinal: 0=win, 1=scorching, 2=hot, 3=warm, 4=cold, 5=freezing.

    Thresholds (match AppConfig constants in config.dart):
      win:       rank == 1
      scorching: rank <= max(50, n * 0.001)
      hot:       rank <= max(500, n * 0.01)
      warm:      rank <= n * 0.05
      cold:      rank <= n * 0.25
      freezing:  else
    """
    if rank == 1:
        return 0
    scorching_max = max(50, int(n * 0.001))
    if rank <= scorching_max:
        return 1
    hot_max = max(500, int(n * 0.01))
    if rank <= hot_max:
        return 2
    warm_max = int(n * 0.05)
    if rank <= warm_max:
        return 3
    cold_max = int(n * 0.25)
    if rank <= cold_max:
        return 4
    return 5


# Per-tier: (start_pct, jump_mean, jump_std, lateral_prob)
# start_pct    — initial rank as fraction of vocab size n
# jump_mean    — mean fractional improvement per forward step
# jump_std     — std deviation of fractional improvement
# lateral_prob — probability of a lateral/slight-regression step (human realism)
#
# Calibration target (evaluated via sanity print in build.py):
#   sharp: ~par-2  (about 2 fewer guesses than even)
#   even:  ~par    (the par baseline)
#   chill: ~par+4  (about 4 more guesses than even)
_TIER_PARAMS: dict[str, tuple[float, float, float, float]] = {
    "sharp": (0.25, 0.52, 0.08, 0.05),
    "even":  (0.40, 0.43, 0.10, 0.12),
    "chill": (0.55, 0.33, 0.09, 0.22),
}

# Independent per-tier seed offsets so tiers don't share correlated RNG state.
_TIER_OFFSETS: dict[str, int] = {
    "even":  0x0000_0000,
    "chill": 0xCAFE_BABE,
    "sharp": 0xDEAD_BEEF,
}

_MAX_PATH_STEPS = 40


def _generate_path(n: int, rng: random.Random, tier: str) -> list[dict]:
    """Generate a single rival path for one tier from a seeded RNG."""
    start_pct, jump_mean, jump_std, lateral_prob = _TIER_PARAMS[tier]

    noise = rng.randint(-max(1, n // 20), max(1, n // 20))
    start_rank = max(2, min(n, int(n * start_pct) + noise))

    path: list[dict] = [{"rank": start_rank, "band": band_for_rank(start_rank, n)}]
    best_rank = start_rank

    for _ in range(_MAX_PATH_STEPS - 1):
        if best_rank == 1:
            break

        if rng.random() < lateral_prob:
            regression = rng.randint(1, max(2, best_rank // 4))
            next_rank = min(n, best_rank + regression)
        else:
            jump = max(0.05, min(0.92, rng.gauss(jump_mean, jump_std)))
            next_rank = max(1, int(best_rank * (1.0 - jump)))

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
