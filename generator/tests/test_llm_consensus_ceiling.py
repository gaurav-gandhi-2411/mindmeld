from __future__ import annotations

"""
Unit tests for spec-metrics-ceiling-calibration.md WORKSTREAM 2's
evals/finetune/llm_consensus_ceiling.py. Per this task's own constraint,
these tests cover the DETERMINISTIC parts only -- blind order-randomisation
reproducibility, calibration-gate pass/fail logic, and sensitivity-analysis
arithmetic -- plus the wiring of self_consistency_vote/run_calibration_gate
against a STUBBED Ollama HTTP layer (urllib.request.urlopen is monkeypatched
module-wide; no real network calls are made in this test module). The
control-set builders (build_control_near/build_control_far) read real,
static, already-frozen benchmark JSON, so their determinism is exercised
directly too, without needing any LLM call.
"""

import json

import pytest

import evals.finetune.llm_consensus_ceiling as mod

# ---------------------------------------------------------------------------
# majority_vote
# ---------------------------------------------------------------------------


def test_majority_vote_clear_majority():
    assert mod.majority_vote(["near", "near", "far"]) == "near"


def test_majority_vote_unanimous():
    assert mod.majority_vote(["far", "far", "far"]) == "far"


def test_majority_vote_all_none_returns_none():
    assert mod.majority_vote([None, None, None]) is None


def test_majority_vote_drops_none_before_voting():
    assert mod.majority_vote(["near", None, "near"]) == "near"


def test_majority_vote_two_way_tie_resolves_to_mid():
    assert mod.majority_vote(["near", "far"]) == "mid"


def test_majority_vote_three_way_tie_resolves_to_mid():
    assert mod.majority_vote(["near", "mid", "far"]) == "mid"


def test_majority_vote_empty_list_returns_none():
    assert mod.majority_vote([]) is None


# ---------------------------------------------------------------------------
# Blind order-randomisation -- reproducibility given seed (spec step 2).
# ---------------------------------------------------------------------------


def test_secret_first_reproducible_given_same_seed():
    a = mod._secret_first("azaadi", "freedom", seed=42)
    b = mod._secret_first("azaadi", "freedom", seed=42)
    assert a == b


def test_secret_first_varies_across_distinct_pairs():
    # Not every pair should land on the same side of the coin flip -- a
    # constant-True or constant-False implementation would defeat the
    # point of order randomisation. Spot-check enough pairs to see both
    # outcomes at least once.
    outcomes = {
        mod._secret_first(f"secret{i}", f"word{i}", seed=42) for i in range(20)
    }
    assert outcomes == {True, False}


def test_build_prompt_is_blind_to_the_withheld_label():
    """build_prompt's output must depend ONLY on (secret, gloss, word,
    seed) -- never on item.label (the withheld benchmark tier / control
    expected-answer) -- otherwise the judge would see a hint of the
    answer. Verified by constructing two items identical except for
    `label` and asserting byte-identical prompts."""
    near_item = mod.JudgeItem(
        secret="azaadi", gloss="freedom", word="knives", domain="abstract", label="near"
    )
    far_item = mod.JudgeItem(
        secret="azaadi", gloss="freedom", word="knives", domain="abstract", label="far"
    )
    assert mod.build_prompt(near_item, seed=42) == mod.build_prompt(far_item, seed=42)


def test_shuffle_items_reproducible_given_same_seed():
    items = [
        mod.JudgeItem(secret=f"s{i}", gloss=f"g{i}", word=f"w{i}", domain="d", label="near")
        for i in range(10)
    ]
    a = mod._shuffle_items(items, seed=42)
    b = mod._shuffle_items(items, seed=42)
    assert [it.secret for it in a] == [it.secret for it in b]


