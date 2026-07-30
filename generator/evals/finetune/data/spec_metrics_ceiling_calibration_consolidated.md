# Consolidated findings — spec-metrics-ceiling-calibration.md

Orchestrator synthesis of Workstreams 1-3, final state. Source reports:
`corrected_retrieval_metrics_report.md` (+`.json`),
`llm_consensus_ceiling_report.md` (+`.json`),
`calibration_threshold_report.md` (+`.json`).

**Production state as of this update**: the Workstream 3 Warm-threshold fix
(`warm_max` 900→1050) IS shipped and live — `rival.py`, `dimension5_winrate.py`,
`app/lib/core/config.dart` all updated and committed (`0d9efb3`, `566f5f6`),
hi-en payloads regenerated and byte-verified live, the Flutter web app
rebuilt and redeployed to playwarmer.vercel.app with the new threshold
confirmed live. `deploy-warmer.ps1` itself had a real, separate bug (native
command stderr crashing the script under PS5.1) found and fixed along the
way, proven with a clean unattended run, committed (`b922a18`).

Full combined test suite after all changes: 777 passed, 4 skipped, 2
pre-existing-unrelated Ollama-timeout errors (documented flake), zero
regressions attributable to this work.

---

## 1. Where the model stands — corrected

- **Ranking quality is real and, on the metrics that actually discriminate
  models, still leading.** The old "NDCG@10/Recall@10 tie with l3cube" was
  suspected to be a saturation artifact. It mostly ISN'T: NDCG@10 was
  already graded (no bug existed), and the true |R| (relevance-set size) is
  3–5 per secret — not the ~59-60 the spec's own working hypothesis assumed
  (verified against real data, premise corrected rather than assumed). The
  actual saturation mechanism is sparse judgment (only ~9 words judged per
  secret out of a 10,495-word vocabulary), which pins Precision@10/@50 at
  ~1.000 for every model — that metric is retired as uninformative.
  **NDCG@10, Recall@10, and R-precision ties with l3cube survive** correct
  specification as genuine statistical-power limits at n=42 secrets (CIs
  include 0). **MAP does not tie** — shipped model leads l3cube significantly
  (+0.0254, CI [+0.0044, +0.0460]). Net: the "tie" claim should be scoped to
  "on 3 of 4 non-saturating/graded metrics, not fully resolved at this
  sample size — but the model wins outright on MAP," not reported as a flat
  tie.
- **Band assignment (what users see): shipped.** The Warm-threshold fix is
  live in production (see §3). ECE itself is confirmed unmovable by any
  threshold change (mathematical fact) — closing it needs a different
  mechanism, and remains open.
- **The label ceiling — how close to "as good as the benchmark can support"
  the model already is — remains genuinely unknown**, not from lack of
  effort but as a real, tested negative result. See §2.

## 2. LLM-consensus label ceiling — CLOSED, honest negative result

`generator/evals/finetune/llm_consensus_ceiling.py` implements all 10 spec
steps (two different-family judges, blind + order-randomised, k=3
self-consistency, mandatory 90%-bar calibration gate, Cohen's weighted kappa
trust gate, contested-item handling, 3-way sensitivity analysis, % of
ceiling). `tests/test_llm_consensus_ceiling.py` — 42/42 passing against a
stubbed Ollama layer. **No manual labeling was requested or performed
anywhere in this work**, per standing policy.

Local GPU contention (chronic — a recurring `aetherart` job, not a one-off)
never cleared long enough for an uncontended local run, so the job moved to
GCP with GG's approval. Two real, full-scale runs on `aetherart-497918`
(`g2-standard-8` + 1x NVIDIA L4, `asia-south1-c` — chosen after directly
verifying live unused GPU quota there; the repo's usual precedent project
`triageiq-portfolio-495022` has 0 GPU quota):

- **Attempt 1** (qwen3:8b + llama3.1:8b, ~184s protocol wall-clock, ~$0.16):
  qwen3:8b PASSED calibration (96.7%: 100% near, 93.3% far). llama3.1:8b
  FAILED (83.3%: 100% near, 66.7% far — bar is 90%).
- **Attempt 2**, GG's explicit bounded retry (qwen3:8b + gemma2:9b, one
  replacement judge, gate-only-first, no bar softening, ~27min session
  incl. VM setup, ~$0.41): gemma2:9b also FAILED (86.7%: 100% near, 73.3%
  far).

**Both failing judges share the identical failure mode**: over-predicting
relatedness ("mid" instead of "far") on unambiguous, domain-disjoint far-tier
control pairs. Near-tier accuracy was 100% for all three judges tested — the
defect is specific to far-tier judgment, not general judge quality. Two
missed items (`registan`/platter, `mazaa`/duration) fail for both
replacement judges, suggesting those specific controls are genuinely harder,
not per-model noise.

