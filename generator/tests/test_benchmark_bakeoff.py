from __future__ import annotations

"""
Unit tests for the NEW pure logic in evals/finetune/benchmark_bakeoff.py
(spec-hinglish-benchmark.md Phase 1b comparative bake-off): the near/far
separation metric, the combined dim1/dim2 record-merging helpers, checkpoint
validity checking, and comparison-table rendering.

Deliberately does NOT exercise `evaluate_one_model`/`run_model` (they load a
real SentenceTransformer checkpoint over the network) -- matching this
codebase's existing convention that model-invocation eval code
(eval_model.py, dimension1_ranking.py) has no dedicated unit tests and is
instead validated via the full eval run + its own report. Everything here
is model-free and runs in milliseconds.
"""

import json

from evals.finetune.benchmark_bakeoff import (
    _load_valid_checkpoint,
    _slug,
    build_comparison,
    checkpoint_path,
    combined_dim2_pairs,
    load_combined_dim1_scenarios,
    near_far_separation,
)


def test_near_far_separation_perfect_ordering():
    """far-tier words ranked strictly farther than near-tier words -> large
    positive separation."""
    vocab_size = 100
    records = [
        {"tier": "near", "actual_rank": 2},
        {"tier": "near", "actual_rank": 4},
        {"tier": "mid", "actual_rank": 40},
        {"tier": "far", "actual_rank": 90},
        {"tier": "far", "actual_rank": 96},
    ]
    sep = near_far_separation(records, vocab_size)
    # near mean pct = (0.02 + 0.04) / 2 = 0.03; far mean pct = (0.90+0.96)/2 = 0.93
    assert sep is not None
    assert abs(sep - 0.90) < 1e-9


def test_near_far_separation_inverted_ordering_is_negative():
    """near-tier words ranked farther than far-tier words -> negative
    separation (the model is actively backwards)."""
    vocab_size = 100
    records = [
        {"tier": "near", "actual_rank": 90},
        {"tier": "far", "actual_rank": 5},
    ]
    sep = near_far_separation(records, vocab_size)
    assert sep is not None
    assert sep < 0


def test_near_far_separation_skips_unresolved_records():
    vocab_size = 100
    records = [
        {"tier": "near", "actual_rank": None},  # unresolved, must be skipped
        {"tier": "near", "actual_rank": 10},
        {"tier": "far", "actual_rank": None},
        {"tier": "far", "actual_rank": 80},
    ]
    sep = near_far_separation(records, vocab_size)
    assert sep is not None
    assert abs(sep - 0.70) < 1e-9


def test_near_far_separation_none_when_tier_missing():
    vocab_size = 100
    records = [{"tier": "near", "actual_rank": 10}, {"tier": "mid", "actual_rank": 50}]
    assert near_far_separation(records, vocab_size) is None
    assert near_far_separation([], vocab_size) is None


def test_load_combined_dim1_scenarios_matches_known_counts():
    """Empirically verified counts (see module docstring): 8 production
    secrets/73 scenarios + 34 supplement secrets/306 scenarios = 42
    secrets/379 scenarios, when filtered to the full expanded test_secrets
    set."""
    from evals.finetune.split import load_split

    test_secrets = set(load_split()["test_secrets"])
    scenarios = load_combined_dim1_scenarios(test_secrets)
    secrets = {r["secret"] for r in scenarios}
    assert len(scenarios) == 379
    assert len(secrets) == 42
    assert secrets <= test_secrets


def test_load_combined_dim1_scenarios_filters_out_non_test_secrets():
    scenarios = load_combined_dim1_scenarios(set())
    assert scenarios == []


def test_combined_dim2_pairs_matches_split_json_test_pairs():
    """Reconstructed union must be set-identical to split.json's own
    precomputed test_pairs field (build_split_with_supplement() computes
    the same union) -- this is the cross-check the module docstring
    promises."""
    from evals.finetune.split import load_split

    split = load_split()
    test_secrets = set(split["test_secrets"])
    pairs = combined_dim2_pairs(test_secrets)
    assert len(pairs) == 50
    assert len(pairs) == len(set(pairs))
    assert set(pairs) == {tuple(p) for p in split["test_pairs"]}


def test_combined_dim2_pairs_empty_when_no_test_secrets():
    assert combined_dim2_pairs(set()) == []


def test_slug_and_checkpoint_path_are_filesystem_safe():
    slug = _slug("BAAI/bge-m3")
    assert "/" not in slug
    assert slug == "BAAI__bge-m3"
    path = checkpoint_path("BAAI/bge-m3")
    assert path.name == "BAAI__bge-m3.json"


def test_load_valid_checkpoint_missing_file_returns_none(tmp_path, monkeypatch):
    import evals.finetune.benchmark_bakeoff as bakeoff

    monkeypatch.setattr(bakeoff, "RAW_DIR", tmp_path)
    assert _load_valid_checkpoint("nonexistent/model") is None