def test_shuffle_items_is_not_identity_order():
    items = [
        mod.JudgeItem(secret=f"s{i}", gloss=f"g{i}", word=f"w{i}", domain="d", label="near")
        for i in range(10)
    ]
    shuffled = mod._shuffle_items(items, seed=42)
    assert [it.secret for it in shuffled] != [it.secret for it in items]
    assert {it.secret for it in shuffled} == {it.secret for it in items}


# ---------------------------------------------------------------------------
# Control-set construction -- deterministic, reads real frozen benchmark
# JSON, no network call.
# ---------------------------------------------------------------------------


def test_build_control_near_all_labelled_near_and_reproducible():
    a = mod.build_control_near(n=10)
    b = mod.build_control_near(n=10)
    assert [it.secret for it in a] == [it.secret for it in b]
    assert all(it.label == "near" for it in a)
    assert len(a) == 10


def test_build_control_near_respects_exclude():
    baseline = mod.build_control_near(n=5)
    exclude = frozenset({(baseline[0].secret, baseline[0].word)})
    excluded = mod.build_control_near(n=5, exclude=exclude)
    assert (baseline[0].secret, baseline[0].word) not in {(it.secret, it.word) for it in excluded}


def test_build_control_far_all_labelled_far_and_domain_disjoint():
    items = mod.build_control_far(n=10)
    assert all(it.label == "far" for it in items)
    domain_of = {h: d for h, _e, d in mod.BENCHMARK_SUPPLEMENT_PAIRS}
    word_domain_of = {e: d for _h, e, d in mod.BENCHMARK_SUPPLEMENT_PAIRS}
    for it in items:
        # every control-far pair is drawn cross-domain by construction
        assert domain_of[it.secret] != word_domain_of[it.word]


def test_build_control_far_never_reproduces_the_secrets_own_translation():
    gloss_of = {h: e for h, e, _d in mod.BENCHMARK_SUPPLEMENT_PAIRS}
    items = mod.build_control_far(n=20)
    assert all(it.word != gloss_of[it.secret] for it in items)


def test_build_control_far_reproducible_given_same_seed():
    a = mod.build_control_far(n=8, seed=999)
    b = mod.build_control_far(n=8, seed=999)
    assert [(it.secret, it.word) for it in a] == [(it.secret, it.word) for it in b]


# ---------------------------------------------------------------------------
# Calibration-gate pass/fail logic (spec step 4).
# ---------------------------------------------------------------------------


def _gate_result(qwen_acc: float, llama_acc: float) -> dict:
    return {
        "per_judge": {
            "qwen3:8b": {"accuracy": qwen_acc, "passed": qwen_acc >= mod.CALIBRATION_BAR},
            "llama3.1:8b": {"accuracy": llama_acc, "passed": llama_acc >= mod.CALIBRATION_BAR},
        }
    }


def test_calibration_verdict_both_pass():
    passed, msg = mod.calibration_verdict(_gate_result(0.95, 0.93))
    assert passed
    assert "passed" in msg.lower()


def test_calibration_verdict_one_fails_is_a_hard_blocker():
    passed, msg = mod.calibration_verdict(_gate_result(0.95, 0.50))
    assert not passed
    assert "HARD BLOCKER" in msg
    assert "llama3.1:8b" in msg
    assert "qwen3:8b" not in msg  # only the FAILING judge is named


def test_calibration_verdict_exactly_at_bar_passes():
    passed, _msg = mod.calibration_verdict(_gate_result(mod.CALIBRATION_BAR, mod.CALIBRATION_BAR))
    assert passed


def test_calibration_verdict_both_fail_names_both():
    passed, msg = mod.calibration_verdict(_gate_result(0.10, 0.20))
    assert not passed
    assert "qwen3:8b" in msg
    assert "llama3.1:8b" in msg


# ---------------------------------------------------------------------------
# Ceiling sensitivity-analysis arithmetic (spec steps 7-8).
# ---------------------------------------------------------------------------


