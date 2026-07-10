from __future__ import annotations

"""
Aggregates all 5 eval-harness dimensions (+ the pre-existing 77 pairwise
ordering fixtures, subsumed not replaced — see run_evals.py, still runnable
and still pytest-gated standalone) into one report: JSON (machine-readable,
full detail) + Markdown (human-readable summary) — the single `run_evals`
deliverable the spec asks for.
"""

import json
import sys
import time
from pathlib import Path

from config import EVALS_DIR
from evals.harness.dimension1_ranking import run_dimension1
from evals.harness.dimension2_crosslang import run_dimension2
from evals.harness.dimension3_judge import run_dimension3
from evals.harness.dimension4_rival import run_dimension4
from evals.harness.dimension5_winrate import run_dimension5
from evals.run_evals import load_fixtures, run_fixtures

REPORTS_DIR = EVALS_DIR / "reports"


def run_full_harness(judge_all: bool = True) -> dict:
    """Run every dimension + the legacy fixture set. Returns the full report dict.

    judge_all=False skips the expensive full-clue LLM judge pass (dimension 3
    still runs its calibration, just not the ~220-clue full judge run) — use
    for fast iteration; the committed baseline report always uses True.
    """
    t0 = time.time()
    report: dict = {"generated_notes": []}

    # Legacy 77-fixture pairwise-ordering set — subsumed into this report,
    # not replaced. Still independently runnable via `uv run python
    # evals/run_evals.py` and still gated by tests/test_evals.py.
    fixtures = load_fixtures(EVALS_DIR / "fixtures")
    passed, total = run_fixtures(fixtures, verbose=False)
    report["legacy_fixtures"] = {"passed": passed, "total": total}

    report["dimension1_ranking"] = {
        "en": run_dimension1("en"),
        "hi-en": run_dimension1("hi-en"),
    }
    report["dimension2_crosslang"] = run_dimension2()
    report["dimension3_judge"] = run_dimension3(judge_all=judge_all)
    report["dimension4_rival"] = run_dimension4()
    report["dimension5_winrate"] = run_dimension5()

    report["elapsed_seconds"] = round(time.time() - t0, 1)
    return report


def _fmt_pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _fmt_num(x: float | None, decimals: int = 3) -> str:
    return "n/a" if x is None else f"{x:.{decimals}f}"


