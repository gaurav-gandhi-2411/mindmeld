from __future__ import annotations

"""
Dimension 4 — rival calibration.

Runs the REAL production rival generator (rival.generate_rival_data — the
exact same deterministic, seeded solver used to build live payloads) across
every daily secret (both languages, full schedule) and every live pack
puzzle, and checks each puzzle's three tiers against the calibration targets
already documented in rival.py's own comments:

  even:  par in [4, 16], median 8-12
  chill: chill.solveAt - par in [2, 8]
  sharp: par - sharp.solveAt in [1, 5]

Flags puzzles outside these bounds as "trivially easy" (par too low / sharp
too close to par) or "unwinnable-feeling" (par too high / chill spread too
wide) for content review — this doesn't touch clue/secret content, it only
measures the rival's own path-generation behavior on real puzzle keys.
"""

import numpy as np

from packs import load_pack_secrets, load_packs_meta
from rival import generate_rival_data
from schedule import load_schedule
from vocab import load_en_vocab, load_hien_vocab

PAR_MIN, PAR_MAX = 4, 16
PAR_MEDIAN_TARGET = (8, 12)
CHILL_SPREAD_MIN, CHILL_SPREAD_MAX = 2, 8
SHARP_SPREAD_MIN, SHARP_SPREAD_MAX = 1, 5

_VOCAB_SIZE = {"en": None, "hi-en": None}  # lazily filled


def _vocab_size(lang: str) -> int:
    if _VOCAB_SIZE[lang] is None:
        loader = load_en_vocab if lang == "en" else load_hien_vocab
        _VOCAB_SIZE[lang] = len(loader())
    return _VOCAB_SIZE[lang]


def _puzzle_keys() -> list[dict]:
    """Every (lang, secret, key, source) the production rival generator runs
    against in real builds — the full daily schedule + every live pack puzzle."""
    keys: list[dict] = []
    for lang in ("en", "hi-en"):
        secrets = load_schedule(lang)
        for i, secret in enumerate(secrets):
            keys.append(
                {
                    "lang": lang,
                    "secret": secret,
                    "key": f"schedule-day-{i}",  # opaque key; date value doesn't matter to rival
                    "source": "daily",
                }
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


def run_dimension4() -> dict:
    puzzles = _puzzle_keys()
    records: list[dict] = []
    for p in puzzles:
        n = _vocab_size(p["lang"])
        rival_data, par = generate_rival_data(n, p["secret"], p["key"])
        even_solve = rival_data["even"]["solveAt"]
        chill_solve = rival_data["chill"]["solveAt"]
        sharp_solve = rival_data["sharp"]["solveAt"]
        chill_spread = chill_solve - par
        sharp_spread = par - sharp_solve

        flags = []
        if not (PAR_MIN <= par <= PAR_MAX):
            flags.append(f"par {par} outside [{PAR_MIN},{PAR_MAX}]")
        if not (CHILL_SPREAD_MIN <= chill_spread <= CHILL_SPREAD_MAX):
            flags.append(
                f"chill_spread {chill_spread} outside [{CHILL_SPREAD_MIN},{CHILL_SPREAD_MAX}]"
            )
        if not (SHARP_SPREAD_MIN <= sharp_spread <= SHARP_SPREAD_MAX):
            flags.append(
                f"sharp_spread {sharp_spread} outside [{SHARP_SPREAD_MIN},{SHARP_SPREAD_MAX}]"
            )

        records.append(
            {
                **p,
                "par": par,
                "even_solve": even_solve,
                "chill_solve": chill_solve,
                "sharp_solve": sharp_solve,
                "chill_spread": chill_spread,
                "sharp_spread": sharp_spread,
                "flags": flags,
            }
        )

    pars = [r["par"] for r in records]
    chill_spreads = [r["chill_spread"] for r in records]
    sharp_spreads = [r["sharp_spread"] for r in records]
    flagged = [r for r in records if r["flags"]]

    def _by_lang_source(lang: str, source_prefix: str | None = None) -> list[dict]:
        subset = [r for r in records if r["lang"] == lang]
        if source_prefix:
            subset = [r for r in subset if r["source"].startswith(source_prefix)]
        return subset

    per_group = {}
    for lang in ("en", "hi-en"):
        group = _by_lang_source(lang)
        group_pars = [r["par"] for r in group]
        per_group[lang] = {
            "n": len(group),
            "median_par": float(np.median(group_pars)) if group_pars else None,
            "mean_par": float(np.mean(group_pars)) if group_pars else None,
            "n_flagged": sum(1 for r in group if r["flags"]),
        }

    return {
        "n_puzzles": len(records),
        "median_par": float(np.median(pars)),
        "mean_par": float(np.mean(pars)),
        "par_within_target_range": sum(1 for p in pars if PAR_MIN <= p <= PAR_MAX) / len(pars),
        "median_within_target": (
            PAR_MEDIAN_TARGET[0] <= float(np.median(pars)) <= PAR_MEDIAN_TARGET[1]
        ),
        "median_chill_spread": float(np.median(chill_spreads)),
        "chill_spread_within_target": sum(
            1 for c in chill_spreads if CHILL_SPREAD_MIN <= c <= CHILL_SPREAD_MAX
        )
        / len(chill_spreads),
        "median_sharp_spread": float(np.median(sharp_spreads)),
        "sharp_spread_within_target": sum(
            1 for s in sharp_spreads if SHARP_SPREAD_MIN <= s <= SHARP_SPREAD_MAX
        )
        / len(sharp_spreads),
        "per_lang": per_group,
        "n_flagged": len(flagged),
        "flagged_puzzles": [
            {
                "lang": r["lang"],
                "source": r["source"],
                "secret": r["secret"],
                "par": r["par"],
                "chill_spread": r["chill_spread"],
                "sharp_spread": r["sharp_spread"],
                "flags": r["flags"],
            }
            for r in flagged
        ],
    }


if __name__ == "__main__":
    result = run_dimension4()
    print("=== dimension 4 — rival calibration ===")
    print(f"  n_puzzles: {result['n_puzzles']}")
    print(f"  median_par: {result['median_par']} (target 8-12: {result['median_within_target']})")
    print(f"  par_within_target_range: {result['par_within_target_range']:.3f}")
    print(f"  median_chill_spread: {result['median_chill_spread']} "
          f"(within target: {result['chill_spread_within_target']:.3f})")
    print(f"  median_sharp_spread: {result['median_sharp_spread']} "
          f"(within target: {result['sharp_spread_within_target']:.3f})")
    print(f"  per_lang: {result['per_lang']}")
    print(f"  n_flagged: {result['n_flagged']}")
    for f in result["flagged_puzzles"][:20]:
        print(f"    {f['lang']:5s} {f['source']:15s} {f['secret']:12s} par={f['par']} "
              f"chill_spread={f['chill_spread']} sharp_spread={f['sharp_spread']} :: {f['flags']}")
