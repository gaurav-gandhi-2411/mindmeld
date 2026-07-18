from __future__ import annotations

"""
Tests for evals/finetune/public_benchmark_analysis.py -- dev/test
correlation computation and shipped-model bootstrap-CI slicing. Uses
synthetic fixtures for the pure-function unit tests (fast, no disk I/O)
plus one integration test against the real split + whatever bake-off
checkpoints are actually on disk (self-adapting to however many of the 8
CANDIDATE_MODELS are available in this environment).
"""

from evals.finetune.public_benchmark_analysis import (
    _dev_test_scores_for_model,
    _filter_by_secret,
    dev_test_correlation,
    shipped_model_bootstrap_cis,
)
from evals.finetune.public_benchmark_split import load_split


def _fake_dim1_record(secret: str, tier: str, actual_rank: int) -> dict:
    return {
        "secret": secret,
        "word": f"{secret}_{tier}_word",
        "tier": tier,
        "expected_bands": [1, 2] if tier == "near" else [4, 5],
        "actual_rank": actual_rank,
        "resolution_error": None,
    }


def test_dev_test_scores_for_model_perfect_ranking_gives_positive_scores():
    # near-tier ranks lower (more related) than far-tier -- a "good" model.
    records = [
        _fake_dim1_record("dev_a", "near", 1),
        _fake_dim1_record("dev_a", "far", 100),
        _fake_dim1_record("dev_b", "near", 2),
        _fake_dim1_record("dev_b", "far", 200),
        _fake_dim1_record("test_a", "near", 3),
        _fake_dim1_record("test_a", "far", 300),
    ]
    result = _dev_test_scores_for_model(
        records, dev_secrets=["dev_a", "dev_b"], test_secrets=["test_a"]
    )
    assert result["dev_score"] > 0
    assert result["test_score"] > 0
    assert result["n_dev_secrets_resolved"] == 2
    assert result["n_test_secrets_resolved"] == 1


def test_dev_test_scores_for_model_ignores_unresolved_records():
    records = [
        _fake_dim1_record("dev_a", "near", 1),
        {**_fake_dim1_record("dev_a", "far", None), "actual_rank": None},
    ]
    result = _dev_test_scores_for_model(records, dev_secrets=["dev_a"], test_secrets=[])
    assert result["n_dev_secrets_resolved"] == 1


def test_filter_by_secret():
    records = [{"secret": "a", "v": 1}, {"secret": "b", "v": 2}, {"secret": "a", "v": 3}]
    filtered = _filter_by_secret(records, {"a"}, "secret")
    assert filtered == [{"secret": "a", "v": 1}, {"secret": "a", "v": 3}]


def test_dev_test_correlation_uses_available_checkpoints_only():
    split = load_split()
    result = dev_test_correlation(split)
    assert result["n_models_in_candidate_list"] == 8
    assert 0 <= result["n_models_used"] <= 8
    assert set(result["per_model_dev_test_scores"]) == set(result["models_used"])
    assert result["correlation_method"] == "pearson"
    assert result["old_n16_baseline_correlation"] == 0.12
    if result["n_models_used"] >= 3:
        assert isinstance(result["dev_test_pearson_r"], float)
        assert -1.0 <= result["dev_test_pearson_r"] <= 1.0
    else:
        assert result["dev_test_pearson_r"] is None


def test_shipped_model_bootstrap_ci_returns_none_or_expected_shape():
    split = load_split()
    result = shipped_model_bootstrap_cis(split)
    if result is None:
        return  # shipped-model checkpoint not on disk in this environment -- valid state
    assert set(result["dim1_spearman"]) == {"full_34", "dev_only", "test_only"}
    assert set(result["dim2_pass_rate"]) == {"full_34", "dev_only", "test_only"}
