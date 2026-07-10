from __future__ import annotations

"""
Dimension 3 — clue quality via local LLM-as-judge.

Judges every clue (daily 60-day schedule + all live packs) on solvability,
spoiler-safety, difficulty, and (hi-en only) cultural fit — see judge_client.py
for the prompt and Ollama integration.

CALIBRATION (mandatory per spec — "an uncalibrated LLM judge is worse than
none"): rather than reconstruct GG's past review edits from git archaeology
(lossy, and much of the "before" wording was never committed), this builds a
golden set with KNOWN-CORRECT ground truth by construction:

  - spoiler-safety: every real, shipped clue (ground truth: NOT spoiled — it
    already passed the deterministic exact-alias gate) paired with the same
    clue MUTATED to literally state the secret (ground truth: spoiled). The
    judge's spoiler_flag is checked against this certain ground truth.
  - solvability: every real, shipped clue paired with its correct secret
    (ground truth: solvable — it's a live, human-reviewed clue) vs the same
    clue paired with a MISMATCHED random secret it was never written for
    (ground truth: not solvable). The judge's solvability score is checked
    for correctly ranking matched > mismatched.

This is a real, verifiable, human-authored ground truth (every clue in the
golden set was written and reviewed by GG during the Bollywood/Cricket pack
phases), constructed rather than reconstructed — see PLAN.md for why.
difficulty and cultural_fit have no constructed ground truth here (no
objective "correct" answer to check against) and are reported uncalibrated,
flagged as such rather than silently implied to be validated.
"""

import random

from clues import load_clues
from evals.harness.judge_client import JudgeUnavailableError, is_judge_available, judge_clue
from packs import load_pack_clues, load_pack_secrets, load_packs_meta
from schedule import load_schedule

CALIBRATION_SAMPLE_SEED = 42
CALIBRATION_N_PER_LANG = 8

MIN_SOLVABILITY = 3
MAX_DIFFICULTY_P90 = 5  # informational — no hard gate, difficulty has no ground truth


def _all_clue_records() -> list[dict]:
    """Every (secret, clue, lang, source) triple across daily + all live packs."""
    records: list[dict] = []
    for lang in ("en", "hi-en"):
        secrets = load_schedule(lang)
        clues = load_clues(lang)
        for secret, clue in zip(secrets, clues, strict=True):
            records.append({"source": "daily", "lang": lang, "secret": secret, "clue": clue})

    for pack in load_packs_meta():
        if not pack.langs:
            continue
        for lang in pack.langs:
            secrets = load_pack_secrets(pack, lang)
            clues = load_pack_clues(pack, lang)
            if not secrets:
                continue
            for secret, clue in zip(secrets, clues, strict=True):
                records.append(
                    {"source": f"pack:{pack.id}", "lang": lang, "secret": secret, "clue": clue}
                )
    return records


def _mutate_spoiler(clue: str, secret: str) -> str:
    """Deliberately break spoiler-safety: append the secret in plain sight."""
    return f"{clue} (the answer is {secret})"


def build_calibration_set() -> list[dict]:
    """Build the golden calibration set — see module docstring for methodology."""
    all_records = _all_clue_records()
    rng = random.Random(CALIBRATION_SAMPLE_SEED)

    cases: list[dict] = []
    for lang in ("en", "hi-en"):
        lang_records = [r for r in all_records if r["lang"] == lang]
        sample = rng.sample(lang_records, min(CALIBRATION_N_PER_LANG, len(lang_records)))
        other_secrets = [r["secret"] for r in lang_records]

        for rec in sample:
            secret, clue = rec["secret"], rec["clue"]

            # Spoiler-safety pair: real clean clue vs deliberately-spoiled mutation.
            cases.append(
                {
                    "axis": "spoiler_safety",
                    "lang": lang,
                    "secret": secret,
                    "clue": clue,
                    "ground_truth_spoiler_flag": False,
                    "case_id": f"real:{rec['source']}:{secret}",
                }
            )
            cases.append(
                {
                    "axis": "spoiler_safety",
                    "lang": lang,
                    "secret": secret,
                    "clue": _mutate_spoiler(clue, secret),
                    "ground_truth_spoiler_flag": True,
                    "case_id": f"mutated:{rec['source']}:{secret}",
                }
            )

            # Solvability pair: real clue with its TRUE secret (should score
            # high) vs the same clue with a randomly mismatched secret it was
            # never written for (should score low).
            mismatched = rng.choice([s for s in other_secrets if s != secret])
            cases.append(
                {
                    "axis": "solvability",
                    "lang": lang,
                    "secret": secret,
                    "clue": clue,
                    "ground_truth_solvable": True,
                    "case_id": f"matched:{rec['source']}:{secret}",
                }
            )
            cases.append(
                {
                    "axis": "solvability",
                    "lang": lang,
                    "secret": mismatched,
                    "clue": clue,
                    "ground_truth_solvable": False,
                    "case_id": f"mismatched:{rec['source']}:{secret}->{mismatched}",
                }
            )
    return cases


