from __future__ import annotations

"""
Frozen dev/test split over the 34-secret public benchmark
(evals/finetune/data/public_benchmark_staging/*.json, spec-hinglish-
benchmark.md Phase 1c) -- the split every dev<->test correlation number and
every reported per-half metric must respect.

Mirrors evals/finetune/split.py's build_split()/load_split() pattern (same
module shape, same "frozen, versioned JSON output" convention) but is
DELIBERATELY a separate module/file: this benchmark's 34 secrets are a
disjoint concern from the fine-tune's own train/dev/test split (they were
already unioned into split.json's test_secrets, never train/dev -- see
split.py's build_split_with_supplement()) and this split answers a
different question ("does the benchmark's dev half predict its test half",
i.e. is the benchmark internally reliable), not "what did the model train
on".

Split method: stratified by domain (nature/emotion/abstract/object/place/
food/kinship) so both halves cover every domain, seed=42, deterministic.
6 domains have 5 secrets (odd) and 1 (kinship) has 4 (even) -- for the odd
domains, one half gets the "extra" secret; WHICH half alternates
domain-by-domain (in sorted-domain order) so the extras net out evenly
across the whole 34-secret set (3 domains' extra -> dev, 3 -> test),
producing an exact 17/17 split rather than a lopsided one from always
favoring the same half.

Run: uv run python -m evals.finetune.public_benchmark_split
Output: evals/finetune/data/public_benchmark_split.json
"""

import json
import random
from collections import defaultdict
from pathlib import Path

STAGING_DIR = Path(__file__).parent / "data" / "public_benchmark_staging"
DIM2_PAIRS_PATH = STAGING_DIR / "dim2_pairs.json"
OUT_PATH = Path(__file__).parent / "data" / "public_benchmark_split.json"

SEED = 42


def _secrets_by_domain() -> dict[str, list[str]]:
    """hien_secret grouped by domain, from dim2_pairs.json (single source of
    truth for the benchmark's 34 secret/domain assignments)."""
    records = json.loads(DIM2_PAIRS_PATH.read_text(encoding="utf-8"))
    by_domain: dict[str, list[str]] = defaultdict(list)
    for rec in records:
        by_domain[rec["domain"]].append(rec["hien_secret"])
    return dict(by_domain)


def build_split() -> dict:
    """
    Build the stratified dev/test split. See module docstring for the
    "extra secret alternates which half" balancing rule.
    """
    by_domain = _secrets_by_domain()
    total = sum(len(v) for v in by_domain.values())

    rng = random.Random(SEED)
    dev_secrets: list[str] = []
    test_secrets: list[str] = []
    domain_counts: dict[str, dict[str, int]] = {}

    odd_domain_index = 0
    for domain in sorted(by_domain):
        secrets = sorted(by_domain[domain])
        shuffled = secrets[:]
        rng.shuffle(shuffled)
        n = len(shuffled)
        half = n // 2

        if n % 2 == 0:
            dev_half, test_half = shuffled[:half], shuffled[half:]
        elif odd_domain_index % 2 == 0:
            # even-indexed odd domain -> extra secret goes to dev
            dev_half, test_half = shuffled[: half + 1], shuffled[half + 1 :]
            odd_domain_index += 1
        else:
            # odd-indexed odd domain -> extra secret goes to test
            dev_half, test_half = shuffled[:half], shuffled[half:]
            odd_domain_index += 1

        dev_secrets.extend(dev_half)
        test_secrets.extend(test_half)
        domain_counts[domain] = {"dev": len(dev_half), "test": len(test_half), "total": n}

    dev_secrets.sort()
    test_secrets.sort()

    assert not (set(dev_secrets) & set(test_secrets)), "dev/test overlap"
    assert len(dev_secrets) + len(test_secrets) == total == 34, (
        f"expected 34 total secrets, got {total} "
        f"({len(dev_secrets)} dev + {len(test_secrets)} test)"
    )
    assert all(dc["dev"] >= 1 and dc["test"] >= 1 for dc in domain_counts.values()), (
        "every domain must have >=1 secret in both halves"
    )

    return {
        "seed": SEED,
        "total_secrets": total,
        "dev_secrets": dev_secrets,
        "test_secrets": test_secrets,
        "domain_counts": domain_counts,
        "counts": {"dev": len(dev_secrets), "test": len(test_secrets)},
    }


def load_split() -> dict:
    if not OUT_PATH.exists():
        raise FileNotFoundError(
            f"{OUT_PATH} not found -- run `uv run python -m evals.finetune.public_benchmark_split` "
            "first"
        )
    return json.loads(OUT_PATH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    split = build_split()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(split, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT_PATH}")
    print(f"counts: {split['counts']}")
    print(f"dev_secrets ({len(split['dev_secrets'])}): {split['dev_secrets']}")
    print(f"test_secrets ({len(split['test_secrets'])}): {split['test_secrets']}")
    print("domain_counts:")
    for domain, counts in sorted(split["domain_counts"].items()):
        print(f"  {domain}: {counts}")
