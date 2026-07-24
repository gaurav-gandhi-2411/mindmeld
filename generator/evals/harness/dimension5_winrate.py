from __future__ import annotations

"""
Dimension 5 — difficulty / win-rate modeling.

Simulates a population of "competent player" guessers per puzzle and
estimates win-rate under the REAL maxGuesses (rival.max_guesses_for_par(par),
from rival.py's own par calculation — the same par a live payload ships
with). Unlike rival.generate_rival_data (one smooth, deterministic path per
tier, used to render the in-game rival), this simulates N independent NOISY
trajectories per puzzle — modeling realistic human inconsistency (some
guesses barely improve, occasional lucky jumps) rather than a single
idealized curve — and reports the resulting win-rate distribution.

Purely algorithmic over rank-space (identical abstraction to rival.py: no
embedding calls, no real words) — fast enough to run across every puzzle.

Player model: adaptive reduction (bigger cuts far from the secret, finer
cuts close in — same qualitative shape as rival.py's tiers) plus per-step
Gaussian noise AND a small per-step chance of a stall (reduction near zero,
modeling a wasted/off-target guess) — this is what actually produces
variance in win-rate across simulations, not just cosmetic randomness.

Base reduction factors (0.70/0.60/0.50 cold->hot) were calibrated by a
parameter sweep against the spec's own target ("~75-85% for a competent
player"): at maxGuesses=14 (a representative mid-range budget) they produce
median win-rate ~0.82. Win-rate is HIGHLY sensitive to both these constants
and to maxGuesses itself.

maxGuesses formula (rival.max_guesses_for_par): `max(12, round(par * 1.5))`
— see rival.py's module-level comment for the full calibration story. This
REPLACED an earlier fixed `par + 6` offset, which this very simulation
exposed as miscalibrated: across the 220 puzzles in this eval's own content
set (60 daily + 160 pack, both langs, par clustering in [6, 10]), `par + 6`
produced median win-rate 93% with only 10.5% of puzzles in the target
[0.75, 0.85] band — a FIXED offset above par handed low-par puzzles a
disproportionately generous RELATIVE budget (par=6 -> 12 guesses is a 100%
buffer) versus high-par puzzles with the same +6 buffer. Scaling
multiplicatively with a floor (rather than adding a constant) fixes this:
the floor keeps very-low-par puzzles from being punished with too tight a
budget, while the multiplier keeps the buffer proportional to how hard the
puzzle already is. Re-running this harness after the fix: median win-rate
82.0%, 63.6% of puzzles in-band (see evals/reports for the full run). Treat
per-puzzle win-rate numbers as MODELED estimates sensitive to these
assumptions, not measured ground truth — useful for relative
easy-vs-hard flagging across puzzles, not as an absolute probability.
"""

import hashlib
import random

import numpy as np

from packs import load_pack_secrets, load_packs_meta
from rival import generate_rival_data, max_guesses_for_par
from schedule import load_schedule
from vocab import load_en_vocab, load_hien_vocab

N_SIMULATIONS_PER_PUZZLE = 100
SIM_SEED = 42
STALL_PROB = 0.15  # chance a given guess barely moves the rank (off-target guess)
_MAX_STEPS = 60

_VOCAB_SIZE_CACHE: dict[str, int] = {}


def _vocab_size(lang: str) -> int:
    if lang not in _VOCAB_SIZE_CACHE:
        loader = load_en_vocab if lang == "en" else load_hien_vocab
        _VOCAB_SIZE_CACHE[lang] = len(loader())
    return _VOCAB_SIZE_CACHE[lang]