def _per_item(status: str, benchmark_tier: str, consensus: str | None) -> dict:
    return {
        "secret": "s",
        "word": "w",
        "benchmark_tier": benchmark_tier,
        "status": status,
        "consensus": consensus,
        "qwen3:8b": consensus,
        "llama3.1:8b": consensus,
    }


def test_compute_ceiling_all_resolved_all_correct():
    per_item = [_per_item("AGREE", "near", "near") for _ in range(10)]
    ceil = mod.compute_ceiling(per_item)
    assert ceil["n_resolved"] == 10
    assert ceil["n_contested"] == 0
    assert ceil["sensitivity"]["resolved_only"]["value"] == pytest.approx(1.0)
    assert ceil["sensitivity"]["contested_as_agree"]["value"] == pytest.approx(1.0)
    assert ceil["sensitivity"]["contested_as_disagree"]["value"] == pytest.approx(1.0)


def test_compute_ceiling_mixed_resolved_correct_incorrect():
    per_item = (
        [_per_item("AGREE", "near", "near")] * 6  # correct
        + [_per_item("AGREE", "near", "far")] * 4  # resolved but WRONG vs benchmark
    )
    ceil = mod.compute_ceiling(per_item)
    assert ceil["n_resolved"] == 10
    assert ceil["sensitivity"]["resolved_only"]["value"] == pytest.approx(0.6)
    assert ceil["sensitivity"]["resolved_only"]["arithmetic"] == "6/10"


def test_compute_ceiling_sensitivity_range_with_contested_items():
    per_item = (
        [_per_item("AGREE", "near", "near")] * 6  # matches
        + [_per_item("AGREE", "near", "far")] * 2  # resolved, wrong
        + [_per_item("CONTESTED", "near", None)] * 2  # contested
    )
    ceil = mod.compute_ceiling(per_item)
    assert ceil["n_total_scored"] == 10
    assert ceil["n_resolved"] == 8
    assert ceil["n_contested"] == 2
    assert ceil["contested_rate"] == pytest.approx(0.2)
    # resolved-only: 6 matches / 8 resolved
    assert ceil["sensitivity"]["resolved_only"]["value"] == pytest.approx(6 / 8)
    # contested-as-agree (optimistic): (6 matches + 2 contested) / 10 total
    assert ceil["sensitivity"]["contested_as_agree"]["value"] == pytest.approx(8 / 10)
    # contested-as-disagree (conservative): 6 matches / 10 total
    assert ceil["sensitivity"]["contested_as_disagree"]["value"] == pytest.approx(6 / 10)
    # optimistic must never be below conservative
    assert (
        ceil["sensitivity"]["contested_as_agree"]["value"]
        >= ceil["sensitivity"]["contested_as_disagree"]["value"]
    )
    assert ceil["sensitivity"]["third_judge"]["value"] is None
    assert "N/A" in ceil["sensitivity"]["third_judge"]["description"]


def test_compute_ceiling_judge_unavailable_excluded_from_every_denominator():
    per_item = [_per_item("AGREE", "near", "near")] * 5 + [
        _per_item("JUDGE_UNAVAILABLE", "near", None)
    ] * 3
    ceil = mod.compute_ceiling(per_item)
    assert ceil["n_judge_unavailable"] == 3
    assert ceil["n_total_scored"] == 5  # unavailable items excluded from the denominator
    assert ceil["sensitivity"]["resolved_only"]["value"] == pytest.approx(1.0)


def test_compute_ceiling_empty_input_returns_none_values():
    ceil = mod.compute_ceiling([])
    assert ceil["n_total_scored"] == 0
    assert ceil["sensitivity"]["resolved_only"]["value"] is None
    assert ceil["contested_rate"] is None


def test_compute_ceiling_contested_examples_capped_and_shaped():
    per_item = [_per_item("CONTESTED", "near", None) for _ in range(15)]
    ceil = mod.compute_ceiling(per_item)
    assert len(ceil["contested_examples"]) == 10  # capped, not all 15
    assert set(ceil["contested_examples"][0].keys()) == {
        "secret",
        "word",
        "benchmark_tier",
        "qwen3:8b",
        "llama3.1:8b",
    }


