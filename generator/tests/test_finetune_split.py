from __future__ import annotations

"""
Frozen train/dev/test split invariants (evals/finetune/split.py) — the
cardinal-rule guard for the hi-en fine-tune (spec-hinglish-finetune.md).
These assertions must hold regardless of when/how the split is rebuilt:
determinism, disjointness, and the 5 documented residual-weak secrets
always landing in test (never trainable).
"""

from evals.finetune.split import FORCED_TEST_SECRETS, build_split, build_split_with_supplement
from evals.gen_dim1_benchmark_supplement import BENCHMARK_SUPPLEMENT_PAIRS


def test_split_is_deterministic():
    a = build_split()
    b = build_split()
    assert a == b


def test_split_partitions_are_disjoint_and_complete():
    split = build_split()
    train = set(split["train_secrets"])
    dev = set(split["dev_secrets"])
    test = set(split["test_secrets"])

    assert not (train & dev)
    assert not (train & test)
    assert not (dev & test)
    assert train | dev | test == set(train) | set(dev) | set(test)
    assert len(train) + len(dev) + len(test) == split["total_secrets"]


def test_forced_weak_secrets_are_always_in_test():
    split = build_split()
    test = set(split["test_secrets"])
    for secret in FORCED_TEST_SECRETS:
        assert secret in test, f"{secret} must be forced into test (residual-weak guard)"


def test_held_out_secrets_is_dev_union_test():
    split = build_split()
    expected = set(split["dev_secrets"]) | set(split["test_secrets"])
    assert set(split["held_out_secrets"]) == expected
    assert not (expected & set(split["train_secrets"]))


def test_held_out_en_translations_match_held_out_secrets():
    split = build_split()
    all_held_out_pairs = split["dev_pairs"] + split["test_pairs"]
    held_out_hien = {hien for _en, hien in all_held_out_pairs}
    held_out_en = {en for en, _hien in all_held_out_pairs}
    assert held_out_hien == set(split["held_out_secrets"])
    assert held_out_en == set(split["held_out_en_translations"])


def test_build_split_with_supplement_does_not_mutate_build_split():
    """`build_split_with_supplement()` must be a pure add-on: the plain
    `build_split()` result (what test_finetune_split.py's other tests
    exercise) has to stay byte-identical whether or not the supplement
    wrapper is ever called — spec-hinglish-benchmark.md Phase 1a's
    constraint that the daily-schedule 60-word train/dev/test assignment is
    never touched by the benchmark-supplement expansion."""
    plain = build_split()
    build_split_with_supplement()  # exercised for a side-effect-on-build_split check
    assert build_split() == plain


def test_build_split_with_supplement_unions_supplement_into_test_and_held_out():
    supplement = build_split_with_supplement()
    plain = build_split()

    supplement_hien = {hien for hien, _en, _domain in BENCHMARK_SUPPLEMENT_PAIRS}
    supplement_en = {en for _hien, en, _domain in BENCHMARK_SUPPLEMENT_PAIRS}

    # Never touches train/dev — additive to test/held-out only.
    assert set(supplement["train_secrets"]) == set(plain["train_secrets"])
    assert set(supplement["dev_secrets"]) == set(plain["dev_secrets"])

    assert supplement_hien <= set(supplement["test_secrets"])
    assert supplement_hien <= set(supplement["held_out_secrets"])
    assert supplement_en <= set(supplement["held_out_en_translations"])
    assert set(supplement["benchmark_supplement_secrets"]) == supplement_hien
    assert set(supplement["benchmark_supplement_en_translations"]) == supplement_en

    # Zero overlap between the new secrets and the pre-existing 60-word schedule.
    assert not (supplement_hien & set(plain["train_secrets"]))
    assert not (supplement_hien & set(plain["dev_secrets"]))
    assert not (supplement_hien & set(plain["test_secrets"]))

    assert supplement["counts"]["test"] == len(plain["test_secrets"]) + len(supplement_hien)
