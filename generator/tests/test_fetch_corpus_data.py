from __future__ import annotations

"""
Unit tests for evals/finetune/fetch_corpus_data.py's pure functions
(build_translit_dict, verify_translit_quality's match classification).
No network access: these do not exercise fetch_aksharantar/
fetch_indiccorp_sample, which require live HTTP calls to huggingface.co and
are exercised manually (see the module docstring's Run: line).
"""

from evals.finetune.fetch_corpus_data import build_translit_dict, verify_translit_quality


def test_build_translit_dict_picks_most_frequent_romanization():
    # "क" romanized as "k" 3x and "q" 1x -> "k" wins on frequency.
    pairs = [("क", "k"), ("क", "k"), ("क", "k"), ("क", "q")]
    result = build_translit_dict(pairs)
    assert result["क"] == "k"


def test_build_translit_dict_ties_break_by_shortest_then_alphabetical():
    # "ख" tied 1x each between "kh" and "kha" -> shortest ("kh") wins.
    pairs = [("ख", "kh"), ("ख", "kha")]
    assert build_translit_dict(pairs)["ख"] == "kh"

    # "ग" tied 1x each between "gaa" and "gab", same length -> alphabetical.
    pairs2 = [("ग", "gab"), ("ग", "gaa")]
    assert build_translit_dict(pairs2)["ग"] == "gaa"


def test_build_translit_dict_lowercases_romanized_side():
    pairs = [("घ", "GHA"), ("घ", "Gha")]
    result = build_translit_dict(pairs)
    assert result["घ"] == "gha"
    assert result["घ"].islower()


def test_build_translit_dict_is_deterministic():
    pairs = [("च", "cha"), ("च", "cha"), ("च", "chha"), ("छ", "chh")]
    assert build_translit_dict(pairs) == build_translit_dict(pairs)


def test_verify_translit_quality_yes_when_romanization_matches_exactly():
    translit_dict = {"दोस्त": "dost"}
    rows = verify_translit_quality(translit_dict)
    row = next(r for r in rows if r["expected_existing_romanization"] == "dost")
    assert row["match"] == "yes"
    assert row["devanagari_matched"] == "दोस्त"


def test_verify_translit_quality_close_when_only_vowel_length_folding_differs():
    # normalize.py folds "aa"->"a", so "baris" (from dict) vs "barish"
    # (fold("baarish")) still differ by "sh"/"s" — real fixture: use a word
    # whose ONLY difference from the existing spelling is aa/ee/oo folding.
    translit_dict = {"रात": "rat"}  # existing "raat" folds aa->a to "rat"
    rows = verify_translit_quality(translit_dict)
    row = next(r for r in rows if r["expected_existing_romanization"] == "raat")
    assert row["match"] == "close"


def test_verify_translit_quality_no_when_devanagari_missing_from_dict():
    rows = verify_translit_quality({})
    row = next(r for r in rows if r["expected_existing_romanization"] == "dost")
    assert row["match"] == "no"
    assert row["devanagari_matched"] is None
    assert row["dict_romanization"] is None


def test_verify_translit_quality_covers_all_configured_words():
    from evals.finetune.fetch_corpus_data import VERIFICATION_WORDS

    rows = verify_translit_quality({})
    assert len(rows) == len(VERIFICATION_WORDS)
