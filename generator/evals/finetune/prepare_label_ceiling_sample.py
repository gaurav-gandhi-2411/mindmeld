from __future__ import annotations

"""
spec-model-excellence.md WORKSTREAM D, item 13 (prep only) -- label-ceiling
measurement. The near/mid/far tiers on the public benchmark are AI-authored
(gen_dim1_benchmark_supplement.py's hand-curated near/mid tiers + build_
scenarios' hashed-RNG far sampling). This module draws a stratified,
independently-judgeable sample from the frozen 34-secret PUBLIC benchmark for
GG to annotate BLIND -- i.e. without seeing the AI-assigned tier -- so
human<->benchmark agreement can be measured. This establishes the benchmark's
own ceiling: without it, "how far from perfect are we" is unanswerable.

Source of truth: evals/finetune/data/public_benchmark_staging/dim1_hien.json
-- confirmed (by direct diff, see power_analysis.py's module docstring) to be
the FINAL, post-scrub, PUBLISHED content, NOT the same as
evals/scenarios/dim1_benchmark_supplement_hien.json (a stale pre-swap
engineering copy: 302 vs 306 records, 24 words differ per
public_benchmark_reverify.py's docstring). Judging the stale file would be
pointless -- some of its (secret, word) pairs are no longer in the actual
published benchmark. Domain comes from
evals.gen_dim1_benchmark_supplement.BENCHMARK_SUPPLEMENT_PAIRS (the single
source of truth for hien_secret -> domain), joined onto the staging records
by secret.

Sample size: 75 (25 per tier x 3 tiers) -- inside the spec's 60-90 target
range, chosen as the largest cleanly tier-divisible round number in range
that stays comfortably within a single-sitting annotation budget (a domain
expert can judge ~75 (secret, word) pairs -- each a 3-way near/mid/far call
-- in under an hour; 90 pairs would add ~20% more time for diminishing
statistical return on a 34-secret pool that only has 67 near-tier and 68
mid-tier records total, i.e. sampling much past 25 near/mid would already be
drawing most of the population).

Stratification: tier (near/mid/far) x domain (the 7 domains in
BENCHMARK_SUPPLEMENT_PAIRS) -- allocated per tier via largest-remainder
proportional rounding against each domain's population WITHIN that tier
(near/mid/far are each close to uniformly distributed across the 7 domains
already -- verified empirically: near ranges 8-10 per domain, mid is 8 or 10
per domain, far ranges 20-25 per domain -- so proportional allocation is
close to equal allocation per domain, "to the extent the data supports even
stratification" per the spec).

Output: evals/finetune/data/label_ceiling_sample_for_gg.csv, columns EXACTLY
`secret, word, domain, gg_tier_judgment` (the last column left BLANK for GG
to fill in) -- deliberately omits `tier`/`expected_bands`/`subtype`/`note`
from the source record, since GG must judge blind, without seeing the
AI-assigned label, or this is not independent annotation. A companion
instructions file is written alongside explaining the judging task in plain
language.

Run (from generator/):
    uv run python -m evals.finetune.prepare_label_ceiling_sample
"""

import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from evals.gen_dim1_benchmark_supplement import BENCHMARK_SUPPLEMENT_PAIRS

FINETUNE_DIR = Path(__file__).parent
DATA_DIR = FINETUNE_DIR / "data"
STAGING_DIM1_HIEN = DATA_DIR / "public_benchmark_staging" / "dim1_hien.json"
OUT_CSV = DATA_DIR / "label_ceiling_sample_for_gg.csv"
OUT_INSTRUCTIONS = DATA_DIR / "label_ceiling_sample_for_gg_INSTRUCTIONS.txt"

SEED = 42
TIERS: tuple[str, ...] = ("near", "mid", "far")
TARGET_TOTAL = 75
PER_TIER_TARGET = TARGET_TOTAL // len(TIERS)  # 25 -- see module docstring for the size rationale

CSV_COLUMNS: tuple[str, ...] = ("secret", "word", "domain", "gg_tier_judgment")

INSTRUCTIONS_TEXT = """\
Label-ceiling annotation instructions (spec-model-excellence.md item 13)
==========================================================================

For each row below, you are given a `secret` word and a candidate `word`.
Judge, using your own understanding of English/Hinglish, how RELATED
`word` is to `secret`, and fill in the `gg_tier_judgment` column with
EXACTLY ONE of:

  near  -- word is DIRECTLY or STRONGLY related to secret
  mid   -- word is MODERATELY or LOOSELY related to secret
  far   -- word is NOT REALLY related to secret

Please do this in a single sitting, judging each pair independently and
blind (this file deliberately does not show you the AI-assigned tier).
Don't look up the benchmark source files while doing this -- the whole
point is an independent judgment to measure how much a human and the
AI-authored labels agree.

When done, save the completed CSV and hand it back for scoring via
evals/finetune/score_label_ceiling.py.
"""