def render_markdown(report: dict) -> str:
    lines: list[str] = []
    lines.append("# Warmer — Applied-AI Eval Harness: Baseline Report\n")
    lines.append(
        f"Generated in {report['elapsed_seconds']}s. See the sibling `.json` file for full "
        "per-record detail (every flagged scenario, every judged clue, every simulated puzzle).\n"
    )

    lf = report["legacy_fixtures"]
    lines.append("## Legacy pairwise-ordering fixtures (subsumed, not replaced)\n")
    lines.append(f"- {lf['passed']}/{lf['total']} passed\n")

    lines.append("## Dimension 1 — Semantic ranking quality\n")
    for lang in ("en", "hi-en"):
        d = report["dimension1_ranking"][lang]
        ba = d["band_accuracy"]
        lines.append(f"### {lang}\n")
        lines.append(f"- n_scenarios: {d['n_scenarios']}")
        lines.append(
            f"- band-accuracy: overall {_fmt_pct(ba['overall'])}, near {_fmt_pct(ba['near'])}, "
            f"mid {_fmt_pct(ba['mid'])}, far {_fmt_pct(ba['far'])}"
        )
        if d["band_accuracy_hien_near_split"]:
            s = d["band_accuracy_hien_near_split"]
            lines.append(
                f"- **hi-en near-tier split** (GG review — do not blend these): "
                f"translation {_fmt_pct(s['translation']['band_accuracy'])} "
                f"(n={s['translation']['n']}), "
                f"associate {_fmt_pct(s['associate']['band_accuracy'])} (n={s['associate']['n']})"
            )
        lines.append(f"- Spearman correlation: {_fmt_num(d['spearman_correlation'])}")
        m = d["monotonicity"]
        lines.append(
            f"- monotonicity violations: {m['violations']}/{m['total_pairs']} "
            f"({_fmt_pct(m['violation_rate'])})"
        )
        lines.append(f"- flagged weak pairs: {len(d['flagged_weak'])}\n")

    lines.append("## Dimension 2 — Cross-language consistency\n")
    d2 = report["dimension2_crosslang"]
    lines.append(
        f"- {d2['n_resolved']}/{d2['n_pairs']} pairs resolved "
        f"({d2['n_resolution_errors']} vocab-coverage errors)"
    )
    lines.append(
        f"- pass rate (translation lands Scorching/Hot): "
        f"{_fmt_pct(d2['pass_rate_scorching_or_hot'])}"
    )
    lines.append(
        f"- median rank: {d2['median_rank']} "
        f"({_fmt_num(d2['median_rank_percentile'], 1)}th percentile of vocab)"
    )
    lines.append("- worst-diverging pairs (translation ranks near the BOTTOM of the vocab):\n")
    for r in d2["worst_diverging_pairs"][:10]:
        lines.append(
            f"  - `{r['hien_secret']}` <- `{r['en_secret']}`: rank {r['rank']} "
            f"({r['rank_percentile']:.1f}%ile)"
        )
    lines.append("")

    lines.append("## Dimension 3 — Clue quality (local LLM judge, qwen3:8b)\n")
    d3 = report["dimension3_judge"]
    if not d3["available"]:
        lines.append(f"**UNAVAILABLE**: {d3['error']}\n")
    else:
        cal = d3["calibration"]
        lines.append("### Calibration (judge <-> known-ground-truth agreement)\n")
        lines.append(
            f"- spoiler-safety agreement: {_fmt_pct(cal['spoiler_agreement'])} "
            f"({cal['n_spoiler_cases']} golden cases)"
        )
        lines.append(
            f"- solvability agreement: {_fmt_pct(cal['solvability_agreement'])} "
            f"({cal['n_solvability_cases']} golden cases)\n"
        )
        if "n_clues_judged" in d3:
            lines.append("### Full clue-set judging\n")
            lines.append(
                f"- n_clues_judged: {d3['n_clues_judged']} (errors: {d3['n_judge_errors']})"
            )
            lines.append(
                f"- solvability: min {d3['min_solvability']}, "
                f"mean {_fmt_num(d3['mean_solvability'], 2)}, "
                f"% below gate ({3}): {_fmt_pct(d3['pct_below_min_solvability'])}"
            )
            lines.append(f"- spoiler-flagged clues: {d3['n_spoiler_flagged']}")
            lines.append(f"- difficulty distribution: {d3['difficulty_distribution']}")
            lines.append(
                f"- mean cultural_fit (hi-en, uncalibrated): "
                f"{_fmt_num(d3['mean_cultural_fit_hien'], 2)}\n"
            )

    lines.append("## Dimension 4 — Rival calibration\n")
    d4 = report["dimension4_rival"]
    lines.append(f"- n_puzzles: {d4['n_puzzles']}")
    lines.append(
        f"- median par: {d4['median_par']} (target 8-12: {d4['median_within_target']}), "
        f"{_fmt_pct(d4['par_within_target_range'])} within [4,16]"
    )
    lines.append(
        f"- median chill_spread: {d4['median_chill_spread']} "
        f"({_fmt_pct(d4['chill_spread_within_target'])} within [2,8])"
    )
    lines.append(
        f"- median sharp_spread: {d4['median_sharp_spread']} "
        f"({_fmt_pct(d4['sharp_spread_within_target'])} within [1,5])"
    )
    lines.append(f"- flagged puzzles: {d4['n_flagged']}\n")

    lines.append("## Dimension 5 — Difficulty / win-rate modeling\n")
    d5 = report["dimension5_winrate"]
    lines.append(f"- n_puzzles: {d5['n_puzzles']}")
    lines.append(f"- median win-rate: {_fmt_pct(d5['median_win_rate'])}")
    lines.append(f"- in target band [75%,85%]: {_fmt_pct(d5['win_rate_in_target_band'])}")
    lines.append(f"- outliers too easy (>97%): {d5['n_outliers_too_easy']}")
    lines.append(f"- outliers too hard (<40%): {d5['n_outliers_too_hard']}\n")

    return "\n".join(lines)


def write_report(
    report: dict, out_dir: Path = REPORTS_DIR, name: str = "baseline_report"
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{name}.json"
    md_path = out_dir / f"{name}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


if __name__ == "__main__":
    judge_all = "--no-judge-all" not in sys.argv
    result = run_full_harness(judge_all=judge_all)
    json_path, md_path = write_report(result)
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
