from __future__ import annotations

"""
Frozen train/dev/test split over the hi-en daily-schedule secrets — the ONE
split every training-data source and every reported eval number must respect.

Cardinal rule (spec-hinglish-finetune.md): whatever is used for TRAINING is
REMOVED from the eval. This module defines "used for training" at the
SECRET level (both the romanized-Hindi secret and its paired EN translation),
not at the individual-pair level, because:
  - dimension1 triplets are keyed by secret,
  - dimension2 cross-language pairs ARE (hien_secret, en_translation),
  - the residual known-weak pairs (titli, khamoshi, rasoi, samunder,
    bachpan) are secrets.
A single frozen `held_out_secrets` set (dev ∪ test) is exported and every
training-data assembly source in assemble_data.py excludes ANY record that
touches one of those secrets or its exact EN translation, at all — not just
as an anchor. This is intentionally broader than "don't train on the exact
eval pair": a held-out secret must not appear anywhere in the training set,
so verifying no-leakage is a single membership check per training record.

Split method: the 5 documented residual-weak secrets (baseline_report.md /
known-limitations.md #1) are FORCED into test — they are the honest signal
for whether the fine-tune actually helps the hard cases, so they must never
be trained on. The remaining 55 schedule secrets are shuffled with a fixed
seed and split ~60/20/20 into train/dev/test.

Benchmark-supplement secrets (spec-hinglish-benchmark.md Phase 1a):
`evals/gen_dim1_benchmark_supplement.py`'s 34 additional held-out secrets are
unioned into test_secrets/held_out_secrets/held_out_en_translations by
`build_split_with_supplement()` below, AFTER `build_split()`'s own schedule-
only computation and assertions have already run and returned. This is
deliberate: `build_split()` itself is NEVER modified (its 60-word daily-
schedule train/dev/test assignment stays byte-identical, so
tests/test_finetune_split.py's existing invariants — which call
build_split() directly — keep passing against the pure schedule-only
split), while `build_split_with_supplement()`'s enriched result is what
actually gets WRITTEN to split.json. Every downstream reader of the
persisted file — assemble_data.py (so future re-assembly runs also exclude
the 34 new secrets from training) and tests/test_finetune_no_leakage.py
(so its membership check automatically covers the bigger held-out set) —
goes through `load_split()`, which just reads split.json, so both pick up
the union for free with zero changes to their own code.

Run: uv run python -m evals.finetune.split
Output: evals/finetune/data/split.json
"""

import json
import random
from pathlib import Path

from evals.harness.pairs import load_daily_pairs

OUT_PATH = Path(__file__).parent / "data" / "split.json"

SEED = 42
DEV_FRAC = 0.20
TEST_FRAC = 0.20

# The residual worst-diverging pairs called out in the baseline report and
# known-limitations.md #1 — forced into TEST so the ship decision's
# "residual weak pairs" check is provably held-out, never trained on.
FORCED_TEST_SECRETS = frozenset({"titli", "khamoshi", "rasoi", "samunder", "bachpan"})