def test_load_valid_checkpoint_corrupt_json_returns_none(tmp_path, monkeypatch):
    import evals.finetune.benchmark_bakeoff as bakeoff

    monkeypatch.setattr(bakeoff, "RAW_DIR", tmp_path)
    (tmp_path / "broken__model.json").write_text("{not valid json", encoding="utf-8")
    assert _load_valid_checkpoint("broken/model") is None


def test_load_valid_checkpoint_missing_required_key_returns_none(tmp_path, monkeypatch):
    import evals.finetune.benchmark_bakeoff as bakeoff

    monkeypatch.setattr(bakeoff, "RAW_DIR", tmp_path)
    (tmp_path / "incomplete__model.json").write_text(
        json.dumps({"model": "incomplete/model"}), encoding="utf-8"
    )
    assert _load_valid_checkpoint("incomplete/model") is None


def test_load_valid_checkpoint_well_formed_round_trips(tmp_path, monkeypatch):
    import evals.finetune.benchmark_bakeoff as bakeoff

    monkeypatch.setattr(bakeoff, "RAW_DIR", tmp_path)
    payload = {k: None for k in bakeoff.REQUIRED_CHECKPOINT_KEYS}
    payload["model"] = "ok/model"
    (tmp_path / "ok__model.json").write_text(json.dumps(payload), encoding="utf-8")
    loaded = _load_valid_checkpoint("ok/model")
    assert loaded is not None
    assert loaded["model"] == "ok/model"


def _fake_result(model: str, spearman: float, pass_rate: float, sep: float) -> dict:
    """Minimal synthetic per-model result shaped like evaluate_one_model's
    output, enough to drive build_comparison() without any real model call."""
    dim1_records = [
        {"secret": "s1", "tier": "near", "actual_rank": 1},
        {"secret": "s1", "tier": "far", "actual_rank": 90},
    ]
    dim2_records = [
        {"en_secret": "en1", "hien_secret": "hi1", "consistent": True, "resolution_error": None},
        {"en_secret": "en2", "hien_secret": "hi2", "consistent": False, "resolution_error": None},
    ]
    return {
        "model": model,
        "n_dim1_secrets": 1,
        "n_dim1_scenarios": 2,
        "n_dim2_pairs": 2,
        "dim1_spearman_ci": {"point": spearman, "ci_95": [spearman - 0.1, spearman + 0.1]},
        "dim2_pass_rate_ci": {"point": pass_rate, "ci_95": [pass_rate - 0.1, pass_rate + 0.1]},
        "band_accuracy": {"overall": 0.8, "near": 0.9, "mid": 0.7, "far": 0.85},
        "near_far_separation": sep,
        "dim1_records": dim1_records,
        "dim2_records": dim2_records,
    }


def test_build_comparison_shipped_row_has_em_dash_delta():
    from evals.finetune.benchmark_bakeoff import SHIPPED_MODEL

    results = {SHIPPED_MODEL: _fake_result(SHIPPED_MODEL, 0.7, 0.8, 0.5)}
    table_md, summary = build_comparison(results)
    assert "—" in table_md
    assert summary["shipped_model"] == SHIPPED_MODEL
    assert summary["paired_deltas_vs_shipped"] == {}


def test_build_comparison_reports_failed_model_without_dropping_it():
    from evals.finetune.benchmark_bakeoff import CANDIDATE_MODELS, SHIPPED_MODEL

    other = next(m for m in CANDIDATE_MODELS if m != SHIPPED_MODEL)
    results = {
        SHIPPED_MODEL: _fake_result(SHIPPED_MODEL, 0.7, 0.8, 0.5),
        other: {"model": other, "error": "OSError: could not download"},
    }
    table_md, _summary = build_comparison(results)
    assert other in table_md
    assert "FAILED" in table_md
    assert "could not download" in table_md


def test_build_comparison_computes_paired_delta_for_successful_candidate():
    from evals.finetune.benchmark_bakeoff import CANDIDATE_MODELS, SHIPPED_MODEL

    other = next(m for m in CANDIDATE_MODELS if m != SHIPPED_MODEL)
    results = {
        SHIPPED_MODEL: _fake_result(SHIPPED_MODEL, 0.7, 0.8, 0.5),
        other: _fake_result(other, 0.5, 0.6, 0.3),
    }
    _table_md, summary = build_comparison(results)
    assert other in summary["paired_deltas_vs_shipped"]
    delta = summary["paired_deltas_vs_shipped"][other]
    assert "dim1" in delta and "dim2" in delta
    assert set(delta["dim1"]) >= {"delta_point", "delta_ci_95", "ci_significant_improvement"}