def _simulate_one(n: int, max_guesses: int, rng: random.Random) -> int | None:
    """Simulate one noisy player trajectory. Returns guesses-to-win, or None
    if not solved within max_guesses (the actual per-puzzle budget, from
    rival.max_guesses_for_par(par) — NOT the unrelated _MAX_STEPS safety cap,
    which only guards against a pathological infinite loop for unreasonably
    large max_guesses values)."""
    # Mirrors rival.py's own _generate_path threshold, which in turn mirrors
    # rival.band_for_rank's real scoring boundary -- the 900-rank warm floor
    # must stay in sync across all three or this simulation's cold/warm
    # transition would no longer correspond to the band the player actually sees.
    warm_threshold = max(900, int(n * 0.05))
    hot_threshold = max(500, int(n * 0.01))

    start_noise = rng.uniform(-0.05, 0.05)
    rank = max(2, min(n - 1, int(n * (0.40 + start_noise))))

    step_cap = min(max_guesses, _MAX_STEPS)
    for step in range(1, step_cap + 1):
        if rank == 1:
            return step - 1

        if rng.random() < STALL_PROB:
            # Off-target guess: rank barely moves (or briefly worsens).
            wobble = rng.randint(-max(1, rank // 50), max(1, rank // 20))
            rank = max(1, min(n - 1, rank + wobble))
            continue

        if rank > warm_threshold:
            base, noise_std = 0.70, 0.15
        elif rank > hot_threshold:
            base, noise_std = 0.60, 0.12
        else:
            base, noise_std = 0.50, 0.10

        reduction = max(0.02, min(0.95, base + rng.gauss(0.0, noise_std)))
        rank = max(1, int(rank * (1.0 - reduction)))

    return step if rank == 1 else None


def simulate_puzzle_winrate(
    n: int, secret: str, key: str, n_sims: int = N_SIMULATIONS_PER_PUZZLE
) -> dict:
    """Run n_sims noisy player simulations against one puzzle; return win-rate stats."""
    _, par = generate_rival_data(n, secret, key)
    max_guesses = max_guesses_for_par(par)

    seed = f"{secret}{key}winrate"

    solve_lengths: list[int] = []
    wins = 0
    for i in range(n_sims):
        # Python's builtin hash() is randomized per-process (PYTHONHASHSEED)
        # unless explicitly fixed — NOT reproducible across runs, so this
        # eval (which must be seeded/reproducible) uses a stable hash
        # instead, same approach as rival.py's own _rival_seed.
        digest = hashlib.sha1(f"{seed}{i}".encode()).digest()  # noqa: S324
        sim_seed = int.from_bytes(digest[:8], "big") ^ SIM_SEED
        sim_rng = random.Random(sim_seed)
        result = _simulate_one(n, max_guesses, sim_rng)
        if result is not None:
            wins += 1
            solve_lengths.append(result)

    return {
        "secret": secret,
        "key": key,
        "par": par,
        "max_guesses": max_guesses,
        "n_sims": n_sims,
        "win_rate": wins / n_sims,
        "median_solve_length": float(np.median(solve_lengths)) if solve_lengths else None,
    }


def _puzzle_keys() -> list[dict]:
    keys: list[dict] = []
    for lang in ("en", "hi-en"):
        secrets = load_schedule(lang)
        for i, secret in enumerate(secrets):
            keys.append(
                {"lang": lang, "secret": secret, "key": f"schedule-day-{i}", "source": "daily"}
            )
    for pack in load_packs_meta():
        if pack.status != "live":
            continue
        for lang in pack.langs:
            secrets = load_pack_secrets(pack, lang)
            for i, secret in enumerate(secrets, start=1):
                keys.append(
                    {
                        "lang": lang,
                        "secret": secret,
                        "key": f"{pack.id}-{i:03d}",
                        "source": f"pack:{pack.id}",
                    }
                )
    return keys


def run_dimension5() -> dict:
    puzzles = _puzzle_keys()
    records: list[dict] = []
    for p in puzzles:
        n = _vocab_size(p["lang"])
        result = simulate_puzzle_winrate(n, p["secret"], p["key"])
        records.append({**p, **result})

    win_rates = [r["win_rate"] for r in records]
    TARGET_LOW, TARGET_HIGH = 0.75, 0.85

    outliers_easy = [r for r in records if r["win_rate"] > 0.97]
    outliers_hard = [r for r in records if r["win_rate"] < 0.40]

    per_lang = {}
    for lang in ("en", "hi-en"):
        group = [r["win_rate"] for r in records if r["lang"] == lang]
        per_lang[lang] = {
            "n": len(group),
            "median_win_rate": float(np.median(group)) if group else None,
            "mean_win_rate": float(np.mean(group)) if group else None,
        }

    return {
        "n_puzzles": len(records),
        "median_win_rate": float(np.median(win_rates)),
        "mean_win_rate": float(np.mean(win_rates)),
        "win_rate_in_target_band": sum(1 for w in win_rates if TARGET_LOW <= w <= TARGET_HIGH)
        / len(win_rates),
        "per_lang": per_lang,
        "n_outliers_too_easy": len(outliers_easy),
        "n_outliers_too_hard": len(outliers_hard),
        "outliers_too_easy": sorted(
            [
                {"lang": r["lang"], "source": r["source"], "secret": r["secret"],
                 "win_rate": r["win_rate"]}
                for r in outliers_easy
            ],
            key=lambda r: -r["win_rate"],
        )[:15],
        "outliers_too_hard": sorted(
            [
                {"lang": r["lang"], "source": r["source"], "secret": r["secret"],
                 "win_rate": r["win_rate"]}
                for r in outliers_hard
            ],
            key=lambda r: r["win_rate"],
        )[:15],
    }


if __name__ == "__main__":
    result = run_dimension5()
    print("=== dimension 5 — difficulty / win-rate modeling ===")
    print(f"  n_puzzles: {result['n_puzzles']}")
    print(f"  median_win_rate: {result['median_win_rate']:.3f}")
    print(f"  mean_win_rate: {result['mean_win_rate']:.3f}")
    print(f"  win_rate_in_target_band[0.75,0.85]: {result['win_rate_in_target_band']:.3f}")
    print(f"  per_lang: {result['per_lang']}")
    print(f"  outliers too easy (>0.97): {result['n_outliers_too_easy']}")
    for o in result["outliers_too_easy"][:10]:
        print(f"    {o}")
    print(f"  outliers too hard (<0.40): {result['n_outliers_too_hard']}")
    for o in result["outliers_too_hard"][:10]:
        print(f"    {o}")
