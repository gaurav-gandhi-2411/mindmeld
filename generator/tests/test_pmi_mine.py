from __future__ import annotations

"""
Unit tests for the pure logic in evals/finetune/pmi_mine.py (PMI corpus-
relatedness staging pipeline). No network/Ollama/corpus-file dependency —
these test the PMI formula, score normalization, tokenization, fuzzy-snap,
and dict-tie-break/calibration helpers on toy in-memory inputs only.
"""

import math
from collections import Counter

import pytest

from evals.finetune.pmi_mine import (
    _chunks,
    build_romanized_to_devanagari_counts,
    compute_calibration,
    compute_pmi,
    fuzzy_snap,
    pick_best_devanagari,
    pmi_to_score,
    select_neighbors,
    tokenize,
)


def test_tokenize_strips_punctuation_and_ascii():
    assert tokenize("यह घर, बड़ा है।") == ["यह", "घर", "बड़ा", "है"]


def test_tokenize_drops_pure_ascii_tokens():
    assert tokenize("hello यह 123 दुनिया!") == ["यह", "दुनिया"]


def test_tokenize_empty_and_whitespace_only():
    assert tokenize("") == []
    assert tokenize("   ") == []
    assert tokenize("... !!! ,,,") == []


def test_compute_pmi_toy_counts():
    # p_xy=0.1, p_x=0.2, p_y=0.15 -> pmi = log2(0.1 / 0.03)
    pmi = compute_pmi(cooc_count=10, anchor_doc_freq=20, neighbor_doc_freq=15, n=100)
    assert pmi == pytest.approx(math.log2(0.1 / (0.2 * 0.15)))


def test_compute_pmi_independence_gives_zero():
    # anchor and neighbor each occur in exactly half the corpus, and co-occur
    # in exactly a quarter -> statistically independent -> PMI == 0.
    pmi = compute_pmi(cooc_count=25, anchor_doc_freq=50, neighbor_doc_freq=50, n=100)
    assert pmi == pytest.approx(0.0, abs=1e-9)


def test_compute_pmi_negative_association():
    # neighbor almost never co-occurs relative to its own frequency -> PMI < 0.
    pmi = compute_pmi(cooc_count=1, anchor_doc_freq=50, neighbor_doc_freq=50, n=100)
    assert pmi < 0


def test_select_neighbors_filters_and_ranks():
    doc_freq = Counter(
        {
            "anchor": 40,
            "strong": 12,  # passes min-freq, strongly associated
            "toofrequent": 40,  # exceeds MAX_NEIGHBOR_DOC_FREQ_FRAC * n (stopword-like)
            "toorare": 5,  # below MIN_NEIGHBOR_DOC_FREQ
            "weak": 20,  # passes freq bounds but PMI <= 0 (independent)
        }
    )
    n = 100
    cooc_counts = Counter(
        {
            "strong": 10,  # cooc/anchor=0.25, well above chance (0.12) -> PMI > 0
            "toofrequent": 20,  # would exceed the doc-freq cap even if cooc passes
            "toorare": 6,  # cooc passes MIN_COOC but neighbor_doc_freq below floor
            "weak": 8,  # cooc/n=0.08 vs p_x*p_y=0.4*0.2=0.08 -> independent, PMI==0
        }
    )
    result = select_neighbors("anchor", cooc_counts, doc_freq, n)
    kept = {r["neighbor_devanagari"] for r in result}
    assert kept == {"strong"}
    assert result[0]["cooc_count"] == 10


def test_select_neighbors_caps_at_top_k():
    n = 1000
    doc_freq = Counter({"anchor": 200})
    cooc_counts = Counter()
    # 12 neighbors, all comfortably passing every filter, with distinct PMI.
    for i in range(12):
        neighbor = f"n{i}"
        doc_freq[neighbor] = 20 + i
        cooc_counts[neighbor] = 20 - i  # decreasing cooc -> decreasing PMI
    result = select_neighbors("anchor", cooc_counts, doc_freq, n)
    assert len(result) == 8
    pmis = [r["pmi"] for r in result]
    assert pmis == sorted(pmis, reverse=True)


def test_pmi_to_score_maps_into_documented_range():
    assert pmi_to_score(1.0, pmi_min=0.0, pmi_max=2.0) == pytest.approx(0.45 + 0.5 * 0.35)
    assert pmi_to_score(0.0, pmi_min=0.0, pmi_max=2.0) == pytest.approx(0.45)
    assert pmi_to_score(2.0, pmi_min=0.0, pmi_max=2.0) == pytest.approx(0.80)


def test_pmi_to_score_degenerate_batch_returns_midpoint():
    assert pmi_to_score(3.0, pmi_min=3.0, pmi_max=3.0) == pytest.approx((0.45 + 0.80) / 2)


def test_pmi_to_score_never_leaves_documented_bounds():
    for pmi in (-5.0, 0.0, 0.5, 1.0, 1.5, 5.0):
        score = pmi_to_score(pmi, pmi_min=0.0, pmi_max=1.5)
        assert 0.45 <= score <= 0.80 or pmi < 0.0 or pmi > 1.5


def test_fuzzy_snap_already_canonical_no_snap():
    canonical = frozenset({"dost", "zindagi"})
    word, snapped = fuzzy_snap("dost", canonical)
    assert word == "dost"
    assert snapped is False


def test_fuzzy_snap_near_duplicate_snaps_to_canonical():
    canonical = frozenset({"zindagi", "dost"})
    word, snapped = fuzzy_snap("zinagi", canonical)
    assert word == "zindagi"
    assert snapped is True


def test_fuzzy_snap_no_match_returns_original_unchanged():
    canonical = frozenset({"zindagi", "dost"})
    word, snapped = fuzzy_snap("kela", canonical)
    assert word == "kela"
    assert snapped is False


def test_build_romanized_to_devanagari_counts_and_tie_break():
    pairs = [("देव", "dev"), ("दिव", "dev"), ("देव", "dev")]
    tally = build_romanized_to_devanagari_counts(pairs)
    assert tally["dev"] == Counter({"देव": 2, "दिव": 1})
    assert pick_best_devanagari(tally["dev"]) == "देव"


def test_pick_best_devanagari_tie_break_shortest_then_alpha():
    # equal frequency -> shortest string wins, then alphabetically first
    counts = Counter({"बबब": 1, "अ": 1})
    assert pick_best_devanagari(counts) == "अ"


def test_compute_calibration_reports_agreement_rate_honestly():
    dict_hit_devas = ["देव", "यार", "काम"]
    dict_rom = {"देव": "dev", "यार": "yaar", "काम": "kaam"}
    # "yar" folds to the same normalized form as "yaar" (aa->a); "dave" does not
    # match "dev"; "काम" has no LLM answer at all (missing from llm_rom).
    llm_rom = {"देव": "dave", "यार": "yar"}
    result = compute_calibration(dict_hit_devas, dict_rom, llm_rom)
    assert result["n_compared"] == 2
    assert result["n_agree"] == 1
    assert result["agreement_rate"] == pytest.approx(0.5)


def test_compute_calibration_empty_input_reports_none_rate():
    result = compute_calibration([], {}, {})
    assert result["n_compared"] == 0
    assert result["agreement_rate"] is None


def test_chunks_splits_and_preserves_order():
    items = [str(i) for i in range(7)]
    chunks = list(_chunks(items, 3))
    assert chunks == [["0", "1", "2"], ["3", "4", "5"], ["6"]]


def test_chunks_empty_input():
    assert list(_chunks([], 5)) == []
