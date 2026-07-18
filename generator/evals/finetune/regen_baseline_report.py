from __future__ import annotations

"""
Regenerate ONLY the model-dependent sections of evals/reports/baseline_report
after a hi-en model swap (legacy_fixtures, dimension1_ranking, dimension2_
crosslang -- all reference embeddings.embed_vocab / config.MODELS), and merge
with the EXISTING report's dimension3_judge/dimension4_rival/dimension5_winrate
sections, which reference neither and are therefore identical output for
identical input regardless of which hi-en model is configured (verified: grep
for `embed_vocab`/`MODELS[` across dimension3_judge.py, dimension4_rival.py,
dimension5_winrate.py returns zero matches). Re-running the full harness
(`evals/harness/report.py`) would take ~40 minutes almost entirely on the
LLM-judge dimension-3 pass for zero new information after a model-only swap.

NOTE (headline-number honesty, spec-hinglish-diagnostic-sweep.md Step 0's own
lesson applied forward): the FULL-set numbers this writes are NOT a fair
generalization estimate for the new model -- the full 25-secret production
scenario set includes secrets the model was directly fine-tuned on (33 train
+ 11 dev of the 60-secret schedule), unlike the old off-the-shelf model,
which had zero secrets in "its" training data. The apples-to-apples,
honest generalization claim remains the HELD-OUT test numbers from
ship_decision_report_v3.md (0.4350->0.7044 dim1, 0.375->0.8125 dim2, 8/16
held-out secrets never trained on). This full-set number is reported here
because baseline_report.md has always reported it (that's what "0.639" was),
not because it's the number to cite as "the improvement."

Run: uv run python -m evals.finetune.regen_baseline_report
"""

import json
import time

from config import EVALS_DIR
from evals.harness.dimension1_ranking import run_dimension1
from evals.harness.dimension2_crosslang import run_dimension2
from evals.harness.report import REPORTS_DIR, write_report
from evals.run_evals import load_fixtures, run_fixtures


def regenerate() -> dict:
    existing = json.loads((REPORTS_DIR / "baseline_report.json").read_text(encoding="utf-8"))

    t0 = time.time()
    fixtures = load_fixtures(EVALS_DIR / "fixtures")
    passed, total = run_fixtures(fixtures, verbose=False)

    report = dict(existing)  # carries forward dimension3_judge/4_rival/5_winrate unchanged
    report["legacy_fixtures"] = {"passed": passed, "total": total}
    report["dimension1_ranking"] = {
        "en": run_dimension1("en"),
        "hi-en": run_dimension1("hi-en"),
    }
    report["dimension2_crosslang"] = run_dimension2()
    report["generated_notes"] = existing.get("generated_notes", []) + [
        "2026-07-18: hi-en model swapped to gauravgandhi2411/hinglish-relatedness-sbert "
        "(spec-hinglish-diagnostic-sweep.md / ship_decision_report_v3.md). Only "
        "legacy_fixtures/dimension1_ranking/dimension2_crosslang recomputed -- "
        "dimension3_judge/4_rival/5_winrate are model-independent (verified: neither "
        "references embed_vocab or config.MODELS) and are carried forward unchanged "
        "from the prior report rather than re-run for zero new information."
    ]
    report["elapsed_seconds"] = round(time.time() - t0, 1)
    return report


if __name__ == "__main__":
    result = regenerate()
    json_path, md_path = write_report(result)
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    d1 = result["dimension1_ranking"]["hi-en"]["spearman_correlation"]
    d2 = result["dimension2_crosslang"]["pass_rate_scorching_or_hot"]
    print(f"hi-en dim1 spearman (full 25-secret set): {d1:.4f}")
    print(f"dim2 pass_rate (full 60-pair schedule): {d2:.4f}")
