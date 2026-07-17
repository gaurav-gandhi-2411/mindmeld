from __future__ import annotations

"""
No-leakage guarantee for assembled training data (evals/finetune/assemble_data.py).

Reads the already-assembled JSONL files (produced by a prior `uv run python
-m evals.finetune.assemble_data` run) rather than re-running the full
pipeline (which calls a local LLM and takes tens of minutes) — this test's
job is to catch a REGRESSION in the leakage guard, not to regenerate data.
Self-skips if the data hasn't been assembled yet in this environment.
"""

import json

import pytest

from evals.finetune.assemble_data import DATA_DIR
from evals.finetune.split import load_split


def _held_out():
    split = load_split()
    return {w.lower() for w in split["held_out_secrets"]} | {
        w.lower() for w in split["held_out_en_translations"]
    }


def _require_assembled_data():
    mnrl_path = DATA_DIR / "train_mnrl_pairs.jsonl"
    graded_path = DATA_DIR / "train_graded_pairs.jsonl"
    if not (mnrl_path.exists() and graded_path.exists()):
        pytest.skip("training data not assembled — run `python -m evals.finetune.assemble_data`")
    return mnrl_path, graded_path


def test_mnrl_pairs_contain_no_held_out_secret():
    mnrl_path, _ = _require_assembled_data()
    held_out = _held_out()
    for line in mnrl_path.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        assert rec["anchor"].lower() not in held_out, f"leakage: {rec}"
        assert rec["positive"].lower() not in held_out, f"leakage: {rec}"


def test_graded_pairs_contain_no_held_out_secret():
    _, graded_path = _require_assembled_data()
    held_out = _held_out()
    for line in graded_path.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        assert rec["sentence1"].lower() not in held_out, f"leakage: {rec}"
        assert rec["sentence2"].lower() not in held_out, f"leakage: {rec}"


def test_graded_pair_scores_in_unit_range():
    _, graded_path = _require_assembled_data()
    for line in graded_path.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        assert 0.0 <= rec["score"] <= 1.0