def run_calibration() -> dict:
    """Run the judge on the golden calibration set and report agreement."""
    cases = build_calibration_set()
    spoiler_cases = [c for c in cases if c["axis"] == "spoiler_safety"]
    solvability_cases = [c for c in cases if c["axis"] == "solvability"]

    spoiler_results = []
    for c in spoiler_cases:
        judged = judge_clue(c["secret"], c["clue"], c["lang"])
        agree = judged["spoiler_flag"] == c["ground_truth_spoiler_flag"]
        spoiler_results.append({**c, "judged_spoiler_flag": judged["spoiler_flag"], "agree": agree})

    solvability_results = []
    for c in solvability_cases:
        judged = judge_clue(c["secret"], c["clue"], c["lang"])
        # Agreement = judge's solvability score is on the correct side of
        # MIN_SOLVABILITY given the ground truth (matched=high, mismatched=low).
        predicted_solvable = judged["solvability"] >= MIN_SOLVABILITY
        agree = predicted_solvable == c["ground_truth_solvable"]
        solvability_results.append(
            {**c, "judged_solvability": judged["solvability"], "agree": agree}
        )

    spoiler_agreement = (
        sum(1 for r in spoiler_results if r["agree"]) / len(spoiler_results)
        if spoiler_results
        else None
    )
    solvability_agreement = (
        sum(1 for r in solvability_results if r["agree"]) / len(solvability_results)
        if solvability_results
        else None
    )

    return {
        "n_spoiler_cases": len(spoiler_results),
        "spoiler_agreement": spoiler_agreement,
        "spoiler_disagreements": [r for r in spoiler_results if not r["agree"]],
        "n_solvability_cases": len(solvability_results),
        "solvability_agreement": solvability_agreement,
        "solvability_disagreements": [r for r in solvability_results if not r["agree"]],
    }


def run_dimension3(judge_all: bool = True) -> dict:
    """Full dimension-3 run: availability check, calibration, then judge every
    real clue (daily + packs) if judge_all=True."""
    if not is_judge_available():
        return {
            "available": False,
            "error": (
                "Local Ollama judge not reachable at http://localhost:11434. "
                "Install/run: `ollama serve` (in a separate terminal) and "
                "`ollama pull qwen3:8b`, then re-run this dimension."
            ),
        }

    try:
        calibration = run_calibration()
    except JudgeUnavailableError as e:
        return {"available": False, "error": str(e)}

    result: dict = {"available": True, "calibration": calibration}

    if not judge_all:
        return result

    all_records = _all_clue_records()
    judged: list[dict] = []
    errors: list[dict] = []
    for rec in all_records:
        try:
            j = judge_clue(rec["secret"], rec["clue"], rec["lang"])
            judged.append({**rec, **j})
        except JudgeUnavailableError as e:
            errors.append({**rec, "error": str(e)})

    solvabilities = [r["solvability"] for r in judged]
    difficulties = [r["difficulty"] for r in judged]
    spoiler_flags = [r for r in judged if r["spoiler_flag"]]
    cultural_fits = [r["cultural_fit"] for r in judged if r.get("cultural_fit") is not None]

    result.update(
        {
            "n_clues_judged": len(judged),
            "n_judge_errors": len(errors),
            "judge_errors": errors,
            "min_solvability": min(solvabilities) if solvabilities else None,
            "mean_solvability": sum(solvabilities) / len(solvabilities) if solvabilities else None,
            "pct_below_min_solvability": (
                sum(1 for s in solvabilities if s < MIN_SOLVABILITY) / len(solvabilities)
                if solvabilities
                else None
            ),
            "n_spoiler_flagged": len(spoiler_flags),
            "spoiler_flagged_clues": [
                {"source": r["source"], "lang": r["lang"], "secret": r["secret"], "clue": r["clue"]}
                for r in spoiler_flags
            ],
            "difficulty_distribution": {
                str(d): difficulties.count(d) for d in range(1, 6)
            },
            "mean_cultural_fit_hien": (
                sum(cultural_fits) / len(cultural_fits) if cultural_fits else None
            ),
            "low_cultural_fit_clues": [
                {"source": r["source"], "secret": r["secret"], "clue": r["clue"],
                 "cultural_fit": r["cultural_fit"]}
                for r in judged
                if r.get("cultural_fit") is not None and r["cultural_fit"] <= 2
            ],
            "all_judged": judged,
        }
    )
    return result


if __name__ == "__main__":
    result = run_dimension3()
    print("=== dimension 3 — LLM-as-judge clue quality ===")
    if not result["available"]:
        print(f"  UNAVAILABLE: {result['error']}")
    else:
        cal = result["calibration"]
        print(f"  calibration: spoiler_agreement={cal['spoiler_agreement']:.3f} "
              f"({cal['n_spoiler_cases']} cases), "
              f"solvability_agreement={cal['solvability_agreement']:.3f} "
              f"({cal['n_solvability_cases']} cases)")
        if "n_clues_judged" in result:
            print(
                f"  n_clues_judged: {result['n_clues_judged']} "
                f"(errors: {result['n_judge_errors']})"
            )
            print(
                f"  min_solvability: {result['min_solvability']}, "
                f"mean: {result['mean_solvability']:.2f}"
            )
            print(f"  n_spoiler_flagged: {result['n_spoiler_flagged']}")
            print(f"  difficulty_distribution: {result['difficulty_distribution']}")
            print(f"  mean_cultural_fit_hien: {result['mean_cultural_fit_hien']}")
