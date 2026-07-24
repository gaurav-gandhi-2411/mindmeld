from __future__ import annotations

"""
Unit tests for the pure (non-judge-dependent) logic backing the
spec-model-excellence.md WORKSTREAM B failure-analysis modules:
  - evals.finetune.frequency_buckets (item 6 — vocab-origin reconstruction,
    tertile bucket assignment, per-bucket join/report aggregation)
  - evals.finetune.failure_taxonomy (item 5 — prompt building, prevalence
    aggregation, sanity-check comparison, low-confidence flagging)
  - evals.finetune.domain_pos_breakdown (item 7 — domain join/report,
    unique-word extraction, POS/concreteness join/report aggregation)

The LLM-judge calls themselves are NOT tested here — same convention as
this repo's other judge-backed modules (see tests/test_harness_judge.py,
which only exercises the (non-LLM) availability probe / calibration
skip-gate, never mocks or asserts on judge output shape).
"""

import json
from pathlib import Path

import pytest

from evals.finetune.domain_pos_breakdown import (
    concreteness_report,
    domain_report,
    join_domain,
    join_pos_concreteness,
    pos_report,
    secret_domain_map,
    unique_words,
)
from evals.finetune.failure_taxonomy import (
    BAND_NAMES,
    band_rank_range,
    build_prompt,
    classify_record,
    collision_scan_crossref,
    inconsistent_rationale_flags,
    load_collision_flagged_secrets,
    low_confidence_flags,
    prevalence_table,
    sanity_check_worked_examples,
    tier_band_width_report,
)
from evals.finetune.frequency_buckets import (
    bucket_report,
    english_rank_map,
    hien_vocab_origin,
    hinglish_sourced_words,
    join_dim1_with_buckets,
    tertile_bucket,
    unresolved_coverage_stats,
)

# ---------------------------------------------------------------------------
# frequency_buckets — vocab-origin reconstruction
# ---------------------------------------------------------------------------


class TestHinglishSourcedWords:
    def test_basic_extraction(self, tmp_path: Path) -> None:
        fp = tmp_path / "hinglish.txt"
        fp.write_text("dost\tfriend\nyaar\tbuddy\n", encoding="utf-8")
        words = hinglish_sourced_words(fp, combined_profanity=frozenset())
        assert words == ["dost", "yaar"]

    def test_dedup_keeps_first_occurrence(self, tmp_path: Path) -> None:
        fp = tmp_path / "hinglish.txt"
        fp.write_text("dost\tfriend\ndost\tpal\n", encoding="utf-8")
        words = hinglish_sourced_words(fp, combined_profanity=frozenset())
        assert words == ["dost"]

    def test_profanity_excluded(self, tmp_path: Path) -> None:
        fp = tmp_path / "hinglish.txt"
        fp.write_text("dost\tfriend\nbadword\tslur\n", encoding="utf-8")
        words = hinglish_sourced_words(fp, combined_profanity=frozenset(["badword"]))
        assert words == ["dost"]

    def test_order_preserved(self, tmp_path: Path) -> None:
        fp = tmp_path / "hinglish.txt"
        fp.write_text("zeta\ta\nalpha\tb\nmid\tc\n", encoding="utf-8")
        words = hinglish_sourced_words(fp, combined_profanity=frozenset())
        assert words == ["zeta", "alpha", "mid"]


class TestHienVocabOrigin:
    def test_splits_hinglish_vs_english(self) -> None:
        vocab = ["dost", "cat", "yaar", "dog"]
        hi_words = ["dost", "yaar"]
        origin = hien_vocab_origin(vocab, hi_words)
        assert origin == {
            "dost": "hinglish",
            "cat": "english",
            "yaar": "hinglish",
            "dog": "english",
        }

    def test_empty_hinglish_all_english(self) -> None:
        vocab = ["cat", "dog"]
        origin = hien_vocab_origin(vocab, [])
        assert all(v == "english" for v in origin.values())


class TestEnglishRankMap:
    def test_one_based_rank_order_preserved(self) -> None:
        en_vocab = ["the", "of", "and"]
        ranks = english_rank_map(en_vocab)
        assert ranks == {"the": 1, "of": 2, "and": 3}

    def test_empty_vocab(self) -> None:
        assert english_rank_map([]) == {}