# ---------------------------------------------------------------------------
# Performance-as-%-of-ceiling arithmetic (spec step 9).
# ---------------------------------------------------------------------------


def test_performance_as_pct_of_ceiling_basic_arithmetic():
    current = {"dim1_spearman": 0.675, "band_accuracy_overall": 0.81}
    perf = mod.performance_as_pct_of_ceiling(current, ceiling_point=0.9)
    assert perf["dim1_spearman_pct_of_ceiling"] == pytest.approx(0.675 / 0.9 * 100.0)
    assert perf["band_accuracy_pct_of_ceiling"] == pytest.approx(0.81 / 0.9 * 100.0)


def test_performance_as_pct_of_ceiling_handles_none_ceiling():
    current = {"dim1_spearman": 0.675, "band_accuracy_overall": 0.81}
    perf = mod.performance_as_pct_of_ceiling(current, ceiling_point=None)
    assert perf["dim1_spearman_pct_of_ceiling"] is None
    assert perf["band_accuracy_pct_of_ceiling"] is None
    assert "note" in perf


def test_performance_as_pct_of_ceiling_handles_zero_ceiling():
    current = {"dim1_spearman": 0.675, "band_accuracy_overall": 0.81}
    perf = mod.performance_as_pct_of_ceiling(current, ceiling_point=0.0)
    assert perf["dim1_spearman_pct_of_ceiling"] is None


def test_load_current_state_metrics_reads_real_checkpoint():
    # current_state_report.json is a frozen, already-committed checkpoint --
    # this exercises the real read path, not a synthetic fixture.
    metrics = mod.load_current_state_metrics()
    assert 0.0 < metrics["dim1_spearman"] < 1.0
    assert 0.0 < metrics["band_accuracy_overall"] < 1.0


# ---------------------------------------------------------------------------
# Inter-judge kappa reliability banding (spec step 5) -- exercises the
# score_label_ceiling.py reuse path against small synthetic pairs, no I/O.
# ---------------------------------------------------------------------------


def test_compute_inter_judge_kappa_perfect_agreement_is_reliable():
    per_item = [
        {"qwen3:8b": "near", "llama3.1:8b": "near"},
        {"qwen3:8b": "mid", "llama3.1:8b": "mid"},
        {"qwen3:8b": "far", "llama3.1:8b": "far"},
    ] * 5
    result = mod.compute_inter_judge_kappa(per_item)
    assert result["kappa"]["point"] == pytest.approx(1.0)
    assert result["reliable"] is True
    assert result["landis_koch_band"] == "almost perfect"


def test_compute_inter_judge_kappa_near_chance_agreement_is_unreliable():
    # Deliberately near-random pairing (roughly chance-level agreement on a
    # 3-way scale) should land kappa well below the 0.4 reliability floor.
    per_item = [
        {"qwen3:8b": "near", "llama3.1:8b": "far"},
        {"qwen3:8b": "far", "llama3.1:8b": "near"},
        {"qwen3:8b": "mid", "llama3.1:8b": "near"},
        {"qwen3:8b": "near", "llama3.1:8b": "mid"},
    ] * 5
    result = mod.compute_inter_judge_kappa(per_item)
    assert result["kappa"]["point"] < 0.4
    assert result["reliable"] is False


def test_compute_inter_judge_kappa_excludes_none_votes():
    per_item = [
        {"qwen3:8b": "near", "llama3.1:8b": "near"},
        {"qwen3:8b": None, "llama3.1:8b": "far"},  # excluded -- one judge had no valid vote
        {"qwen3:8b": "far", "llama3.1:8b": None},  # excluded
    ]
    result = mod.compute_inter_judge_kappa(per_item)
    assert result["n_pairs"] == 1