**Conclusion, per GG's own stop condition** (no third model, no bar
loosening, no temperature-shopping): the LLM-consensus label ceiling cannot
currently be established with locally-available ~7-9B instruction-tuned
models. Documented as a final, honest negative result, not an open blocker.
qwen3:8b is documented as the one passing judge found (96.7%) for any future
attempt with a genuinely different third model family (a larger/stronger
model, or a paid-API judge, would be the next lever — out of this
workstream's scope). Total GCP spend across both attempts: **~$0.57**, both
sessions torn down and verified at zero billable resources.

## 3. Calibration — shipped

**Diagnosis:** Warm-band recall (8.3%) is **predominantly genuine ranking
error, not threshold placement** — 75.3% of the 77 missed mid-tier records
either already rank inside Scorching/Hot (interleaved with correctly-ranked
near-tier words, no safe cutoff exists) or sit deep in the tail (rank >2400
of 10,495). Only 24.7% (19 records) were threshold-recoverable.

**Shipped:** `warm_max` floor `900 → 1050` (`rival.py::band_for_rank` +
`_generate_path`, `dimension5_winrate.py`, and the Dart mirror
`app/lib/core/config.dart`, all kept in sync). **+4 fixed / 0 broken** — Near
and Far confusion-matrix rows are byte-identical before/after (unlike the
prior 900-floor fix, which cost Far accuracy 95.7%→93.3%). Mid recall
8.3%→13.1% (directionally real, not CI-significant at n=84). A more
aggressive candidate reaching +6 net was evaluated and explicitly
**rejected** for breaking 5 near-tier records — the same one-band-tradeoff
trap this workstream existed to catch. Realistic-guess simulation (118 real
puzzles, 100 trajectories each): all 6 bands remain reachable; Warm's
real-play frequency rises 4.14%→5.27%.

**Deployed end-to-end**: generator fix + Dart fix committed (`0d9efb3`,
`566f5f6`), hi-en payloads regenerated and byte-verified live on the
payloads CDN (18 files changed), EN payloads spot-checked byte-identical
(zero impact, confirmed not just assumed), Flutter web app rebuilt and
redeployed to playwarmer.vercel.app (byte-verified WASM match, smoke check
passed) — rival-displayed bands and player-guess bands are consistent again.

**Honest scope**: this fix addresses only the ~25% threshold-placement share
of the Warm-recall gap. The remaining ~75% is genuine ranking error — a
documented model limitation whose real fix needs better training data (the
standing player-data lever), not a threshold change. Stated plainly in both
the report and the shipping commit body, not buried.

**Hard limit found:** band ECE (0.202, tied with granite's 0.195) is
**mathematically independent of band thresholds** —
`topheavy.band_calibration_error` never reads `actual_band`. No threshold
search, however exhaustive, can close that gap; confirmed byte-identical
(0.2020108359603864) before/after shipping. If worth closing, it needs a
different mechanism (e.g. recalibrating the rank→confidence mapping itself)
— out of this workstream's scope, remains open.

**Side effect fixed**: `deploy-warmer.ps1` itself had a real, pre-existing
bug surfaced while proving the app deploy — any native command's stderr
output (not just vercel's) was crashing the script under Windows PowerShell
5.1's `$ErrorActionPreference='Stop'`, on every run, including successful
ones. Fixed with an `Invoke-NativeCommand` helper scoping EAP to just each
native call and deciding success/failure from the real exit code, applied to
all 7 call sites. Proven with a clean, fully unattended real deploy.
Committed (`b922a18`).

## 4. What's genuinely left, ranked by user impact

1. **Corrected retrieval-metric reporting** (§1) — already fully delivered;
   the residual action is deciding whether the model/benchmark cards should
   be updated to state the MAP win and the narrower, honest framing of the
   NDCG/Recall/R-precision ties (currently they likely still say "tied,"
   which undersells the MAP result and overclaims certainty on the others).
2. **The ECE gap itself (0.202 vs 0.195) remains open and unaddressed** —
   now provably NOT closeable via band thresholds (confirmed twice, before
   and after the shipped fix). A real, scoped follow-up (rank→confidence
   recalibration) if you want to pursue it, otherwise worth documenting as
   a known, characterized limitation like the junoon/registan residual.
3. **The label ceiling is a closed negative, not an open item** — no further
   action unless you want to try a materially different judge (bigger local
   model, or a paid API judge — a real cost/quality decision, not a retry of
   what already failed twice).
4. **The Warm-recall residual (~75%, genuine ranking error)** is now the
   clearly-isolated remaining piece of that whole thread — same
   documented-limitation status as the junoon/registan subword-collision
   residual: real, characterized, not threshold-fixable, needs model/data
   work if pursued further.