class TestTertileBucket:
    def test_first_third_is_head(self) -> None:
        assert tertile_bucket(1, 9) == "head"
        assert tertile_bucket(3, 9) == "head"

    def test_middle_third_is_mid(self) -> None:
        assert tertile_bucket(4, 9) == "mid"
        assert tertile_bucket(6, 9) == "mid"

    def test_last_third_is_tail(self) -> None:
        assert tertile_bucket(7, 9) == "tail"
        assert tertile_bucket(9, 9) == "tail"

    def test_single_item_population(self) -> None:
        assert tertile_bucket(1, 1) == "head"

    def test_rank_out_of_bounds_raises(self) -> None:
        with pytest.raises(ValueError, match="out of bounds"):
            tertile_bucket(0, 9)
        with pytest.raises(ValueError, match="out of bounds"):
            tertile_bucket(10, 9)

    def test_zero_population_raises(self) -> None:
        with pytest.raises(ValueError, match="out of bounds"):
            tertile_bucket(1, 0)


class TestUnresolvedCoverageStats:
    def test_counts_unresolved_fraction(self) -> None:
        table = {
            "a": {"origin": "hinglish", "bucket": "head", "frequency_rank_or_value": 0.01},
            "b": {"origin": "hinglish", "bucket": "unresolved", "frequency_rank_or_value": 0.0},
            "c": {"origin": "hinglish", "bucket": "unresolved", "frequency_rank_or_value": None},
            "d": {"origin": "english", "bucket": "head", "frequency_rank_or_value": 1},
        }
        stats = unresolved_coverage_stats(table, ["a", "b", "c"])
        assert stats["n_hinglish_words"] == 3
        assert stats["n_unresolved"] == 2
        assert stats["pct_unresolved"] == pytest.approx(2 / 3)
        assert stats["unresolved_words"] == ["b", "c"]


class TestJoinAndBucketReport:
    def _bucket_table(self) -> dict[str, dict]:
        return {
            "near1": {"origin": "english", "bucket": "head", "frequency_rank_or_value": 5},
            "far1": {"origin": "english", "bucket": "tail", "frequency_rank_or_value": 9000},
            "hi1": {"origin": "hinglish", "bucket": "unresolved", "frequency_rank_or_value": None},
        }

    def test_join_attaches_origin_and_bucket(self) -> None:
        records = [
            {"word": "near1", "secret": "s", "actual_rank": 10, "in_expected_band": True},
            {"word": "far1", "secret": "s", "actual_rank": 9000, "in_expected_band": False},
        ]
        joined = join_dim1_with_buckets(records, self._bucket_table())
        assert joined[0]["freq_origin"] == "english"
        assert joined[0]["freq_bucket"] == "head"
        assert joined[1]["freq_bucket"] == "tail"

    def test_join_missing_word_yields_none(self) -> None:
        records = [{"word": "unknown", "secret": "s", "actual_rank": 1, "in_expected_band": True}]
        joined = join_dim1_with_buckets(records, self._bucket_table())
        assert joined[0]["freq_origin"] is None
        assert joined[0]["freq_bucket"] is None

    def test_bucket_report_computes_rate_and_tail_penalty(self) -> None:
        # head bucket: 2/2 in_expected_band; tail bucket: 0/2 in_expected_band
        # -> tail penalty should be exactly 1.0 (perfect head, zero tail).
        records = [
            {"word": "h1", "secret": "s", "actual_rank": 1, "in_expected_band": True},
            {"word": "h2", "secret": "s", "actual_rank": 2, "in_expected_band": True},
            {"word": "t1", "secret": "s", "actual_rank": 9000, "in_expected_band": False},
            {"word": "t2", "secret": "s", "actual_rank": 9001, "in_expected_band": False},
        ]
        table = {
            "h1": {"origin": "english", "bucket": "head", "frequency_rank_or_value": 1},
            "h2": {"origin": "english", "bucket": "head", "frequency_rank_or_value": 2},
            "t1": {"origin": "english", "bucket": "tail", "frequency_rank_or_value": 9000},
            "t2": {"origin": "english", "bucket": "tail", "frequency_rank_or_value": 9001},
        }
        joined = join_dim1_with_buckets(records, table)
        report = bucket_report(joined, vocab_size=10000)
        assert report["combined"]["head"]["n"] == 2
        assert report["combined"]["head"]["in_expected_band_rate"] == 1.0
        assert report["combined"]["tail"]["in_expected_band_rate"] == 0.0
        assert report["tail_penalty_head_minus_tail_rate"] == 1.0

    def test_bucket_report_skips_unresolved_actual_rank(self) -> None:
        records = [{"word": "x", "secret": "s", "actual_rank": None, "in_expected_band": False}]
        table = {"x": {"origin": "english", "bucket": "head", "frequency_rank_or_value": 1}}
        joined = join_dim1_with_buckets(records, table)
        report = bucket_report(joined, vocab_size=10000)
        assert report["n_records_resolved"] == 0


