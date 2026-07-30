from __future__ import annotations

"""
spec-model-excellence.md WORKSTREAM D, item 13 -- score a completed
label-ceiling annotation CSV (see prepare_label_ceiling_sample.py) against
the withheld AI-assigned tier for the same (secret, word) pairs.

NOT run against real GG annotation in this task -- no completed CSV exists
yet (evals/finetune/data/label_ceiling_sample_for_gg.csv's gg_tier_judgment
column is blank, as prepared). This module is written and verified now
(against a SYNTHETIC filled-in test CSV -- see
tests/test_label_ceiling_sample.py and the __main__ smoke path below) so no
further engineering is needed once GG returns the real completed CSV.

Metrics computed:
  - raw (unweighted) agreement rate
  - LINEAR-weighted Cohen's kappa, with a bootstrap CI. Linear weights
    (not quadratic) chosen because: (a) near/mid/far is a 3-level ordinal
    scale where "off by one" (near<->mid, mid<->far) and "off by two"
    (near<->far) should count as increasingly-serious disagreements, which
    a weighted kappa captures and unweighted kappa does not; (b) quadratic
    weighting disproportionately amplifies the penalty for the single
    "off by two" case relative to the two "off by one" cases (weight
    ratio 4:1 vs linear's 2:1), which is a stronger and less-motivated
    assumption for a 3-level scale this small -- linear is the more
    conservative, easier-to-justify default here.
  - 3x3 confusion matrix, AI-assigned tier (rows) x GG judgment (cols).

Run (from generator/):
    uv run python -m evals.finetune.score_label_ceiling
    uv run python -m evals.finetune.score_label_ceiling --csv path/to/completed.csv
"""

import argparse
import csv
import json
from pathlib import Path

import numpy as np

FINETUNE_DIR = Path(__file__).parent
DATA_DIR = FINETUNE_DIR / "data"
STAGING_DIM1_HIEN = DATA_DIR / "public_benchmark_staging" / "dim1_hien.json"
DEFAULT_CSV = DATA_DIR / "label_ceiling_sample_for_gg.csv"
OUT_JSON = DATA_DIR / "label_ceiling_score_report.json"
OUT_MD = DATA_DIR / "label_ceiling_score_report.md"

CATEGORIES: tuple[str, ...] = ("near", "mid", "far")
N_BOOT = 5000
SEED = 42


def load_ai_tier_lookup() -> dict[tuple[str, str], str]:
    """(secret, word) -> AI-assigned tier, from the frozen 34-secret PUBLIC
    benchmark's dim1 records. (secret, word) is unique across this file
    (verified: 302 records, 302 unique pairs), so this is a safe direct
    join key."""
    records = json.loads(STAGING_DIM1_HIEN.read_text(encoding="utf-8"))
    return {(r["secret"], r["word"]): r["tier"] for r in records}


def load_completed_csv(path: Path) -> list[dict]:
    """Read a completed label-ceiling CSV. Returns the raw rows (dicts with
    secret/word/domain/gg_tier_judgment) -- validation of gg_tier_judgment
    happens in join_with_ai_tier, so a partially-completed CSV can still be
    scored on whatever rows ARE filled in."""
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def join_with_ai_tier(rows: list[dict], ai_lookup: dict[tuple[str, str], str]) -> dict:
    """Join each row's gg_tier_judgment against the withheld AI tier for the
    same (secret, word). Returns {"scored": [...], "skipped": [...]} --
    "skipped" rows are those with a blank/invalid gg_tier_judgment or a
    (secret, word) not found in the AI-tier lookup (data-entry error), each
    tagged with a `reason`, never silently dropped."""
    scored: list[dict] = []
    skipped: list[dict] = []
    for row in rows:
        secret, word = row["secret"], row["word"]
        judgment_raw = (row.get("gg_tier_judgment") or "").strip().lower()
        ai_tier = ai_lookup.get((secret, word))
        if ai_tier is None:
            reason = f"(secret,word)=({secret!r},{word!r}) not in benchmark"
            skipped.append({**row, "reason": reason})
        elif judgment_raw not in CATEGORIES:
            skipped.append(
                {**row, "reason": f"gg_tier_judgment={judgment_raw!r} not one of {CATEGORIES}"}
            )
        else:
            scored.append(
                {"secret": secret, "word": word, "ai_tier": ai_tier, "gg_tier": judgment_raw}
            )
    return {"scored": scored, "skipped": skipped}


def confusion_matrix(
    pairs: list[tuple[str, str]], categories: tuple[str, ...] = CATEGORIES
) -> np.ndarray:
    """categories[i] x categories[j] count matrix, rows = first element of
    each pair (AI tier), cols = second element (GG tier)."""
    idx = {c: i for i, c in enumerate(categories)}
    m = np.zeros((len(categories), len(categories)), dtype=int)
    for a, b in pairs:
        m[idx[a], idx[b]] += 1
    return m


def _weight_matrix(k: int, scheme: str) -> np.ndarray:
    """Cohen's weighted-kappa weight matrix for `k` ORDINAL categories in
    fixed order (index = ordinal position). scheme="linear": w_ij =
    1 - |i-j|/(k-1). scheme="none": identity (unweighted kappa, w_ij = 1
    iff i==j)."""
    i = np.arange(k)
    diff = np.abs(i[:, None] - i[None, :])
    if scheme == "linear":
        return 1.0 - diff / (k - 1)
    if scheme == "none":
        return (diff == 0).astype(float)
    raise ValueError(f"unsupported weight scheme: {scheme!r}")


