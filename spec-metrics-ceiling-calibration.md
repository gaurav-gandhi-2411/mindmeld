# Warmer — Metric Re-specification, Automated Label Ceiling, and Calibration Frontier

## Standing policies
- Evaluate every model with metrics genuinely suited to its ACTUAL task; target exceptional performance vs alternatives; establish a USP competitors can't match.
- NEVER block a workflow on manual human labeling. Use multi-LLM consensus (different model families, blind, inter-judge agreement measured, calibrated on unambiguous cases), and label outputs honestly as LLM-consensus, not human ground truth.

## Current state (from the freshly recomputed bake-off, 42-secret combined test)
Shipped model leads 54/56 CI-significant cells with 0 regressions; top-weighted-corr 0.774 vs next-best 0.633; dim1 0.675, dim2 0.740. Two exceptions (NDCG@10, Recall@10 vs l3cube) are statistical ties. Band ECE 0.202 — statistically tied with granite (0.195), i.e. the ONLY dimension without a clear lead. Warm-band recall 8.3% (precision 41.2%) is the weakest absolute number.

---

## WORKSTREAM 1 — Fix the mis-specified retrieval metrics (do first; current numbers are uninformative)
**The problem:** Precision@10 = 1.000 and Precision@50 = 1.000 while Recall@10 = 0.169. Perfect precision at k means every retrieved item is "relevant", so Recall@k is capped at k/|R| — the model is AT that cap and mathematically cannot score higher. These metrics currently measure the size of the relevance set, not model quality, and explain the NDCG@10/Recall@10 "tie" (both models saturated at k=10).

Actions:
1. Report |R| (relevance-set size) per query — confirm the saturation diagnosis explicitly.
2. Re-specify relevance as **graded**, using the benchmark's own near/mid/far tiers as relevance grades, and recompute NDCG with graded gains (this is what NDCG is designed for). Binary relevance with |R| >> k is the wrong configuration.
3. Add metrics that don't saturate: **R-precision**, **MAP**, and recall at k values comparable to |R|.
4. Re-run the 8-model comparison under the corrected metrics with paired bootstrap CIs. Determine whether the l3cube tie at k=10 survives correct specification or was purely an artifact.
5. Keep the old numbers in the report for continuity, clearly marked as superseded and why.

## WORKSTREAM 2 — Label ceiling via multi-LLM consensus (NO manual labeling)
Replaces the 75-pair manual task. Goal: establish the benchmark's own ceiling so performance can be expressed as % of achievable.

Protocol (robustness is the point — a naive two-model vote is not enough):
1. **Two judges from DIFFERENT model families** (e.g. qwen3:8b and llama3.1:8b — both already local, $0). Same-family judges have correlated errors and would inflate agreement.
2. **Blind and order-randomised:** judges never see the benchmark's own label, the tier name, or each other's output. Randomise pair order and the presentation order of options per item.
3. **Self-consistency per judge:** sample each judge k≥3 times (temperature > 0), take the per-judge majority. Reduces single-sample noise before cross-judge comparison.
4. **Judge calibration gate (mandatory):** first run both judges on unambiguous control items — exact synonyms (must label near) and hash-random far-tier fillers (must label far). A judge that fails controls is not trusted; report control accuracy per judge. If a judge fails, replace it, don't proceed.
5. **Inter-judge agreement:** compute Cohen's kappa between the two judges. This is the trust gate — if kappa is low, the consensus is not reliable and the ceiling estimate must be reported as unreliable rather than quietly used.
6. **Disagreement handling:** where judges disagree, resolve with a third judge from a third family if available; otherwise mark the item **contested**. Contested items are themselves a finding — they represent genuine label ambiguity and bound the ceiling.
7. **Compute the ceiling:** agreement between consensus labels and the benchmark's existing labels. That agreement rate is the benchmark's ceiling — no model can exceed it, because the remainder are contested labels.
8. **Sensitivity analysis:** report the ceiling under alternative tie-break rules (contested-as-agree, contested-as-disagree, third-judge) to show the estimate is robust to methodology choices.
9. **Re-express current performance as % of achievable ceiling** — this is the number that answers "have we hit the best possible".
10. **Honest labelling:** everywhere this is reported (docs, model card, benchmark card), describe it as an **LLM-consensus ceiling**, not a human-annotated ceiling. Note the known limitation: LLM judges may share correlated blind spots from similar training data.

## WORKSTREAM 3 — Calibration as the next improvement frontier
Ranking is effectively solved (dominant, wide margins). Band assignment is not — ECE 0.202 is a statistical tie with the best comparator, and Warm recall is 8.3% vs 41.2% precision (most human-expected-Warm words land elsewhere).
1. Diagnose the Warm asymmetry: recall 8.3% / precision 41.2% means the band is under-assigned. Determine whether it is threshold placement (fixable deterministically, like the previous floor fix) or genuine mid-range ranking error (needs model work). Report which, with evidence.
2. Explore threshold optimisation: fit band boundaries to maximise band-level agreement with the benchmark's tiers (per language), rather than using hand-chosen constants. Deterministic, no retraining, consistent with the pattern that pipeline interventions win here.
3. Re-measure the Warm↔Far trade-off (the last fix cost far-tier accuracy 95.7%→93.3%) — optimise the boundary set jointly rather than one band at a time.
4. Gate any change on the full metric suite + zero net regression, and verify in real gameplay terms (simulate realistic guess distributions; confirm each band is reachable and sensible).

## Gates
- Every metric with bootstrap CIs; paired tests for comparisons.
- Nothing ships to HF/production unless it clears the full suite with zero net regression; the current published model stands until beaten.
- Never tune the benchmark to flatter the model; label corrections only, in a visible changelog.
- Report "model" (raw weights) and "system" (with Devanagari patch + alias fold) as SEPARATE claims — the bake-off measures raw weights only.
- Scrub game content from public artefacts; EN untouched; everything seeded, logged, rerunnable.
- If GCP is used: cap spend, checkpoint, tear down and verify zero billable resources, report burn.

## Deliverables
1. Corrected retrieval metrics + re-run 8-model comparison; explicit statement of whether the k=10 tie survives.
2. LLM-consensus label ceiling with judge control accuracy, inter-judge kappa, contested-item count, sensitivity analysis, and current performance expressed as % of achievable.
3. Calibration diagnosis + optimised band thresholds (if they clear gates), with the Warm/Far trade-off jointly measured.
4. One consolidated update: where the model stands, what is genuinely left, ranked by user impact.