# ---------------------------------------------------------------------------
# failure_taxonomy — prompt building + aggregation
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    def _record(self) -> dict:
        return {
            "secret": "bachpan",
            "word": "innocence",
            "tier": "mid",
            "subtype": None,
            "expected_bands": [3],
            "actual_band": 5,
            "actual_rank": 3739,
            "note": None,
        }

    def test_prompt_contains_key_fields(self) -> None:
        prompt = build_prompt(self._record())
        assert "bachpan" in prompt
        assert "innocence" in prompt
        assert "3739" in prompt
        assert BAND_NAMES[5] in prompt  # "freezing"
        assert BAND_NAMES[3] in prompt  # "warm" (expected band)

    def test_prompt_includes_note_when_present(self) -> None:
        rec = self._record()
        rec["note"] = "special case"
        prompt = build_prompt(rec)
        assert "special case" in prompt

    def test_prompt_omits_note_when_absent(self) -> None:
        prompt = build_prompt(self._record())
        assert "Note:" not in prompt


class TestClassifyRecordVocabGap:
    def test_unresolved_record_short_circuits_without_judge_call(self) -> None:
        # No Ollama call should happen here -- actual_rank is None means
        # there's no "actual placement" for the judge to explain.
        record = {
            "secret": "basti",
            "word": "migrant",
            "tier": "mid",
            "subtype": None,
            "expected_bands": [3],
            "actual_band": None,
            "actual_rank": None,
            "note": None,
            "resolution_error": "secret='basti' or word='migrant' not in vocab",
        }
        result = classify_record(record)
        assert result["category"] == "vocab_resolution_gap"
        assert "not in vocab" in result["rationale"]
        assert result["confidence"] == 5


class TestPrevalenceTable:
    def test_counts_and_percentages(self) -> None:
        classified = [
            {"category": "genuine_semantic_difficulty"},
            {"category": "genuine_semantic_difficulty"},
            {"category": "label_error"},
        ]
        table = prevalence_table(classified)
        assert table["genuine_semantic_difficulty"]["n"] == 2
        assert table["genuine_semantic_difficulty"]["pct"] == pytest.approx(2 / 3)
        assert table["label_error"]["n"] == 1

    def test_empty_input(self) -> None:
        assert prevalence_table([]) == {}


class TestSanityCheckWorkedExamples:
    def test_agreement_flagged_correctly(self) -> None:
        classified = [
            {
                "secret": "bachpan",
                "word": "innocence",
                "category": "genuine_semantic_difficulty",
                "rationale": "abstract association",
            },
            {
                "secret": "chaand",
                "word": "satellite",
                "category": "label_error",  # deliberately WRONG vs GG's anchor label
                "rationale": "disagreeing case",
            },
        ]
        result = sanity_check_worked_examples(classified)
        by_word = {r["word"]: r for r in result}
        assert by_word["innocence"]["agree"] is True
        assert by_word["satellite"]["agree"] is False

    def test_missing_record_reported_as_error(self) -> None:
        result = sanity_check_worked_examples([])
        assert all("error" in r for r in result)


class TestBandRankRange:
    def test_win_band_is_rank_one_only(self) -> None:
        assert band_rank_range(0, 10495) == (1, 1)

    def test_warm_band_matches_known_window(self) -> None:
        # Hand-verified against rival.band_for_rank for vocab_size=10495 AFTER
        # the warm-floor fix (PLAN.md checkpoint, docs/known-limitations.md
        # #18): warm = rank <= max(900, n*0.05) = max(900, 524) = 900,
        # hot = rank <= max(500, n*0.01) = 500 -> warm band is ranks 501-900,
        # a 400-rank window (was a 24-rank window pre-fix).
        assert band_rank_range(3, 10495) == (501, 900)

    def test_unreachable_band_raises(self) -> None:
        with pytest.raises(ValueError, match="never reached"):
            band_rank_range(99, 10495)


