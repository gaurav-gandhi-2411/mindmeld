from __future__ import annotations

"""
Tests for the public-benchmark dev/test split
(evals/finetune/public_benchmark_split.py) -- determinism, no-overlap,
full coverage, and per-domain stratification invariants.
"""

from evals.finetune.public_benchmark_split import build_split


def test_split_is_deterministic():
    a = build_split()
    b = build_split()
    assert a["dev_secrets"] == b["dev_secrets"]
    assert a["test_secrets"] == b["test_secrets"]


def test_split_covers_all_34_secrets_no_overlap():
    split = build_split()
    dev, test = set(split["dev_secrets"]), set(split["test_secrets"])
    assert not (dev & test), f"dev/test overlap: {dev & test}"
    assert len(dev) + len(test) == 34
    assert split["counts"]["dev"] == len(dev)
    assert split["counts"]["test"] == len(test)


def test_split_is_roughly_balanced():
    split = build_split()
    assert split["counts"]["dev"] == 17
    assert split["counts"]["test"] == 17


def test_every_domain_present_in_both_halves():
    split = build_split()
    for domain, counts in split["domain_counts"].items():
        assert counts["dev"] >= 1, f"domain {domain} has 0 dev secrets"
        assert counts["test"] >= 1, f"domain {domain} has 0 test secrets"
        assert counts["dev"] + counts["test"] == counts["total"]
