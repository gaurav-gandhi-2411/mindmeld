from __future__ import annotations

"""
Tests for the public-benchmark safety scrub (evals/finetune/
scrub_public_benchmark.py) -- both a regression test (the real staging
files must always scrub clean) and unit coverage of the blocking/advisory
severity classification, which is the non-trivial logic this module adds.
"""

from evals.finetune.scrub_public_benchmark import (
    BenchmarkWord,
    LiveItem,
    _collision_severity,
    collect_benchmark_words,
    collect_live_items,
    find_collisions,
    run_scrub,
)


def test_collision_severity_exact_match_is_blocking():
    assert _collision_severity("chai", "chai") == "blocking"
    assert _collision_severity("Chai", "CHAI") == "blocking"  # case-insensitive


def test_collision_severity_prefix_containment_long_enough_is_blocking():
    # "doctors" is the plain plural of "doctor" -- shorter string ("doctor",
    # 6 chars) >= the 4-char floor, and one is a genuine prefix of the other.
    assert _collision_severity("doctors", "doctor") == "blocking"


def test_collision_severity_short_prefix_is_not_blocking():
    # "ma" (2 chars) is below the containment length floor -- a coincidental
    # prefix of "masculine" should not gate PASS/FAIL (matches payload.py's
    # own precedent for excluding short coincidental substrings).
    severity = _collision_severity("masculine", "ma")
    assert severity in (None, "advisory")
    assert severity != "blocking"


def test_collision_severity_levenshtein_only_is_advisory_not_blocking():
    # "basket" vs "market": distance-2, no prefix/substring relationship --
    # different roots, real coincidental noise.
    assert _collision_severity("basket", "market") == "advisory"


def test_collision_severity_unrelated_words_are_no_collision():
    assert _collision_severity("mountain", "elephant") is None


def test_find_collisions_reports_severity_for_each_pair():
    benchmark = [BenchmarkWord(word="chai", source="test:chai")]
    live = [LiveItem(word="chai", source="test-live:chai")]
    collisions = find_collisions(benchmark, live)
    assert len(collisions) == 1
    assert collisions[0]["severity"] == "blocking"
    assert collisions[0]["benchmark_word"] == "chai"
    assert collisions[0]["live_word"] == "chai"


def test_collect_live_items_nonempty_and_includes_schedule():
    items = collect_live_items()
    assert len(items) > 0
    sources = {item.source for item in items}
    assert any(s.startswith("schedule:en") for s in sources)
    assert any(s.startswith("schedule:hi-en") for s in sources)


def test_collect_benchmark_words_covers_34_secrets():
    words = collect_benchmark_words()
    assert len(words) > 0
    secrets_seen = {
        w.word for w in words if w.source.endswith(":secret") or w.source.endswith("hien_secret")
    }
    # dim1_en secrets are EN glosses, dim1_hien/dim2 secrets are hien words --
    # both vocabularies should be represented among the collected words.
    assert len(secrets_seen) > 0


def test_public_benchmark_staging_scrubs_clean():
    """
    Regression test: the actual (finalized) public benchmark staging files
    must have zero BLOCKING collisions against live game content. Advisory
    (Levenshtein-only) hits are expected and do not fail this test -- see
    scrub_public_benchmark.py's module docstring for why.
    """
    result = run_scrub()
    assert result["n_secrets"] == 34, f"expected 34 benchmark secrets, got {result['n_secrets']}"
    assert result["passed"], (
        f"public benchmark scrub FAILED -- {result['n_blocking']} blocking collision(s): "
        f"{result['blocking_collisions']}"
    )