class TestTierBandWidthReport:
    def _record(self, tier: str, expected_bands: list[int], actual_rank, in_band: bool) -> dict:
        return {
            "tier": tier,
            "expected_bands": expected_bands,
            "actual_rank": actual_rank,
            "in_expected_band": in_band,
        }

    def test_mid_tier_target_window(self) -> None:
        # Post warm-floor-fix (PLAN.md checkpoint, docs/known-limitations.md
        # #18): mid's warm-band (3) window at vocab_size=10495 is now
        # ranks 501-900 (400 ranks), up from a pre-fix 24-rank sliver --
        # still narrower than near's, but no longer a near-dead band.
        records = [
            self._record("mid", [3], 600, False),
            self._record("mid", [3], 700, False),
            self._record("near", [1, 2], 10, True),
        ]
        report = tier_band_width_report(records, vocab_size=10495)
        assert report["mid"]["n"] == 2
        assert report["mid"]["in_expected_band_rate"] == 0.0
        assert report["mid"]["target_window_ranks"] == 400
        assert report["mid"]["target_window_pct_of_vocab"] == pytest.approx(400 / 10495)
        # near tier (bands scorching+hot, ranks 1-500) still has a wider window.
        assert report["near"]["target_window_ranks"] > report["mid"]["target_window_ranks"]

    def test_skips_unresolved_actual_rank_in_rate(self) -> None:
        records = [self._record("mid", [3], None, False)]
        report = tier_band_width_report(records, vocab_size=10495)
        assert report["mid"]["n_resolved"] == 0
        assert report["mid"]["in_expected_band_rate"] is None


class TestLowConfidenceFlags:
    def test_filters_below_threshold(self) -> None:
        classified = [
            {"confidence": 1},
            {"confidence": 4},
            {"confidence": 2},
        ]
        flagged = low_confidence_flags(classified, threshold=2)
        assert len(flagged) == 2
        assert all(r["confidence"] <= 2 for r in flagged)


class TestLoadCollisionFlaggedSecrets:
    def test_returns_none_when_report_absent(self, tmp_path: Path) -> None:
        assert load_collision_flagged_secrets(tmp_path / "missing.json") is None

    def test_filters_by_threshold(self, tmp_path: Path) -> None:
        report = {
            "threshold": 0.2,
            "full_scan": [
                {"word": "sandook", "collision_score": 0.667},
                {"word": "dost", "collision_score": 0.05},
            ],
        }
        fp = tmp_path / "collision_scan_report.json"
        fp.write_text(json.dumps(report), encoding="utf-8")
        flagged = load_collision_flagged_secrets(fp)
        assert flagged == {"sandook"}


class TestCollisionScanCrossref:
    def test_splits_flagged_vs_unflagged_and_tallies_categories(self) -> None:
        classified = [
            {"secret": "sandook", "word": "vault", "category": "transliteration_artifact"},
            {"secret": "sandook", "word": "chest", "category": "genuine_semantic_difficulty"},
            {"secret": "bachpan", "word": "innocence", "category": "genuine_semantic_difficulty"},
        ]
        result = collision_scan_crossref(classified, flagged_secrets={"sandook"})
        assert result["n_failing_records_with_collision_flagged_secret"] == 2
        assert result["n_failing_records_total"] == 3
        assert result["pct_failing_records_with_collision_flagged_secret"] == pytest.approx(2 / 3)
        assert result["category_breakdown_flagged_secrets"]["transliteration_artifact"]["n"] == 1
        assert (
            result["category_breakdown_unflagged_secrets"]["genuine_semantic_difficulty"]["n"] == 1
        )

    def test_empty_flagged_set_puts_everything_in_unflagged(self) -> None:
        classified = [{"secret": "bachpan", "word": "innocence", "category": "label_error"}]
        result = collision_scan_crossref(classified, flagged_secrets=set())
        assert result["n_failing_records_with_collision_flagged_secret"] == 0
        assert result["category_breakdown_unflagged_secrets"]["label_error"]["n"] == 1


