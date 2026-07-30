from __future__ import annotations

"""
Unit tests for evals.finetune.probe_l2_collision_scan_extension's pure
helpers (spec-model-excellence.md WORKSTREAM B, item 8, Part 2): the paired
topheavy-metric bootstrap delta and the zero-topheavy-regression gate.
No model loading, no network calls, no candidate-patch file writes outside
a pytest tmp_path.
"""

from pathlib import Path

from evals.finetune.probe_l2_collision_scan_extension import (
    _no_topheavy_regression,
    paired_bootstrap_topheavy_delta,
    write_candidate_patch_file,
)

# Two secrets' worth of resolved dim1 records -- shape matches
# evals.harness.dimension1_ranking._resolve_actuals's output (only the
# fields topheavy.compute_topheavy_metrics actually reads are populated).
_BASE_RECORDS = [
    {"secret": "sec1", "word": "a", "tier": "near", "actual_rank": 1},
    {"secret": "sec1", "word": "b", "tier": "mid", "actual_rank": 5},
    {"secret": "sec1", "word": "c", "tier": "far", "actual_rank": 300},
    {"secret": "sec2", "word": "d", "tier": "near", "actual_rank": 2},
    {"secret": "sec2", "word": "e", "tier": "mid", "actual_rank": 8},
    {"secret": "sec2", "word": "f", "tier": "far", "actual_rank": 400},
]


class TestPairedBootstrapTopheavyDelta:
    def test_identical_baseline_and_candidate_gives_zero_delta(self) -> None:
        result = paired_bootstrap_topheavy_delta(_BASE_RECORDS, _BASE_RECORDS, n_boot=200)
        assert result["n_clusters"] == 2
        assert result["secret_mismatch"] is None
        for k in (10, 50, 100):
            leaf = result["ndcg"][k]
            assert leaf["delta_point"] == 0.0
            assert not leaf["ci_significant_improvement"]
            assert not leaf["ci_significant_regression"]

    def test_candidate_with_worse_ranks_shows_negative_delta(self) -> None:
        # Candidate buries sec1's near-tier word far away -- a real regression.
        worse = [dict(r) for r in _BASE_RECORDS]
        for r in worse:
            if r["secret"] == "sec1" and r["tier"] == "near":
                r["actual_rank"] = 5000
        result = paired_bootstrap_topheavy_delta(_BASE_RECORDS, worse, n_boot=200)
        assert result["mrr"]["delta_point"] < 0

    def test_secret_mismatch_reported_not_silently_dropped(self) -> None:
        extra_secret_records = _BASE_RECORDS + [
            {"secret": "sec3", "word": "g", "tier": "near", "actual_rank": 1}
        ]
        result = paired_bootstrap_topheavy_delta(_BASE_RECORDS, extra_secret_records, n_boot=50)
        assert result["secret_mismatch"] == ["sec3"]
        assert result["n_clusters"] == 2  # only the shared secrets are used


class TestNoTopheavyRegression:
    def test_all_non_regressing_passes(self) -> None:
        delta = {
            "ndcg": {k: {"ci_significant_regression": False} for k in (10, 50, 100)},
            "recall": {k: {"ci_significant_regression": False} for k in (10, 50, 100)},
            "precision": {k: {"ci_significant_regression": False} for k in (10, 50, 100)},
            "mrr": {"ci_significant_regression": False},
        }
        assert _no_topheavy_regression(delta) is True

    def test_one_regressing_submetric_fails(self) -> None:
        delta = {
            "ndcg": {k: {"ci_significant_regression": False} for k in (10, 50, 100)},
            "recall": {k: {"ci_significant_regression": False} for k in (10, 50, 100)},
            "precision": {
                10: {"ci_significant_regression": True},
                50: {"ci_significant_regression": False},
                100: {"ci_significant_regression": False},
            },
            "mrr": {"ci_significant_regression": False},
        }
        assert _no_topheavy_regression(delta) is False

    def test_mrr_regression_fails(self) -> None:
        delta = {
            "ndcg": {k: {"ci_significant_regression": False} for k in (10, 50, 100)},
            "recall": {k: {"ci_significant_regression": False} for k in (10, 50, 100)},
            "precision": {k: {"ci_significant_regression": False} for k in (10, 50, 100)},
            "mrr": {"ci_significant_regression": True},
        }
        assert _no_topheavy_regression(delta) is False


class TestWriteCandidatePatchFile:
    def test_writes_kv_format_never_touches_live_file(self, tmp_path: Path) -> None:
        out_path = tmp_path / "candidate.txt"
        write_candidate_patch_file({"junoon": "जुनून", "seedha": "सीधा"}, path=out_path)
        content = out_path.read_text(encoding="utf-8")
        assert "junoon: जुनून" in content
        assert "seedha: सीधा" in content
        assert "STAGING" in content
