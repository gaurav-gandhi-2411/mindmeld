from __future__ import annotations

"""
Coverage for the semantic-proximity scrub (evals/finetune/
semantic_scrub_public_benchmark.py). Complements test_scrub_public_benchmark.py
(string/morphological collisions) -- this checks the embedding-rank-based
check that catches leaks with zero string overlap.
"""

from evals.finetune.semantic_scrub_public_benchmark import (
    _benchmark_words_by_lang,
    _live_secrets_by_lang,
    find_semantic_hits,
    run_scrub,
)


def test_benchmark_words_cover_all_34_secrets() -> None:
    """dim1_hien's `secret` field is always the hi-en name (34 distinct).
    dim1_en's `secret` field uses the EN gloss instead, and dim2 tags its
    en_gloss records with the hi-en name as `owning_secret` -- so the "en"
    lang's owning-secret set is a mix of both naming schemes (up to 68
    distinct identifiers for the same 34 underlying secrets). Both schemes
    are internally self-consistent for the "exclude a word's own secret"
    check in find_semantic_hits, since EN-language live secrets never
    coincide with hi-en secret names.
    """
    bench = _benchmark_words_by_lang()
    hien_secrets = {s for _, s in bench["hi-en"]}
    assert len(hien_secrets) == 34
    en_owning_secrets = {s for _, s in bench["en"]}
    assert len(en_owning_secrets) <= 68
    assert len(en_owning_secrets) >= 34


def test_live_secrets_nonempty_both_langs() -> None:
    live = _live_secrets_by_lang()
    assert len(live["en"]) > 0
    assert len(live["hi-en"]) > 0


def test_a_words_own_secret_excluded_from_its_own_hits() -> None:
    """A benchmark word is never flagged against ITS OWN secret (that
    relationship is the benchmark's own near/mid/far label, not a leak)."""
    hits = find_semantic_hits()
    for h in hits:
        assert h.live_secret != h.benchmark_secret


def test_run_scrub_returns_consistent_counts() -> None:
    result = run_scrub()
    assert result["n_blocking"] == len(result["blocking_hits"])
    assert result["n_advisory"] == len(result["advisory_hits"])
    assert result["passed"] == (result["n_blocking"] == 0)


def test_known_fixed_collision_no_longer_blocking() -> None:
    """'physician' (yogurt's prior far-tier word) was a rank=3 semantic
    near-miss against the live EN secret 'doctor' -- replaced with
    'tribunal'. Regression guard: 'physician' must no longer appear as a
    dim1_en far-tier word for 'yogurt' at all.
    """
    bench = _benchmark_words_by_lang()
    yogurt_words = {w for w, s in bench["en"] if s == "yogurt"}
    assert "physician" not in yogurt_words