def secret_to_domain() -> dict[str, str]:
    """hien_secret -> domain, from BENCHMARK_SUPPLEMENT_PAIRS (the single
    source of truth for this supplement's 34 secrets' domains)."""
    return {hien: domain for hien, _en, domain in BENCHMARK_SUPPLEMENT_PAIRS}


def load_public_benchmark_dim1_records() -> list[dict]:
    """Raw dim1 records for the 34-secret PUBLIC (published, post-scrub)
    benchmark. Pure file IO, no model/embedding call."""
    return json.loads(STAGING_DIM1_HIEN.read_text(encoding="utf-8"))


def _allocate_per_domain(pop_by_domain: dict[str, int], target: int) -> dict[str, int]:
    """Largest-remainder proportional allocation of `target` draws across
    domains weighted by `pop_by_domain`, capped at each domain's own
    population (never allocate more than exists). Ties in the fractional
    remainder are broken alphabetically by domain name for determinism."""
    domains = sorted(pop_by_domain)
    total_pop = sum(pop_by_domain.values())
    if total_pop == 0 or target <= 0:
        return {d: 0 for d in domains}
    target = min(target, total_pop)
    raw = {d: target * pop_by_domain[d] / total_pop for d in domains}
    floor = {d: int(np.floor(raw[d])) for d in domains}
    by_fraction_desc = sorted(domains, key=lambda d: (-(raw[d] - floor[d]), d))
    alloc = dict(floor)
    i = 0
    # Distribute the rounding remainder one unit at a time, skipping any
    # domain already at its population cap, until `target` is reached --
    # a plain top-`remainder` slice could over-allocate a small-population
    # domain past what it actually has.
    while sum(alloc.values()) < target:
        d = by_fraction_desc[i % len(by_fraction_desc)]
        if alloc[d] < pop_by_domain[d]:
            alloc[d] += 1
        i += 1
        if i > 10 * len(domains):  # population fully exhausted across the board
            break
    return alloc


def stratified_sample(
    records: list[dict],
    domain_of: dict[str, str],
    per_tier_target: int = PER_TIER_TARGET,
    seed: int = SEED,
) -> list[dict]:
    """Stratified (tier x domain) sample, without replacement, seeded for
    reproducibility. Returns the FULL source records for the sampled rows
    (tier/expected_bands/subtype/note included) -- CSV-writing strips the
    AI-visible fields separately, so this function stays independently
    testable against the richer record shape.

    The returned list is shuffled (same seeded rng) before being handed
    back -- sampling is done tier-by-tier internally, so an UNSHUFFLED
    return would put all "near" rows first, all "mid" rows next, all "far"
    rows last, silently leaking the withheld tier via row position alone
    (GG would notice "this whole block reads as closely related" well
    before reaching the gg_tier_judgment column). Blind annotation requires
    the row order itself to carry no tier signal.
    """
    by_cell: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in records:
        by_cell[(r["tier"], domain_of[r["secret"]])].append(r)

    rng = np.random.default_rng(seed)
    sample: list[dict] = []
    for tier in TIERS:
        domains_in_tier = sorted({d for (t, d) in by_cell if t == tier})
        pop_by_domain = {d: len(by_cell[(tier, d)]) for d in domains_in_tier}
        alloc = _allocate_per_domain(pop_by_domain, per_tier_target)
        for domain, k in alloc.items():
            if k == 0:
                continue
            pool = by_cell[(tier, domain)]
            idx = rng.choice(len(pool), size=k, replace=False)
            sample.extend(pool[i] for i in idx)
    rng.shuffle(sample)
    return sample


def write_csv(sample: list[dict], out_path: Path = OUT_CSV) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(CSV_COLUMNS))
        writer.writeheader()
        for r in sample:
            writer.writerow(
                {
                    "secret": r["secret"],
                    "word": r["word"],
                    "domain": r["domain"],
                    "gg_tier_judgment": "",
                }
            )


def build_stratification_breakdown(sample: list[dict]) -> dict[str, dict[str, int]]:
    """tier -> domain -> count, for reporting."""
    out: dict[str, dict[str, int]] = {t: defaultdict(int) for t in TIERS}
    for r in sample:
        out[r["tier"]][r["domain"]] += 1
    return {t: dict(sorted(d.items())) for t, d in out.items()}


def main() -> None:
    domain_of = secret_to_domain()
    records = load_public_benchmark_dim1_records()
    for r in records:
        r["domain"] = domain_of[r["secret"]]
    sample = stratified_sample(records, domain_of)
    write_csv(sample)
    OUT_INSTRUCTIONS.write_text(INSTRUCTIONS_TEXT, encoding="utf-8")
    breakdown = build_stratification_breakdown(sample)
    print(f"wrote {OUT_CSV} ({len(sample)} rows) and {OUT_INSTRUCTIONS}")
    print(json.dumps(breakdown, indent=2))


if __name__ == "__main__":
    main()