class TestInconsistentRationaleFlags:
    def test_flags_hedged_rationale_despite_high_confidence(self) -> None:
        classified = [
            {"confidence": 4, "rationale": "may have caused an unusual association"},
            {"confidence": 5, "rationale": "a clear, direct semantic mismatch"},
        ]
        flagged = inconsistent_rationale_flags(classified)
        assert len(flagged) == 1
        assert "may have" in flagged[0]["rationale"]

    def test_no_flags_when_no_hedge_phrases(self) -> None:
        classified = [{"confidence": 3, "rationale": "a direct, unambiguous explanation"}]
        assert inconsistent_rationale_flags(classified) == []


# ---------------------------------------------------------------------------
# domain_pos_breakdown — domain join/report, POS/concreteness join/report
# ---------------------------------------------------------------------------


class TestSecretDomainMap:
    def test_real_supplement_pairs_present(self) -> None:
        domain_map = secret_domain_map()
        assert domain_map["registan"] == "nature"
        assert domain_map["mausi"] == "kinship"
        assert len(domain_map) == 34


class TestJoinDomain:
    def test_labeled_and_unlabeled_split(self) -> None:
        records = [
            {"secret": "registan", "actual_rank": 1, "in_expected_band": True},
            # original 25 production secrets carry no domain label.
            {"secret": "bachpan", "actual_rank": 1, "in_expected_band": True},
        ]
        joined = join_domain(records, {"registan": "nature"})
        assert joined[0]["domain"] == "nature"
        assert joined[0]["domain_labeled"] is True
        assert joined[1]["domain"] is None
        assert joined[1]["domain_labeled"] is False


class TestDomainReport:
    def test_per_domain_rate_and_unlabeled_caveat(self) -> None:
        records = [
            {
                "secret": "a",
                "actual_rank": 1,
                "in_expected_band": True,
                "domain": "nature",
                "domain_labeled": True,
            },
            {
                "secret": "b",
                "actual_rank": 1,
                "in_expected_band": False,
                "domain": "nature",
                "domain_labeled": True,
            },
            {
                "secret": "c",
                "actual_rank": 1,
                "in_expected_band": True,
                "domain": None,
                "domain_labeled": False,
            },
        ]
        report = domain_report(records)
        assert report["by_domain"]["nature"]["n"] == 2
        assert report["by_domain"]["nature"]["in_expected_band_rate"] == 0.5
        assert report["unlabeled"]["n"] == 1
        assert report["unlabeled"]["in_expected_band_rate"] == 1.0
        assert "caveat" in report["unlabeled"]


class TestUniqueWords:
    def test_dedup_and_sort(self) -> None:
        records = [{"word": "zeta"}, {"word": "alpha"}, {"word": "zeta"}]
        assert unique_words(records) == ["alpha", "zeta"]


def _pos_record(word: str, in_band: bool, pos: str, conc: str) -> dict:
    return {
        "word": word,
        "actual_rank": 1,
        "in_expected_band": in_band,
        "part_of_speech": pos,
        "concreteness": conc,
    }


class TestPosConcretenessReports:
    def test_pos_report_rate_per_pos(self) -> None:
        records = [
            _pos_record("cat", True, "noun", "concrete"),
            _pos_record("run", False, "verb", "concrete"),
        ]
        report = pos_report(records)
        assert report["noun"]["n"] == 1
        assert report["noun"]["in_expected_band_rate"] == 1.0
        assert report["verb"]["in_expected_band_rate"] == 0.0

    def test_concreteness_report_rate(self) -> None:
        records = [
            _pos_record("cat", True, "noun", "concrete"),
            _pos_record("freedom", False, "other", "abstract"),
        ]
        report = concreteness_report(records)
        assert report["concrete"]["n"] == 1
        assert report["abstract"]["in_expected_band_rate"] == 0.0

    def test_join_pos_concreteness_missing_word(self) -> None:
        records = [{"word": "unknown", "actual_rank": 1, "in_expected_band": True}]
        joined = join_pos_concreteness(records, {})
        assert joined[0]["part_of_speech"] is None
        assert joined[0]["concreteness"] is None