def build_split() -> dict:
    pairs = load_daily_pairs()  # [(en_secret, hien_secret), ...], schedule order
    by_hien = {hien: en for en, hien in pairs}
    all_hien = [hien for _en, hien in pairs]
    assert len(all_hien) == len(set(all_hien)), "duplicate hien secrets in schedule"

    forced_test = sorted(FORCED_TEST_SECRETS & set(all_hien))
    missing = FORCED_TEST_SECRETS - set(all_hien)
    if missing:
        raise ValueError(f"forced-test secrets not found in schedule: {missing}")

    remaining = [h for h in all_hien if h not in FORCED_TEST_SECRETS]
    rng = random.Random(SEED)
    shuffled = remaining[:]
    rng.shuffle(shuffled)

    n = len(shuffled)
    n_dev = round(n * DEV_FRAC)
    n_test = round(n * TEST_FRAC)
    dev_secrets = sorted(shuffled[:n_dev])
    test_from_remaining = sorted(shuffled[n_dev : n_dev + n_test])
    train_secrets = sorted(shuffled[n_dev + n_test :])
    test_secrets = sorted(set(test_from_remaining) | set(forced_test))

    assert not (set(train_secrets) & set(dev_secrets))
    assert not (set(train_secrets) & set(test_secrets))
    assert not (set(dev_secrets) & set(test_secrets))
    assert set(train_secrets) | set(dev_secrets) | set(test_secrets) == set(all_hien)

    held_out_secrets = sorted(set(dev_secrets) | set(test_secrets))
    held_out_en = sorted({by_hien[h] for h in held_out_secrets})

    result = {
        "seed": SEED,
        "total_secrets": len(all_hien),
        "forced_test_secrets": forced_test,
        "train_secrets": train_secrets,
        "dev_secrets": dev_secrets,
        "test_secrets": test_secrets,
        "held_out_secrets": held_out_secrets,
        "held_out_en_translations": held_out_en,
        "train_pairs": [[by_hien[h], h] for h in train_secrets],
        "dev_pairs": [[by_hien[h], h] for h in dev_secrets],
        "test_pairs": [[by_hien[h], h] for h in test_secrets],
        "counts": {
            "train": len(train_secrets),
            "dev": len(dev_secrets),
            "test": len(test_secrets),
        },
    }
    return result


def build_split_with_supplement() -> dict:
    """`build_split()`'s result, plus the benchmark-supplement secrets
    (evals/gen_dim1_benchmark_supplement.py) unioned into
    test_secrets/held_out_secrets/held_out_en_translations/test_pairs — see
    module docstring's "Benchmark-supplement secrets" section for why this
    is a separate wrapper rather than a change to build_split() itself.
    """
    from evals.gen_dim1_benchmark_supplement import BENCHMARK_SUPPLEMENT_PAIRS

    split = build_split()

    supplement_hien = sorted(hien for hien, _en, _domain in BENCHMARK_SUPPLEMENT_PAIRS)
    supplement_en = sorted(en for _hien, en, _domain in BENCHMARK_SUPPLEMENT_PAIRS)

    # Never touches train_secrets/dev_secrets, never overlaps the daily-schedule
    # 60-secret pool — asserted, not assumed.
    schedule_secrets = (
        set(split["train_secrets"]) | set(split["dev_secrets"]) | set(split["test_secrets"])
    )
    overlap = set(supplement_hien) & schedule_secrets
    assert not overlap, f"benchmark-supplement secret collides with daily schedule: {overlap}"

    split["benchmark_supplement_secrets"] = supplement_hien
    split["benchmark_supplement_en_translations"] = supplement_en
    split["test_secrets"] = sorted(set(split["test_secrets"]) | set(supplement_hien))
    split["held_out_secrets"] = sorted(set(split["held_out_secrets"]) | set(supplement_hien))
    split["held_out_en_translations"] = sorted(
        set(split["held_out_en_translations"]) | set(supplement_en)
    )
    split["test_pairs"] = split["test_pairs"] + [
        [en, hien] for hien, en, _domain in BENCHMARK_SUPPLEMENT_PAIRS
    ]
    split["counts"]["test"] = len(split["test_secrets"])
    return split


def load_split() -> dict:
    if not OUT_PATH.exists():
        raise FileNotFoundError(
            f"{OUT_PATH} not found — run `uv run python -m evals.finetune.split` first"
        )
    return json.loads(OUT_PATH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    split = build_split_with_supplement()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(split, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT_PATH}")
    print(f"counts: {split['counts']}")
    print(f"forced-test (residual weak): {split['forced_test_secrets']}")
    print(
        f"benchmark_supplement_secrets ({len(split['benchmark_supplement_secrets'])}): "
        f"{split['benchmark_supplement_secrets']}"
    )
    print(f"held_out_secrets ({len(split['held_out_secrets'])}): {split['held_out_secrets']}")