def weighted_kappa_from_confusion(m: np.ndarray, weights: str = "linear") -> float:
    """Cohen's (weighted) kappa from a k x k confusion matrix `m`. Returns
    NaN if the matrix is empty (n=0) or if pe==1 (kappa undefined, chance
    agreement already perfect)."""
    n = float(m.sum())
    if n == 0:
        return float("nan")
    k = m.shape[0]
    w = _weight_matrix(k, weights)
    row_marg = m.sum(axis=1) / n
    col_marg = m.sum(axis=0) / n
    po = float((w * (m / n)).sum())
    pe = float((w * np.outer(row_marg, col_marg)).sum())
    if pe >= 1.0:
        return float("nan")
    return (po - pe) / (1.0 - pe)


def cohens_kappa(
    pairs: list[tuple[str, str]], categories: tuple[str, ...] = CATEGORIES, weights: str = "linear"
) -> float:
    """Weighted Cohen's kappa for a list of (rater_a_label, rater_b_label)
    pairs over `categories` (fixed ordinal order)."""
    return weighted_kappa_from_confusion(confusion_matrix(pairs, categories), weights)


def raw_agreement_rate(pairs: list[tuple[str, str]]) -> float | None:
    if not pairs:
        return None
    return float(np.mean([1.0 if a == b else 0.0 for a, b in pairs]))


def bootstrap_kappa_ci(
    pairs: list[tuple[str, str]],
    categories: tuple[str, ...] = CATEGORIES,
    weights: str = "linear",
    n_boot: int = N_BOOT,
    seed: int = SEED,
) -> dict:
    """Percentile bootstrap CI on cohens_kappa, resampling PAIRS (items)
    with replacement -- the standard bootstrap unit for an agreement study
    (each annotated item is an independent draw, unlike the by-secret
    clustering used elsewhere in this repo's dim1 bootstraps, because a
    label-ceiling item's annotation doesn't share randomness with any other
    item the way multiple scenarios under one secret's rank table do)."""
    point = cohens_kappa(pairs, categories, weights)
    n = len(pairs)
    if n == 0:
        return {"point": point, "ci_95": None, "n_pairs": 0, "n_valid_bootstrap_draws": 0}
    rng = np.random.default_rng(seed)
    idx_all = np.arange(n)
    samples = []
    for _ in range(n_boot):
        idx = rng.choice(idx_all, size=n, replace=True)
        resampled = [pairs[i] for i in idx]
        val = cohens_kappa(resampled, categories, weights)
        if not np.isnan(val):
            samples.append(val)
    if len(samples) >= 2:
        ci: list[float] | None = [
            float(np.percentile(samples, 2.5)),
            float(np.percentile(samples, 97.5)),
        ]
    else:
        ci = None
    return {
        "point": point,
        "ci_95": ci,
        "n_pairs": n,
        "n_valid_bootstrap_draws": len(samples),
    }


def score(scored_rows: list[dict]) -> dict:
    """Full metric bundle for a list of already-joined {"ai_tier",
    "gg_tier", ...} rows (join_with_ai_tier's "scored" list)."""
    pairs = [(r["ai_tier"], r["gg_tier"]) for r in scored_rows]
    return {
        "n_scored": len(pairs),
        "raw_agreement_rate": raw_agreement_rate(pairs),
        "weighted_kappa_linear": bootstrap_kappa_ci(pairs, weights="linear"),
        "unweighted_kappa": bootstrap_kappa_ci(pairs, weights="none"),
        "confusion_matrix": {
            "categories": list(CATEGORIES),
            "rows_are": "ai_tier",
            "cols_are": "gg_tier",
            "matrix": confusion_matrix(pairs).tolist(),
        },
    }


def render_markdown(result: dict) -> str:
    cm = result["confusion_matrix"]
    cats = cm["categories"]
    lines = [
        "# Label-ceiling score report -- spec-model-excellence.md WORKSTREAM D item 13",
        "",
        f"n scored: {result['n_scored']} | n skipped: {result['n_skipped']}",
        "",
        f"Raw agreement rate: {result['raw_agreement_rate']}",
        f"Weighted kappa (linear): {result['weighted_kappa_linear']}",
        f"Unweighted kappa: {result['unweighted_kappa']}",
        "",
        f"Confusion matrix (rows={cm['rows_are']}, cols={cm['cols_are']}):",
        "",
        "| | " + " | ".join(cats) + " |",
        "|---|" + "---|" * len(cats),
    ]
    for tier, row in zip(cats, cm["matrix"], strict=True):
        lines.append(f"| {tier} | " + " | ".join(str(c) for c in row) + " |")
    if result["skipped"]:
        lines += ["", "## Skipped rows", ""]
        for s in result["skipped"]:
            lines.append(f"- {s['secret']}/{s['word']}: {s['reason']}")
    return "\n".join(lines) + "\n"


def score_csv(csv_path: Path) -> dict:
    ai_lookup = load_ai_tier_lookup()
    rows = load_completed_csv(csv_path)
    joined = join_with_ai_tier(rows, ai_lookup)
    result = score(joined["scored"])
    result["n_skipped"] = len(joined["skipped"])
    result["skipped"] = joined["skipped"]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv", type=Path, default=DEFAULT_CSV, help="Path to the completed label-ceiling CSV"
    )
    args = parser.parse_args()

    result = score_csv(args.csv)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    OUT_MD.write_text(render_markdown(result), encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"wrote {OUT_JSON} and {OUT_MD}")


if __name__ == "__main__":
    main()
