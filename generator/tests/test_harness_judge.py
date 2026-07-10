from __future__ import annotations

"""
Dimension 3 (local LLM-as-judge) CI gate — separate from test_harness.py
because it needs `ollama serve` + `qwen3:8b` pulled locally, which most CI
runners and dev machines won't have by default. Self-skips with an explicit
install/run message rather than silently passing or failing the whole suite
— see spec-eval-harness.md's "if the judge isn't available, tell me what to
install/run" requirement.

Only runs the (cheap, ~30-second) calibration set here, not the full
~220-clue judge pass (that's the baseline-report generator's job, run
on-demand via `uv run python -m evals.harness.report`) — a per-test-run
gate should be fast, not a multi-minute LLM batch job.
"""

import pytest

from evals.harness.judge_client import is_judge_available

_JUDGE_AVAILABLE = is_judge_available()
_SKIP_REASON = (
    "Local Ollama judge not reachable at http://localhost:11434. To run this "
    "gate: install Ollama (https://ollama.com), run `ollama serve` in a "
    "separate terminal, then `ollama pull qwen3:8b`."
)


@pytest.fixture(scope="module")
def calibration():
    from evals.harness.dimension3_judge import run_calibration

    return run_calibration()


@pytest.mark.skipif(not _JUDGE_AVAILABLE, reason=_SKIP_REASON)
def test_judge_spoiler_calibration_floor(calibration):
    # Baseline measured 96.9% (31/32) after isolating the spoiler-check
    # prompt (see judge_client.py's module docstring for why compound
    # prompts silently failed this check).
    assert calibration["spoiler_agreement"] >= 0.85


@pytest.mark.skipif(not _JUDGE_AVAILABLE, reason=_SKIP_REASON)
def test_judge_solvability_calibration_floor(calibration):
    # See baseline_report.md for the measured value — solvability agreement
    # is the weaker of the two calibrated axes (the judge tends to be
    # lenient on clearly-mismatched clue/secret pairs). Floor set at the
    # measured baseline minus a small buffer.
    assert calibration["solvability_agreement"] >= 0.55
