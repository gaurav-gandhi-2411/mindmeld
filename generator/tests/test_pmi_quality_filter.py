from __future__ import annotations

"""
Unit tests for the pure logic in evals/finetune/pmi_quality_filter.py (LLM-
judge quality filter for corpus PMI-mined pairs). No network/Ollama
dependency — these test chunking, prompt rendering, response parsing, the
fail-closed accept/reject decision, and stratified example sampling on toy
in-memory inputs only.
"""

from evals.finetune.pmi_quality_filter import (
    _chunks,
    build_pairs_block,
    parse_judge_batch_response,
    run_quality_filter,
    stratified_examples,
)


def test_chunks_splits_and_preserves_order():
    items = [{"i": i} for i in range(7)]
    chunks = _chunks(items, 3)
    assert chunks == [items[0:3], items[3:6], items[6:7]]


def test_chunks_empty_input():
    assert _chunks([], 5) == []


def test_chunks_exact_multiple():
    items = [{"i": i} for i in range(6)]
    chunks = _chunks(items, 3)
    assert len(chunks) == 2
    assert all(len(c) == 3 for c in chunks)


def test_build_pairs_block_renders_indexed_lines():
    batch = [{"anchor": "yaar", "neighbor": "dost"}, {"anchor": "kaam", "neighbor": "ui"}]
    block = build_pairs_block(batch)
    assert block == '0. anchor="yaar", neighbor="dost"\n1. anchor="kaam", neighbor="ui"'


def test_parse_judge_batch_response_happy_path():
    raw = [{"index": 0, "related_ok": True}, {"index": 1, "related_ok": False}]
    result = parse_judge_batch_response(raw, batch_size=2)
    assert result == {0: True, 1: False}


def test_parse_judge_batch_response_drops_out_of_range_index():
    raw = [{"index": 0, "related_ok": True}, {"index": 5, "related_ok": True}]
    result = parse_judge_batch_response(raw, batch_size=2)
    assert result == {0: True}


def test_parse_judge_batch_response_drops_malformed_entries():
    raw = [
        {"index": 0, "related_ok": True},
        {"index": "1", "related_ok": True},  # index not an int
        {"index": 2, "related_ok": "yes"},  # related_ok not a bool
        "not-a-dict",
        {"index": 3},  # missing related_ok
    ]
    result = parse_judge_batch_response(raw, batch_size=5)
    assert result == {0: True}


def test_parse_judge_batch_response_rejects_bool_as_index():
    # bool is a subclass of int in Python; index=True must not silently pass
    # isinstance(idx, int) and get treated as index 1.
    raw = [{"index": True, "related_ok": True}]
    result = parse_judge_batch_response(raw, batch_size=5)
    assert result == {}


def test_parse_judge_batch_response_non_list_returns_empty():
    assert parse_judge_batch_response({"index": 0, "related_ok": True}, batch_size=1) == {}
    assert parse_judge_batch_response(None, batch_size=1) == {}


def test_run_quality_filter_fail_closed_on_missing_judgment(monkeypatch):
    # judge_batch returns judgments only for even indices -> odd indices
    # (no judgment) must be rejected, not accepted.
    import evals.finetune.pmi_quality_filter as m

    def fake_judge_batch(batch: list[dict]) -> dict[int, bool]:
        return {i: True for i in range(len(batch)) if i % 2 == 0}

    monkeypatch.setattr(m, "judge_batch", fake_judge_batch)

    pairs = [{"anchor": f"a{i}", "neighbor": f"n{i}", "score": 0.5} for i in range(4)]
    accepted, rejected, stats = run_quality_filter(pairs, batch_size=4)

    assert [p["anchor"] for p in accepted] == ["a0", "a2"]
    assert [p["anchor"] for p in rejected] == ["a1", "a3"]
    assert stats["n_no_judgment_fail_closed"] == 2
    assert stats["n_input"] == 4
    assert stats["n_accepted"] == 2
    assert stats["n_rejected"] == 2


def test_run_quality_filter_all_rejected_on_ollama_failure(monkeypatch):
    import evals.finetune.pmi_quality_filter as m

    monkeypatch.setattr(m, "judge_batch", lambda batch: {})

    pairs = [{"anchor": "a", "neighbor": "b", "score": 0.5}]
    accepted, rejected, stats = run_quality_filter(pairs, batch_size=25)

    assert accepted == []
    assert rejected == pairs
    assert stats["n_no_judgment_fail_closed"] == 1


def test_stratified_examples_includes_low_and_high_band():
    records = (
        [{"anchor": f"lo{i}", "neighbor": "x", "score": 0.46} for i in range(5)]
        + [{"anchor": f"mid{i}", "neighbor": "x", "score": 0.60} for i in range(5)]
        + [{"anchor": f"hi{i}", "neighbor": "x", "score": 0.75} for i in range(5)]
    )
    sample = stratified_examples(records, n=9)
    scores = [r["score"] for r in sample]
    assert any(s <= 0.55 for s in scores), "expected at least one low-band example"
    assert any(s >= 0.70 for s in scores), "expected at least one high-band example"
    assert len(sample) == 9


def test_stratified_examples_deterministic_with_fixed_seed():
    records = [{"anchor": f"a{i}", "neighbor": "x", "score": 0.5 + i * 0.01} for i in range(20)]
    a = stratified_examples(records, n=6, seed=42)
    b = stratified_examples(records, n=6, seed=42)
    assert a == b


def test_stratified_examples_never_exceeds_available_records():
    records = [{"anchor": "a", "neighbor": "x", "score": 0.5}]
    sample = stratified_examples(records, n=15)
    assert sample == records


def test_stratified_examples_empty_input():
    assert stratified_examples([], n=15) == []
