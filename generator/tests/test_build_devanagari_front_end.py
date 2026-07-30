from __future__ import annotations

"""
Unit tests for the pure/orchestration logic in
evals/finetune/build_devanagari_front_end.py. No network/Ollama dependency --
pmi_mine.llm_devanagari_batch is monkeypatched with an in-memory fake so these
run offline and fast (mirrors tests/test_pmi_mine.py's no-network convention).
"""

import json

from evals.finetune import pmi_mine
from evals.finetune.build_devanagari_front_end import (
    load_checkpoint,
    merge_dict_hits,
    resolve_misses,
    resolve_misses_batch,
    save_checkpoint,
)


def test_save_and_load_checkpoint_round_trip(tmp_path):
    path = tmp_path / "checkpoint.json"
    table = {"dost": "दोस्त", "unknown": None}
    save_checkpoint(table, path)
    assert load_checkpoint(path) == table


def test_load_checkpoint_missing_file_returns_empty_dict(tmp_path):
    assert load_checkpoint(tmp_path / "nope.json") == {}


def test_merge_dict_hits_adds_new_entries_without_overwriting_checkpoint():
    checkpoint = {"dost": "दोस्त-stale"}  # simulates a prior partial run
    dict_hits = {"dost": "दोस्त", "ghar": "घर"}
    merged = merge_dict_hits(checkpoint, dict_hits)
    # existing checkpoint entry for a dict-hit word is left untouched
    assert merged["dost"] == "दोस्त-stale"
    # new dict-hit word is added
    assert merged["ghar"] == "घर"
    # original checkpoint dict is not mutated (merge returns a copy)
    assert checkpoint == {"dost": "दोस्त-stale"}


def test_resolve_misses_batch_resolves_all_on_first_attempt(monkeypatch):
    calls = []

    def fake_llm_devanagari_batch(words):
        calls.append(list(words))
        return {w: f"deva-{w}" for w in words}

    monkeypatch.setattr(pmi_mine, "llm_devanagari_batch", fake_llm_devanagari_batch)

    result = resolve_misses_batch(["alpha", "beta"], max_retries=1)
    assert result == {"alpha": "deva-alpha", "beta": "deva-beta"}
    assert len(calls) == 1  # no retry needed


def test_resolve_misses_batch_retries_only_unresolved_subset(monkeypatch):
    calls = []

    def fake_llm_devanagari_batch(words):
        calls.append(list(words))
        # first call only resolves "alpha"; "beta" is resolved on retry
        if len(calls) == 1:
            return {"alpha": "deva-alpha"}
        return {w: f"deva-{w}" for w in words}

    monkeypatch.setattr(pmi_mine, "llm_devanagari_batch", fake_llm_devanagari_batch)

    result = resolve_misses_batch(["alpha", "beta"], max_retries=1)
    assert result == {"alpha": "deva-alpha", "beta": "deva-beta"}
    assert calls == [["alpha", "beta"], ["beta"]]  # retry only re-sends "beta"


def test_resolve_misses_batch_marks_still_unresolved_as_none(monkeypatch):
    def always_fails(words):
        return {}

    monkeypatch.setattr(pmi_mine, "llm_devanagari_batch", always_fails)

    result = resolve_misses_batch(["alpha", "beta"], max_retries=1)
    assert result == {"alpha": None, "beta": None}


def test_resolve_misses_checkpoints_after_every_batch(monkeypatch, tmp_path):
    checkpoint_path = tmp_path / "checkpoint.json"
    saved_snapshots = []

    def fake_llm_devanagari_batch(words):
        return {w: f"deva-{w}" for w in words}

    monkeypatch.setattr(pmi_mine, "llm_devanagari_batch", fake_llm_devanagari_batch)
    monkeypatch.setattr(pmi_mine, "LLM_BATCH_SIZE", 2)  # force multiple small batches

    original_save = save_checkpoint

    def spying_save(table, path):
        original_save(table, path)
        saved_snapshots.append(json.loads(path.read_text(encoding="utf-8")))

    import evals.finetune.build_devanagari_front_end as bdfe

    monkeypatch.setattr(bdfe, "save_checkpoint", spying_save)

    misses = ["a", "b", "c", "d", "e"]
    result = bdfe.resolve_misses(misses, {}, checkpoint_path, batch_size=2)

    assert result == {w: f"deva-{w}" for w in misses}
    # 5 words / batch_size 2 -> 3 batches -> 3 checkpoint saves, each growing
    assert len(saved_snapshots) == 3
    assert len(saved_snapshots[0]) == 2
    assert len(saved_snapshots[1]) == 4
    assert len(saved_snapshots[2]) == 5
    # the on-disk file reflects the final, complete state
    assert load_checkpoint(checkpoint_path) == result


def test_resolve_misses_skips_words_already_in_checkpoint(monkeypatch, tmp_path):
    checkpoint_path = tmp_path / "checkpoint.json"
    calls = []

    def fake_llm_devanagari_batch(words):
        calls.append(list(words))
        return {w: f"deva-{w}" for w in words}

    monkeypatch.setattr(pmi_mine, "llm_devanagari_batch", fake_llm_devanagari_batch)

    existing_checkpoint = {"alpha": "deva-alpha"}  # simulates a resumed run
    result = resolve_misses(["alpha", "beta"], existing_checkpoint, checkpoint_path)

    assert result == {"alpha": "deva-alpha", "beta": "deva-beta"}
    assert calls == [["beta"]]  # "alpha" was never re-sent to the LLM


def test_resolve_misses_no_pending_work_is_a_noop(monkeypatch, tmp_path):
    checkpoint_path = tmp_path / "checkpoint.json"

    def should_not_be_called(words):
        raise AssertionError("llm_devanagari_batch should not be called when nothing is pending")

    monkeypatch.setattr(pmi_mine, "llm_devanagari_batch", should_not_be_called)

    checkpoint = {"alpha": "deva-alpha"}
    result = resolve_misses(["alpha"], checkpoint, checkpoint_path)
    assert result == checkpoint