# ---------------------------------------------------------------------------
# Ollama wiring, STUBBED -- no real network calls in this test module.
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: dict, status: int = 200):
        self._payload = payload
        self.status = status

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_call_ollama_tier_parses_valid_response(monkeypatch):
    def fake_urlopen(request, timeout=None):  # noqa: ARG001
        return _FakeResponse({"response": json.dumps({"tier": "near"})})

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    assert mod.call_ollama_tier("qwen3:8b", "some prompt") == "near"


def test_call_ollama_tier_returns_none_on_malformed_json(monkeypatch):
    def fake_urlopen(request, timeout=None):  # noqa: ARG001
        return _FakeResponse({"response": "not json"})

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    assert mod.call_ollama_tier("qwen3:8b", "some prompt") is None


def test_call_ollama_tier_returns_none_on_out_of_schema_tier(monkeypatch):
    def fake_urlopen(request, timeout=None):  # noqa: ARG001
        return _FakeResponse({"response": json.dumps({"tier": "extremely-near"})})

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    assert mod.call_ollama_tier("qwen3:8b", "some prompt") is None


def test_call_ollama_tier_returns_none_on_connection_error(monkeypatch):
    def fake_urlopen(request, timeout=None):  # noqa: ARG001
        raise ConnectionError("no server")

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    assert mod.call_ollama_tier("qwen3:8b", "some prompt") is None


def test_self_consistency_vote_majority_over_stubbed_sequence(monkeypatch):
    responses = iter(["near", "near", "far"])

    def fake_urlopen(request, timeout=None):  # noqa: ARG001
        return _FakeResponse({"response": json.dumps({"tier": next(responses)})})

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    item = mod.JudgeItem(
        secret="azaadi", gloss="freedom", word="liberty", domain="abstract", label="near"
    )
    result = mod.self_consistency_vote("qwen3:8b", item, seed=42, k=3)
    assert result["majority"] == "near"
    assert result["votes"] == ["near", "near", "far"]
    assert result["n_failed"] == 0


def test_verify_judges_available_raises_when_ollama_down(monkeypatch):
    monkeypatch.setattr(mod, "check_ollama_up", lambda: False)
    with pytest.raises(mod.ConsensusJudgeUnavailableError):
        mod.verify_judges_available()


def test_verify_judges_available_reports_missing_models(monkeypatch):
    monkeypatch.setattr(mod, "check_ollama_up", lambda: True)
    monkeypatch.setattr(mod, "list_available_models", lambda: {"qwen3:8b"})
    availability = mod.verify_judges_available()
    assert availability == {"qwen3:8b": True, "llama3.1:8b": False}


def test_run_calibration_gate_end_to_end_stubbed(monkeypatch):
    """Every call returns the CORRECT tier for its item (stubbed
    perfectly) -- both judges should score 100% and pass."""

    def fake_urlopen(request, timeout=None):  # noqa: ARG001
        body = json.loads(request.data)
        prompt = body["prompt"]
        # crude but sufficient for this stub: infer expected tier from which
        # control fixture word appears in the prompt.
        tier = "near" if "liberty" in prompt or "freedom" in prompt else "far"
        return _FakeResponse({"response": json.dumps({"tier": tier})})

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    items = [
        mod.JudgeItem(
            secret="azaadi", gloss="freedom", word="liberty", domain="abstract", label="near"
        ),
        mod.JudgeItem(secret="chattan", gloss="rock", word="dessert", domain="nature", label="far"),
    ]
    gate = mod.run_calibration_gate(items, models=("qwen3:8b", "llama3.1:8b"), seed=42, k=3)
    for judge_result in gate["per_judge"].values():
        assert judge_result["accuracy"] == pytest.approx(1.0)
        assert judge_result["passed"] is True
    passed, _msg = mod.calibration_verdict(gate)
    assert passed
