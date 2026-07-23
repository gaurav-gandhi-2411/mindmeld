# Warmer — Hinglish Model Excellence Program

## Standing standard (applies to this and every model)
Evaluate with the metrics genuinely best-suited to the model's ACTUAL task — not defaults or conveniences. Target performance exceptionally better than alternatives. Ensure a clear USP competitors cannot offer.

## Current state
Published: `gauravgandhi2411/hinglish-relatedness-sbert` (weights: dim1 Spearman 0.657, dim2 pass-rate 0.727, 14/14 CI-significant vs 7 alternatives) + production wrapper L2-patch/L5 (0.717 / 0.849, zero regression). Benchmark: `gauravgandhi2411/hinglish-relatedness-benchmark` (34 secrets, ~600 scenarios).

## The core problem this program fixes
Global Spearman is a MISMATCHED metric for this task. The model's job is to rank ~10,495 words by relatedness to a secret, where users only ever perceive the TOP of that ranking (their guesses cluster in the first few hundred ranks; everything beyond is undifferentiated "Freezing"). Global Spearman spends most of its mass on rank regions no user experiences, and weights a 8000-vs-9000 error identically to a 3-vs-300 error. Additionally, the model's user-facing output is a temperature BAND, and band calibration has never been measured at all.

---

## WORKSTREAM A — Task-appropriate metric suite (do first; everything else is measured with it)
Replace/augment the headline metrics with ones matching the actual task. Implement, compute for the current model + all 7 comparators, and report a full table.
1. **Top-heavy ranking metrics:** NDCG@{10,50,100}, MRR, Recall@{10,50,100}, Precision@k, and a rank-weighted (top-emphasising) correlation. These reflect what users perceive.
2. **Band calibration (closest metric to lived UX):** expected calibration error across bands; a band-confusion matrix (predicted band × human-intended tier); per-band precision/recall. Answers "when a human means Warm, does the model say Warm?"
3. **Keep global Spearman** as a secondary/comparability metric — do not delete it, but demote it from headline.
4. Report every metric with bootstrap CIs. Re-run the 7-model comparison under the new suite: leadership must be re-established under task-appropriate metrics, not assumed from the old ones.

## WORKSTREAM B — Systematic failure analysis (find what aggregate metrics hide)
5. **Full error taxonomy at scale:** for every failing pair in the benchmark, classify the cause (subword-collision, commonsense/world-knowledge, polysemy/gloss ambiguity, transliteration artifact, genuine semantic difficulty, label error). Report counts per class — this ranks what to fix next by actual prevalence, replacing anecdote with distribution.
6. **Head/tail (frequency) analysis:** bucket vocabulary by corpus frequency; report metric performance per bucket. Determine whether quality is frequency-dependent and quantify the tail penalty.
7. **Per-domain and per-POS breakdown** with adequate n (see D) — abstract vs concrete, noun/adj/verb — to surface systematic weakness rather than noise.
8. **Systematic collision detection:** the L2 patch covers only 4 HAND-PICKED words. Scan the ENTIRE 10,495-word vocab for the subword-collision signature (romanized token whose nearest neighbours are dominated by orthographically-similar English tokens rather than semantic ones). Produce the full collision-prone list, then extend the L2 patch to all confirmed cases (same targeted mechanism, zero-regression gate).

## WORKSTREAM C — Robustness suite + THE USP
9. **Spelling-variance robustness (the differentiator):** romanized Hindi has no canonical orthography. Build an eval measuring rank/band STABILITY across spelling variants (khushbu/khushboo, baarish/barish, nariyal/nariyel …), generated from the existing alias layer + Aksharantar. Metrics: rank variance across variants, band-agreement rate, worst-case drift.
10. **If robustness is weak, TRAIN for it:** variant-augmented contrastive training (spelling variants as positives). This is a genuine, ownable USP — "the romanized-Hinglish embedding model that is measurably spelling-invariant" — which no competitor offers and which directly matters to real users. Gate any resulting model on the full metric suite + zero regression.
11. **Additional robustness axes:** casing, whitespace/compound forms, common typos.

## WORKSTREAM D — Benchmark strength & external comparability
12. **Statistical power:** 34 secrets is why dim1's improvement could not clear significance. Expand the benchmark enough that realistic effect sizes are detectable; report the power analysis (what effect size is detectable at what n).
13. **Label-ceiling measurement:** the near/mid/far tiers are AI-authored. Have a human (GG) annotate a sample independently; compute human↔benchmark agreement. This establishes the benchmark's own ceiling — without it, "how far from perfect are we" is unanswerable. Report the ceiling and re-express current performance as a % of achievable.
14. **External comparability:** search for and evaluate on any existing public code-mixed / Hindi semantic-similarity resource (e.g. code-switched NLP benchmark suites, transliterated Hindi similarity sets). Verify licence and applicability first; if none is suitable, document the search so the "no public benchmark existed" claim is evidenced.

## WORKSTREAM E — Efficiency (a second potential USP)
15. Measure model size/latency. Evaluate quantisation and/or distillation to a smaller student: if quality holds within CI at materially smaller size/faster inference, that is an additional USP ("best-in-class quality at a fraction of the size") and unblocks future on-device use. Gate on the full metric suite.

## WORKSTREAM F — Close known inert/incomplete items
16. **L5 dormancy:** its 8 trigger words appear in no live schedule, so it has never fired in production. Either schedule trigger words into an upcoming daily/pack, or generalise L5's coverage to words that DO appear. Report the fix chosen.
17. Confirm L4/L6 remain documented as live-but-untested levers with their triaged next steps.

## Gates (all workstreams)
- Every metric reported with bootstrap CIs; every model change gated on the FULL suite (not one metric) + zero net regression on currently-working pairs.
- Nothing ships to HF or production unless it clears those gates; the current published model stands until beaten.
- Benchmark must never be tuned to flatter the model; label fixes are corrections only, logged in a visible changelog.
- Public artefacts: scrub all game content, verify licences/attribution.
- EN untouched. All experiments logged, seeded, rerunnable. Report GCP spend if used; tear down and verify zero billable resources when pausing.

## Deliverables
1. Task-appropriate metric suite implemented + the 8-model comparison re-run under it, with CIs.
2. Failure taxonomy with prevalence counts; frequency/domain/POS breakdowns; full collision-prone word list.
3. Robustness suite + measured spelling-invariance; a trained-for-robustness candidate if warranted.
4. Strengthened benchmark (power + human-agreement ceiling + external comparability search).
5. Efficiency assessment (size/latency/quantisation-distillation).
6. L5 dormancy resolved.
7. One consolidated report: where the model still fails, ranked by prevalence and user impact, with the evidenced next attack for each.
