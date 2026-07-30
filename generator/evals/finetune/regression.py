from __future__ import annotations

"""
Per-pair regression-floor accounting -- same methodology as
`data/ship_decision_report{,_v2}.md`'s "Regression floor" sections, extracted
into a reusable function so every sweep config gets an identical, honest
fixed-vs-broken count instead of hand-computed per-report prose.

"Fixed" = wrong on baseline, right on candidate. "Broken" = right on
baseline, wrong on candidate. Net = fixed - broken. Zero net regression
requires net >= 0 AND (per the ship reports' stricter reading) broken == 0 --
a config that fixes 5 and breaks 5 is NOT "zero regression" even though net
is 0, because 5 real working pairs stopped working.
"""


def dim1_regression_floor(baseline_records: list[dict], candidate_records: list[dict]) -> dict:
    def key(r: dict) -> tuple[str, str]:
        return (r["secret"], r["word"])

    base_by_key = {key(r): r["in_expected_band"] for r in baseline_records}
    cand_by_key = {key(r): r["in_expected_band"] for r in candidate_records}
    shared = sorted(set(base_by_key) & set(cand_by_key))

    fixed = [k for k in shared if not base_by_key[k] and cand_by_key[k]]
    broken = [k for k in shared if base_by_key[k] and not cand_by_key[k]]
    return {
        "n_shared_pairs": len(shared),
        "n_fixed": len(fixed),
        "n_broken": len(broken),
        "net": len(fixed) - len(broken),
        "zero_net_regression": len(fixed) >= len(broken),
        "zero_regression_strict": len(broken) == 0,
        "fixed_pairs": [f"{s}/{w}" for s, w in fixed],
        "broken_pairs": [f"{s}/{w}" for s, w in broken],
    }


def dim2_regression_floor(baseline_records: list[dict], candidate_records: list[dict]) -> dict:
    def key(r: dict) -> tuple[str, str]:
        return (r["en_secret"], r["hien_secret"])

    base_by_key = {
        key(r): r["consistent"] for r in baseline_records if r["resolution_error"] is None
    }
    cand_by_key = {
        key(r): r["consistent"] for r in candidate_records if r["resolution_error"] is None
    }
    shared = sorted(set(base_by_key) & set(cand_by_key))

    fixed = [k for k in shared if not base_by_key[k] and cand_by_key[k]]
    broken = [k for k in shared if base_by_key[k] and not cand_by_key[k]]
    return {
        "n_shared_pairs": len(shared),
        "n_fixed": len(fixed),
        "n_broken": len(broken),
        "net": len(fixed) - len(broken),
        "zero_net_regression": len(fixed) >= len(broken),
        "zero_regression_strict": len(broken) == 0,
        "fixed_pairs": [f"{en}->{h}" for en, h in fixed],
        "broken_pairs": [f"{en}->{h}" for en, h in broken],
    }
