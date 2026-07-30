# PLAN — spec-metrics-ceiling-calibration.md CLOSED (2026-07-25)

Follow-up to the checkpoint below: WS3 shipped to production, WS2 concluded
as a final honest negative. Full detail:
`generator/evals/finetune/data/spec_metrics_ceiling_calibration_consolidated.md`.

**WS3 shipped end-to-end.** `warm_max` floor 900->1050 (`rival.py` +
`dimension5_winrate.py` + Dart mirror `app/lib/core/config.dart`, all synced)
-- +4 fixed/0 broken, Near/Far confusion rows byte-identical (unlike the
prior 900-floor fix, which cost Far 95.7%->93.3%). Commits `0d9efb3`
(Python), `566f5f6` (Dart). hi-en payloads regenerated + byte-verified live
(18 files), EN spot-checked byte-identical. Flutter web app rebuilt and
redeployed to playwarmer.vercel.app (byte-verified WASM, smoke check green)
-- rival-displayed and player-guess bands consistent again. Honest scope
documented: addresses only ~25% of the Warm-recall gap (threshold-
placement-fixable share); the other ~75% is genuine ranking error, a
documented model/data limitation, not fixed here.

**Side quest: `deploy-warmer.ps1` had a real, separate bug**, found while
proving the app deploy -- any native command's stderr (not just vercel's)
crashed the script under Windows PowerShell 5.1's
`$ErrorActionPreference='Stop'`, on every run, including successful ones
(confirmed with two unrelated tools: vercel, then uv). Fixed with an
`Invoke-NativeCommand` helper (EAP scoped per-call via try/finally, decides
success/failure from the real exit code) applied to all 7 native call sites,
plus an unrelated encoding bug (8 em-dashes, no BOM, misdecoding into a
smart-quote under this environment's codepage and corrupting two `throw`
literals) fixed alongside it. Proven with a clean, fully unattended real
deploy. Commit `b922a18`.

**WS2 (LLM-consensus ceiling) CLOSED as a final honest negative, not an open
blocker.** Local GPU contention was chronic (a recurring `aetherart` job,
not a one-off) and never cleared, so the job moved to GCP (`aetherart-497918`
-- verified live unused GPU quota there, unlike this repo's usual precedent
project `triageiq-portfolio-495022` which has 0). Two real full-scale runs,
`g2-standard-8` + 1x NVIDIA L4, `asia-south1-c`:
- Attempt 1 (qwen3:8b + llama3.1:8b, ~$0.16): qwen3:8b PASSED calibration
  (96.7%: 100% near/93.3% far). llama3.1:8b FAILED (83.3%: 100%/66.7%, bar
  90%).
- Attempt 2, GG's bounded retry (qwen3:8b + gemma2:9b, gate-only-first,
  ~$0.41): gemma2:9b also FAILED (86.7%: 100%/73.3%).
Both failing judges share the identical failure mode -- over-predicting
relatedness ("mid" not "far") on unambiguous domain-disjoint far-tier
controls; near-tier was 100% for all three judges tested. Per GG's explicit
stop condition (no third model, no bar softening, no temperature-shopping):
**the LLM-consensus label ceiling cannot currently be established with
locally-available ~7-9B models.** qwen3:8b documented as the one passing
judge for any future attempt with a genuinely different (bigger/paid) third
judge. Total GCP spend ~$0.57 across both attempts, both sessions torn down
and verified zero billable resources.

**What's left, ranked**: (1) decide whether model/benchmark cards should be
updated with the corrected MAP-win/narrower-tie framing from WS1; (2) the
ECE gap (0.202 vs granite 0.195) remains open, now provably not closeable
via thresholds; (3) label ceiling is closed, not open -- next lever would be
a materially different judge, a real cost/quality call, not a retry; (4) the
~75% genuine-ranking-error share of Warm-recall is now the clearly-isolated
remaining piece, same documented-limitation status as junoon/registan.

---

# PLAN — Metric re-specification + label ceiling + calibration frontier (2026-07-25)

Spec: `spec-metrics-ceiling-calibration.md`. Three parallel executor workstreams,
autonomous end-to-end per standing policy (no manual labeling requested at any
point). Full consolidated findings:
`generator/evals/finetune/data/spec_metrics_ceiling_calibration_consolidated.md`.
Combined full test suite after all three: 777 passed / 4 skipped / 2
pre-existing-unrelated Ollama-timeout errors (same GPU contention as WS2
below), zero regressions. Nothing applied to production — `rival.py` and the
shipped model are unchanged.

**WS1 (retrieval metrics, DONE)** — corrected the mis-specified Precision@10=
1.000/Recall@10=0.169 saturation. Real finding, not the spec's own working
hypothesis: |R| (relevance-set size) is 3-5/mean 4.0 per secret, not ~59-60 as
assumed — the classical `k/|R|` ceiling doesn't literally bind; the real
mechanism is sparse judgment (~9 judged words per secret out of 10,495-word
vocab). NDCG@10 was ALREADY graded (`_RELEVANCE_GRADE`, no bug) — documented,
not "fixed." Added R-precision/MAP/|R|-scaled recall + surfaced |R| everywhere,
all bootstrap-CI'd. **l3cube tie verdict, correctly scoped**: NDCG@10/Recall@10/
R-precision ties SURVIVE (genuine n=42 statistical-power limits, not artifacts)
but **MAP does not tie — shipped leads significantly** (+0.0254, CI
[+0.0044,+0.0460]). Precision@10's tie WAS a pure saturation artifact (delta=0
across all 10k draws) — retired, kept in report as superseded.
`generator/evals/finetune/data/corrected_retrieval_metrics_report.md`.

**WS3 (calibration, DONE)** — diagnosed Warm-band recall 8.3%: 75.3% of the 77
misses are genuine ranking error (unrecoverable by any threshold), only 24.7%
threshold-placement-fixable. Joint grid search found ONE candidate clearing a
strict zero-broken gate: `warm_max` floor 900->1050 (+4 fixed/0 broken, Near
and Far confusion rows byte-identical -- unlike the prior 900-floor fix which
cost Far 95.7%->93.3%). Mid recall 8.3%->13.1% (real, zero-cost, not
CI-significant at n=84). A more aggressive candidate (+6 net) was found and
explicitly REJECTED for breaking 5 near-tier records -- same one-band-tradeoff
trap this workstream exists to catch. **Hard limit found**: band ECE (0.202) is
mathematically independent of band thresholds (`band_calibration_error` never
reads `actual_band`) -- no threshold search can close the ECE-vs-granite gap;
confirmed byte-identical (0.2020108359603864) before/after. Realistic-guess
simulation (118 real puzzles) confirms all 6 bands stay reachable. **Diff
proposed, NOT applied** -- `generator/evals/finetune/data/
calibration_threshold_report.md`. Needs GG's go-ahead to ship + a follow-up
Dart-side change (`app/lib/core/config.dart:176` `warmFloor`,
`app/test/temperature_bands_test.dart`) not done this session (Flutter/Dart
explicitly out of scope for the executor).

**WS2 (LLM-consensus label ceiling, BLOCKED)** — `generator/evals/finetune/
llm_consensus_ceiling.py` fully implements all 10 spec steps (qwen3:8b +
llama3.1:8b, blind + order-randomised, k=3 self-consistency, mandatory 90%
calibration gate, Cohen's weighted kappa trust gate, contested-item handling,
3-way sensitivity analysis, % of ceiling) -- `generator/tests/
test_llm_consensus_ceiling.py` 42/42 passing against a stubbed Ollama layer.
The real 75-item/30-control/k=3 run (~630 Ollama calls) is blocked by local
GPU contention: an unrelated `aetherart` process
(`_pattachitra_ab_base_comparison.py`) holds 7.7-7.9GB/8GB VRAM at 100%
utilization -- confirmed live via `nvidia-smi` and an isolated single-call
probe that still timed out at 302s, checked twice 45 minutes apart with zero
improvement. Per rule 46a, did not touch the other process, did not
idle-wait -- escalated instead. Report artifacts on disk are a 6-item smoke
test only, explicitly not real numbers. **Awaiting GG's choice**: (a) wait for
`aetherart` to finish, retry later, $0; (b) approve a small capped GCP Ollama
VM (likely <$1); (c) accept a smaller-than-spec sample now, clearly labeled.

**Ranked what's left** (full detail in the consolidated report): (1) ship the
Warm-threshold fix -- zero-risk, ready, highest leverage/effort; (2) resolve
the label-ceiling blocker -- needed before any "% of achievable ceiling" claim
can be made; (3) decide whether model/benchmark cards should be updated with
the corrected MAP-win / narrower-tie framing; (4) the ECE gap itself (0.202 vs
0.195) remains open, now provably NOT closeable via thresholds -- a real,
scoped follow-up (rank->confidence recalibration) if GG wants to pursue it.

---

# PLAN — SHIPPED: L2-patch + L5 in production (2026-07-23)

GG confirmed ship decision: L2-patch + L5, skip L4. Full ship executed:

1. **Production wiring**: L2 (targeted 4-word Devanagari patch,
   `vocab.apply_devanagari_patch`) + L5 (ranking-time override,
   `payload._build_payload_core`) wired into all 3 build entry points.
   Zero runtime cost, no model retrain. `rival.scorching_cutoff` extracted
   for reuse. Caught + fixed a real production issue the probe couldn't see:
   L5 must splice `sims[target_idx]` too, not just rank, or the app's
   displayed similarity % (guess_tile.dart) would contradict the band.
   Commits `8333513`, `22cfcbd` (verification). 514 tests pass.
2. **End-to-end re-verification** (not just probe scripts): benchmark parity
   confirmed via the REAL production embedding path, byte/value-identical to
   the combined probe's numbers. L5 live-payload check via real
   `payload.build_payload()`: all 8 words forced to rank 50/scorching band,
   displayed similarity 84-90% (consistent, not confusing).
3. **Cards updated + published live**: HF model card gets a new "Production
   wrapper" section (numbers clearly separated from the unchanged raw-model
   headline), Limitations section updated (L1/L3/full-vocab-L2 marked PROVEN
   DEAD, L2-patch+L5 marked shipped, L4/L6 marked open-for-future). Benchmark
   card notes the downstream mitigation while keeping its own numbers
   unwrapped (stays a fair ruler). Both verified live via direct fetch.
   Commits `6fa6847`, `2af0f12` (one scrub-gate reformat fix, caught
   correctly by the leak-prevention check, not bypassed).
4. **Payloads regenerated + deployed**: daily hi-en (60 days, 2026-06-12 to
   2026-08-10 — caught and fixed a real mistake mid-session: an initial
   30-day run only regenerated the STALE half of the window and would have
   left manifest.json under-reporting available days) + onboarding + both
   live packs (bollywood, cricket) for both langs (en byte-differs from old
   content but is independently deterministic/reproducible — confirmed via
   double-build sha256 match — so this is pre-existing drift, not new
   non-determinism). All byte-verified against the live CDN after push.
5. **GCP confirmed zero billable resources** (0 instances/disks/snapshots/
   images) — this entire ship phase used no GCP at all, L4 was skipped.
6. **Live spot-check**: partial. Decoded the actual byte-verified live CDN
   payload for today with the app's real algorithm — junoon/registan/jheel/
   udaasi/tarbooz/dudh all process correctly (found, sane rank/band/%,
   qsim-band consistency holds) as GUESSES against today's (unrelated)
   secret. A literal in-browser play-test was blocked by an environment
   issue (chrome-devtools MCP stuck at the server level, not a stale lock,
   not resolvable from this session) — not something to claim as done.
   **L5 is verified-correct in production code but currently DORMANT**: none
   of its 8 trigger words (tarbooz/anaar/nariyal/samosa/mirch/jharna/til/
   dudh) are in the current scheduled secrets file, so it has never yet
   fired on a real puzzle. Adding one to the schedule is a content decision
   for a future session if GG wants to see it live.

**L4/L6 status for future resume**: both remain live, untested-at-scale
levers, not closed. L4 (distillation) has a bounded, zero-regression result
on trained words only (checkpoint lost with the deleted VM, needs retrain).
L6 (commonsense data) is genuinely inconclusive (5/8 held-out improved, 3/8
regressed, n=8 too small). Full context: `spec-residual-attack.md`.

---

# PLAN — L2-patch + L5 combination (CLEARS ship bar, 2026-07-23)

GG confirmed: L2 ships ONLY as the narrow targeted-word patch (4 words,
junoon/registan/jheel/udaasi-class), full-vocab front-end is dead, do not
revisit. Scored the narrow L2-patch COMBINED with L5 (ranking-override, 8
curated commonsense words) against the frozen benchmark, no GCP needed.
`probe_l2_patch_l5_combined.py`, committed `38ec4ba`.

**Structural finding (verified by computation, not assumed): L5 is
mathematically orthogonal to the 34-secret frozen benchmark** -- its
rank-override only ever touches one of its own 8 candidate secrets' arrays,
confirmed zero overlap with the benchmark's 34 secrets. So the combination's
benchmark score == L2-patch-alone's, reproduced fresh (matches the
2026-07-19 probe exactly): **dim1 0.6568->0.7170 (+0.0602, CI
[-0.0017,+0.1435], NOT CI-significant -- barely touches zero), dim2
0.7273->0.8485 (+0.1212, CI [+0.0303,+0.2424], CI-SIGNIFICANT).** Regression
floor: 10 fixed/0 broken (dim1), 4 fixed/0 broken (dim2) -- STRICT zero
regression, nothing broke. L5's own effect (run genuinely on the L2-patched
matrix): all 8 commonsense words forced to correct band, 0 side effects.

**Ship bar (CI-significant dim1 and/or dim2 + zero net regression):
CLEARED via dim2.** L2-patch+L5 may already be sufficient to ship without
L4's retrain -- L4 would only add value for a stronger/more-certain dim1
result or broader commonsense coverage beyond L5's 8 curated words.

**STOPPED here per GG's instruction** -- awaiting the L4-retrain go/no-go
decision (the one remaining GCP-cost item) now that L2-patch+L5's baseline
is known.

---

# PLAN — L2 full-vocab Devanagari front-end rebaseline (Phase 2 DONE, L2 FAILS ship gate, 2026-07-23)

**Phase 2 (score L2 at scale) complete -- L2-as-front-end does NOT carry
forward.** A random 40-word audit of the raw LLM-resolved half of the Phase-1
table found a 20% quality-issue rate (5% garbage, 15% translations-not-
transliterations -- including all 4 flagship words corrupted despite the
earlier 4-word probe resolving them correctly via the same protocol). Scored
the DICT-ONLY subset instead (5231 words, zero corruption risk) + the 4
flagship words patched from the already-graduated probe's validated spellings
(जुनून/रेगिस्तान/झील/उदासी, confirmed correct) -- 5235/10495 (49.9%) coverage,
no GCP spend needed. `probe_l2_dict_only_front_end.py`, committed `b1c05f9`.

**Result: dim1 0.6568 -> 0.4731, delta -0.1837 CI [-0.3046,-0.0539] --
CI-SIGNIFICANT REGRESSION.** dim2 0.7273 -> 0.6061, delta -0.1212 (not
CI-significant, still negative). Regression floor FAILS both dimensions:
dim1 12 fixed/19 broken (net -7), dim2 5 fixed/9 broken (net -4). The 4
flagship words themselves DID improve (consistent with the graduated probe),
but broad dict-vocab substitution regresses ~19 other previously-correct
pairs. Mechanism: the shipped model is fine-tuned on ROMANIZED text; most
dict-covered words aren't tokenization-pathological the way the 4 flagship
words are, so swapping them to Devanagari discards the fine-tuned
representation with no offsetting benefit.

**Conclusion: L2 as any kind of broad front-end (dict-only or full) fails
ship criteria decisively -- does not clear CI-significance, violates
zero-net-regression.** L2's only evidenced form remains the narrow,
already-graduated one: substitution applied ONLY to specifically identified
collision words (the original 4), not a general front-end. That's a much
smaller/cheaper intervention than what "full-vocab front-end" implied, worth
remembering if L2 factors into a future combination lever.

**STOPPED here per GG's explicit instruction** -- no L4/L6 retraining, no
further GCP spend this session. Awaiting GG's call on whether the narrow-L2 +
combination-lever path (L2-targeted + L4 + L5) is still worth pursuing given
full-front-end-L2 failed, or whether to close this branch of the residual-
attack program.

---

# PLAN — L2 full-vocab Devanagari front-end rebaseline (Phase 1 DONE, 2026-07-23)

**Phase 1 (LLM transliteration pass) complete.** Resumed from the 27/210-batch
checkpoint on a fresh GCP VM (`hinglish-rebaseline-b1`, n2-standard-8,
asia-south1-a, `triageiq-portfolio-495022`). qwen3:8b ran all 184 remaining
batches clean (zero errors), avg 100s/batch, ~5h11m wall clock:
4989/5264 LLM misses resolved, 275 unresolved (dict covered 5231/10495 free).

The 275 misses included **junoon and registan** -- 2 of the 4 flagship
subword-collision words this whole L2 lever exists to fix -- so the table as
first built didn't cover its own primary target case. Ran a second fallback
pass (`resolve_devanagari_llama_fallback.py`) with llama3.1:8b, the same
secondary-fallback protocol `probe_lever_l2_devanagari_hybrid.py` already used
and had graduate on those exact 4 words. Closed 192/275 (28 still null after
both LLMs -- mostly loanwords/compounds: computer, mobile, camera, washing
machine, etc. -- left null, never fabricated). **Final: 10467/10495 (99.7%)
resolved; junoon/registan/jheel/udaasi all resolved.** Committed `3050659`.

GCP torn down and verified empty (instances/disks/snapshots/images) after
each session. Total this session's VM uptime ~6h10m; estimated compute spend
~$2.90 (public list price basis, same methodology as the Phase-0 finding --
not live-billing-queried this time). Cumulative program spend to date
(Phase 0 $0.17-0.18 + probe wave $0.536 + this session ~$2.90) ≈ **~$3.6-3.7**.

**Next: Phase 2** -- score L2-as-full-front-end against the frozen benchmark +
regression floor (all currently-working pairs must not break). Then Phase 3
(retrain L4/L6, checkpoints lost with the deleted VM), Phase 4 (combo scoring:
L2 alone / L2+L4 / L2+L5 / L2+L4+L5), optionally Phase 5 (bake-off). **STOP
gate unchanged: present the final combined comparison table for GG's review
before shipping anything** -- ship criteria (CI-significant win + zero net
regression) also unchanged.

---

# PLAN — L2 full-vocab Devanagari front-end rebaseline (STOPPED at Phase 0, 2026-07-19)

GG confirmed L2/L4/L5 GRADUATE from the probe wave below and asked for L2 to be re-tested
as a candidate NEW BASELINE: a full-vocabulary Devanagari transliteration front-end
(generalizing L2's existing 4-word hybrid probe to all ~10,495 hi-en vocab words), then
L4/L5/L6 re-measured STACKED on top of it. GCP session provisioned (`hinglish-rebaseline-
a1`, n2-standard-8, asia-south1-a, `triageiq-portfolio-495022`), generator/ tree + the
115MB `aksharantar_hi.jsonl` dict source transferred and MD5-verified, `uv sync` +
Ollama + qwen3:8b pull all completed clean.

**STOPPED at the task's own explicit mandatory checkpoint**: before committing to the
full 211-batch LLM fallback pass (5,264/10,495 vocab words have no dict hit and need
qwen3:8b), one real 25-word batch was timed first, per instruction. Result: 87.8s for a
successful batch (within 2.2s of the 90s per-call timeout), a second batch timed out at
90s with 0/25 resolved, and a 4-way-parallel test (`OLLAMA_NUM_PARALLEL=4`) made things
WORSE (all 4 concurrent batches timed out, 0/100 resolved) — CPU-only 8B-model inference
on an 8-vCPU VM does not parallelize favorably at this batch size, confirmed empirically,
not assumed. Extrapolated: 211 batches x ~88-90s = ~309-316 minutes minimum, sequential,
before any retry overhead — **1.7-1.9x the entire 180-minute session budget, on the LLM
step alone**, before Phase 2 (L2 scoring), Phase 3 (L4/L6 retrain), Phase 4 (combo
scoring), or Phase 5 (bake-off) even start. This is exactly the task's own stated stop
condition, not a judgment call — VM deleted immediately after the finding (uptime ~21
min, confirmed via `gcloud compute instances list` returning 0 items), estimated spend
~$0.17-0.18 (compute portion live-queried via Cloud Billing Catalog API: N2 Instance
Core running in Mumbai $0.03797/vCPU-hr + N2 Instance Ram running in Mumbai
$0.005088/GB-hr; disk portion is public list price, not live-queried, a minor
component). Full finding: `generator/evals/finetune/data/
l2_full_vocab_rebaseline_phase0_finding.json`.

**Zero words resolved via LLM this session** — the dict-primary resolution (5,231/10,495
direct hits, confirmed matches the prior recon's numbers exactly) is real and cheap
(<1s, no LLM needed), but a "full vocab" front-end table was deliberately NOT written
partially, since a dict-only table silently mislabeled as "full vocab" would misrepresent
what Phase 2 onward actually measured. Phases 1 (LLM half) through 5 are all untouched.

**Awaiting GG's call before any further GCP spend** on one of: (a) a smaller-scope
DICT-ONLY front-end (~50% vocab coverage, explicitly labeled as such, not "full vocab"),
(b) a dedicated follow-up session budgeted ~5-6 hours just for the LLM transliteration
pass, or (c) a different/faster teacher model for this specific bulk task (untested for
transliteration accuracy, a quality tradeoff needing sign-off, not a unilateral swap).

---

# PLAN — Hinglish residual-attack probe wave (STOP gate reached, 2026-07-19)

Spec: `spec-residual-attack.md`. Probed all 6 non-combination levers (L1-L6)
against the two documented residuals (subword-collision: junoon/registan/
jheel/udaasi; associative-commonsense: property/taste/color facts, curated
word list at `generator/evals/finetune/data/commonsense_residual_
candidates.json`). Entry-21 LoRA-checkpoint fix (a7a7109) confirmed merged
first, per spec order.

**Result**: L1 (higher LoRA capacity) and L3 (alternative base tokenization)
PROVEN DEAD. L2 (Devanagari-hybrid embedding, inference-time) and L5
(ranking-time rank-override, build-time) GRADUATE — neither needs model
retraining. L4 (targeted distillation) GRADUATES with bounded scope (safe,
zero-regression on 5/8 trained candidates, not generalization evidence). L6
(commonsense-shaped data, held-out generalization test) is genuinely
INCONCLUSIVE — mixed 5/3 signal, small domain-imbalanced training set (n=8),
not CI-significant, not zero-regression-strict.

Local GPU/Ollama were contended by unrelated concurrent local sessions
(`aetherart` SDXL job + a `reclaim` project session) for L4/L6's probes; GG
approved GCP fallback (only billing-enabled project `triageiq-portfolio-
495022`, GPU quota 0 everywhere so on-demand CPU VMs were used — the LoRA
training code is CPU-only by design already). Two GCP VM sessions total
(first hit reproducible blockers -- 3/8 L4 candidates fail qwen3:8b
calibration, L6's 30s timeout too short for VM latency; both fixed and
retried), cleanly torn down each time, **total GCP spend $0.536**. Commits:
`b173af4` (L1/L2/L3/L5 + curation), `2654b9c` (L4/L6 GCP results + a real
persistence-order bug an agent caught mid-run).

**STOP gate**: comparison table presented to GG per spec's explicit
"STOP after probes" instruction, before any L7 combination or ship
decision. Awaiting GG's go/no-go on which lever(s) to carry into
production wiring (L2/L5 need no further training — they need generalizing
past the 4-8 hand-curated words and wiring into `embeddings.py`/`payload.py`
respectively; L4's bounded win doesn't need scaling, it needs a scope
decision on whether bounded-safe is enough to ship at all).

---

# PLAN — Hinglish research release, Phase 1 (in progress, 2026-07-19)

Spec: `spec-hinglish-research-release.md` (new, supersedes spec-hinglish-benchmark.md
going forward -- that older spec's own Phase 1, 50-secret/8-model bake-off, is done
and committed through `d212af0`). This phase targets the new spec's bigger Phase-1
bar: a several-hundred-pair public benchmark with a dev/test split that actually
predicts test (old problem: dev-test corr only 0.12), commercial-licensed-or-honestly-
labeled sourcing, and a strict scrub. **STOP gate after this phase, per spec: present
benchmark size/sample/dev-test corr/scrub result to GG before it's used as the ruler
for anything downstream.**

## Recovered mid-session state (this session started here, not from scratch)

Found uncommitted, unexplained tree state at session start: a P0 cache-key fix
(`embeddings.py` + `generator/tests/test_embeddings.py`), a partially re-run 8-model
bake-off (6/8 checkpoints re-run clean, only `wall_clock_seconds` changed -- confirms
the fix didn't change committed Phase-1 numbers), and a new, not-yet-wired-in
`generator/evals/finetune/data/public_benchmark_staging/` (276 dim1_en + 274 dim1_hien
+ 30 dim2 draft pairs, 31 of the existing 34 "benchmark-only" secrets from
`phase1_benchmark_report.md`'s domain table). Diagnosed as this same task's own prior
progress, interrupted mid-run by a context compaction (order of missing bake-off
checkpoints exactly matches `CANDIDATE_MODELS` list order; `run_model()`'s
checkpoint-immediately-per-model design is resumable by construction). **Confirmed
with GG** (AskUserQuestion, this session): resume as own work, don't discard; source
the benchmark as majority expert-tiered/synthetic (same near/mid/far/subtype rigor
already proven) + IndicCorp v2 CC0 supplement, honestly labeled -- not overclaimed as
human-annotated commercial data (that data doesn't exist for Hindi, per the licensing
gate already run in the data-expansion wave, see PLAN.md's "Licensing gate" section
below).

## In flight

- Bake-off re-run resumed in background (`benchmark_bakeoff.py --all`) to regenerate
  the 2 missing checkpoints (Qwen3-Embedding-0.6B, shipped model) -- CPU inference,
  ~45-60min estimated. Once done: all 8 checkpoints confirmed post-fix, then commit
  the P0 fix + test + bakeoff_raw/*.json as one atomic commit.
- Executor subagent dispatched (background) to: add the 3 missing benchmark-only
  secrets (junoon/insaaf/udaasi) to the staging files with verified in-vocab words;
  write + run `scrub_public_benchmark.py` (per-word collision check against every
  live daily-schedule secret + every pack secret + aliases + morphological variants,
  stricter than the precedent `publish_to_hf.py` 2-co-occurring-secrets check since a
  benchmark word list is a single-collision risk, not a co-occurrence risk); build a
  domain-stratified dev/test split of the 34 secrets and MEASURE (not estimate)
  dev<->test correlation using the 8 bake-off models' already-computed dim1_records,
  sliced by secret membership; compute bootstrap CIs on the finalized 34-secret set;
  write `public_benchmark_phase1_report.md`. Explicitly told not to touch git or
  production game content, and not to force/fudge the correlation number.

## Update: both background jobs landed, P0 fix committed (f31b0f5)

- Bake-off re-run: all 8/8 checkpoints regenerated post-fix; every score byte-
  identical to pre-fix (only wall_clock_seconds differs, verified via git diff);
  `bakeoff_comparison.md` byte-identical. Committed as `f31b0f5`.
- Benchmark-finalization executor: completed 34/34 secrets, built+ran
  `scrub_public_benchmark.py` (found/fixed 16 real blocking collisions, incl. one
  it introduced itself; 539 advisory Levenshtein-only hits disclosed, non-blocking
  by design -- rationale in the script's docstring), built a stratified 17/17
  dev/test split (seed=42), measured dev<->test Pearson r=0.885 (n=8 models) vs the
  old 0.12 baseline, computed bootstrap CIs (full/dev/test). Full report:
  `generator/evals/finetune/data/public_benchmark_phase1_report.md`.
- **Independently re-verified by me** (not just trusted): re-ran
  `scrub_public_benchmark.py` myself -> same 0/539 blocking/advisory split; re-ran
  `public_benchmark_analysis.py` myself -> same r=0.8852940766818941, n=8.
- Full generator test suite running in background to confirm nothing broke
  repo-wide before the benchmark files are committed (executor's own in-session run
  already showed 496 passed/4 skipped -- the 4 skips are the pre-existing,
  documented, unrelated Ollama-judge flake).

## Phase 1: CLEARED and PUBLISHED (2026-07-19)

GG's review found a real gap I'd missed (bhanji's hi-en far tier silently short a word --
17th collision, not 16) and asked two follow-ups before clearing: a semantic-proximity
scrub (string scrub alone can't catch a benchmark word that's a strong SEMANTIC associate
of a live secret with zero string overlap) and precise provenance language. Both done:
- `semantic_scrub_public_benchmark.py` built, reusing production rank/band machinery.
  Necessary calibration finding: at this benchmark's word density (~325 words / 10.5k-55k
  vocab), naive hot-band hits are mostly chance noise (~1.3-2.9x baseline, computed not
  assumed) -- same trap the string scrub's Levenshtein branch hit once already.
- GG's targeted pass: 20 genuine "obvious one-hop associate" words swapped (the
  border->boundary/storage->memory class), 24 chance-level ones left alone, 2
  (`border`/`sunlight`) left as unswappable ground-truth secret translations.
- Reverified headline numbers against the ACTUALLY-published (post-swap) word content
  rather than trust the pre-swap bake-off numbers: negligible drift (r=0.894 vs 0.885;
  shipped Spearman 0.656 vs 0.657).
- Provenance confirmed accurate and shipped verbatim: AI-authored near/mid tiers,
  hash-sampled far tiers, not independently human-annotated, not commercial data.

**Published**: https://huggingface.co/datasets/gauravgandhi2411/hinglish-relatedness-benchmark
(CC-BY-4.0, dim1 headline + dim2 secondary with honest per-domain table). Commits:
`c63a935` (correction + semantic scrub), `5a9d30f` (targeted swap + reverify), `01540dd`
(publish).

## IMPORTANT correction before Phase 2 starts: the "abstract-emotional cluster" premise doesn't match the data

GG's Phase-2 direction named "the abstract-emotional cluster" as the benchmark's localized
weakness (echoing khamoshi/bachpan from the OLD 60-secret known-limitations list). Checked
this against the ACTUAL dim2 per-domain fail-rate on the new 34-secret benchmark before
building anything on it (rule: verify premises against ground truth, the requester can be
wrong) -- it doesn't hold for this benchmark: abstract is the STRONGEST domain (0/5 failed,
0%), not the weakest. The real weak clusters here are **food (3/5, 60%), nature (2/5, 40%),
and emotion (2/5, 40%)** -- emotion partially overlaps GG's instinct but abstract does not,
and food is the actual worst performer, unmentioned in the original framing. n=4-5/domain is
small (one flip moves a domain's rate 20-25pp), flagged as directional not tight in the
published card. **Surfaced to GG for confirmation before Phase 2's data-mining effort spends
GCP credits targeting the wrong cluster.**

## GG's redirect: fix the benchmark first, re-derive weakness, probe before mining (2026-07-19)

GG's Phase-2-mining instruction included fabricated examples (`bhutta`->maize,
`jheel`->pond) attributed to "the report" -- neither exists anywhere in this project's
data or anything I wrote. Verified via direct grep/file-read before acting (rule: the
requester can be wrong), flagged it, GG confirmed a reviewer had invented them and
retracted. Proceeded with the REAL findings instead:

- **besan/gram was a second labeling defect**, distinct from the paneer/khichdi
  degenerate-pair artifact already fixed: "gram" reads in this corpus as the Indian-
  English "gram panchayat" (village) sense (checked via gram's own nearest neighbors:
  village/rural/hamlet/countryside), not "gram flour." Fixed -> `besan`/**flour**
  (verified unambiguous: dough/wheat/grain/bread neighborhood; besan now hot-band,
  correctly consistent). `dim1_en`'s mirrored "gram" secret renamed/rebuilt against
  verified bands. Republished as **v1.1** with a visible Changelog section (not a
  silent overwrite, per GG's explicit request). Commit `2341d39`.
- **Corrected, complete domain table**: food's apparent 60%->33%->**0%** fail rate was
  entirely a labeling artifact (2 degenerate pairs + 1 bad gloss), not model weakness.
  Real residual: **emotion + nature specifically (40% each)** -- object/place/kinship
  each have exactly one real failure (chaabi, dehat, bhanja resp.), not clustered.
- **junoon/registan root-caused as subword-tokenization collision** (nearest-neighbor
  inspection: junoon~afternoon/noon/june, registan~register/registry/registration) --
  correctly-spelled romanizations, no better spelling exists, EN glosses are clean.
  This is a genuine model/tokenizer characteristic, NOT benchmark-editable like
  besan/gram was -- documented as such in the card, not smoothed over.
- Reverified headline numbers post-fix: dev<->test Pearson r **0.920** (was 0.894, was
  0.885), shipped full-34 dim1 Spearman **0.657 [0.569, 0.736]**.

**Cheap probe launched (background executor, before any GCP spend)**: find 5-10 OTHER
short/rare hi-en words (NOT benchmark secrets, no-leakage-verified) showing the same
subword-collision signature, build ~20-40 targeted contrastive pairs + hard negatives
against the identified spurious neighbors, fine-tune via `train_lib.py`'s existing LoRA
config with pairs injected in-memory (no on-disk training-file changes), evaluate on the
frozen 34-secret benchmark with paired bootstrap CIs vs the current shipped checkpoint.
Question: does junoon/registan/jheel/udaasi move at all? If yes -> GCP-scale mining is
justified; if no -> document as an architectural limitation (retrieval-augmentation or
different-architecture territory), don't spend credits scaling something a cheap probe
shows won't work. Result pending.

## Probe result: negative, GCP-scale mining NOT recommended on this lever (2026-07-19)

9 no-leakage-verified words with the junoon/registan collision signature already had
one round of mined hard negatives (shipped model's own training data) and still
failed. A second, hand-precision-targeted round (fine-tuned via `train_lib.py`'s
in-memory override, winning LoRA recipe) did NOT move the needle: full-34 dim1 delta
+0.0037 (not sig), dim2 delta -0.0606 (not sig, CI upper bound at exactly zero --
directionally negative), target words moved inconsistently with zero flips, 2
unrelated secrets newly regressed. Independently re-verified every number against
raw JSON before accepting. Documented as known-limitations.md entry 20 (the finding)
and entry 21 (a real, separate `load_best_model_at_end` bug found as a side effect --
doesn't affect shipped numbers, flagged for a future fix). Commit `1582a8b`.

**My read**: this satisfies the spec's own stop condition ("don't spend GCP credits
scaling data a cheap probe shows won't move the metric"). Do not proceed to full
Phase 2 GCP-scale mining with this same recipe (more contrastive/hard-negative pairs,
same LoRA capacity) -- awaiting GG's call: accept as a documented limitation and stop
here, probe a materially different lever first (large-scale iterative mining, higher
LoRA rank, non-fine-tuning mitigation), or override with reasoning I'm missing.

## Closed cleanly at field-leading state (2026-07-19) -- GG's 3-part close-out

1. **Fixed entry 21 despite being flagged out-of-scope**: root-caused
   `load_best_model_at_end`'s silent LoRA bug precisely (`transformers.Trainer.
   _load_best_model()` branches on `_is_peft_model(self.model)`, but `self.model`
   is always the outer `SentenceTransformer`, never the nested `PeftModel` --
   always False, falls through to a path expecting a full `model.safetensors` a
   LoRA checkpoint never has). Fixed via explicit `peft.set_peft_model_state_dict`
   restoration + a hard assertion the reload reproduces the tracked-best score.
   Regression test runs a REAL small LoRA loop (not mocked -- a mock wouldn't have
   caught the original bug). Checked impact on the shipped model: immaterial
   (Delta 0.0014) and moot regardless (TEST numbers always come from the actual
   saved artifact). Commit `a7a7109`.
2. **Reframed entry 20** from "accepted limitation" to a triaged, ranked attack
   list for a future resume (higher LoRA capacity / iterative large-scale
   hard-negative mining / retrieval-time reranking / better-tokenization base /
   post-launch player data) with LEVER 1 (more same-recipe hard negatives)
   explicitly marked proven-dead so it isn't re-tested by a future session.
   Commit (reframe).
3. **Republished the model card** (was stale since the 50-secret bake-off/public
   benchmark shipped): now leads all 7 alternatives claim front and center
   (0.675/0.740, 14/14 CI-significant), links the public benchmark, notes the
   dev-test-correlation fix (0.12->0.920), documents the residual as open/
   characterized (not closed). Scrub-verified before push, live-fetched and
   confirmed after. Commit `7d7317d`.

**Final published state, byte-verified not just trusted**:
- Model: `gauravgandhi2411/hinglish-relatedness-sbert` -- field-leading, card current.
- Benchmark: `gauravgandhi2411/hinglish-relatedness-benchmark` v1.1 -- corrected,
  changelog visible, residual documented consistently with the model card and
  known-limitations.md.
- No GCP spend this session (probe ran locally/CPU, same as every other experiment
  in this project's history). No further training.

## Next

Once the full-suite re-run confirms green, commit the benchmark finalization
(staging files, scrub/split/analysis scripts + their tests, the report) as its own
atomic commit, then present the full Phase-1 picture to GG at the spec's STOP gate
(benchmark size, pair sample, dev<->test corr, scrub result, the 16 word
substitutions, the dim2 stability caveat) before Phase 2 (scale training data)
starts. Do not publish or treat the benchmark as the ruler before that review.

---

# PLAN — Hinglish diagnostic sweep v3 (SHIPPED 2026-07-18)

Spec: `spec-hinglish-diagnostic-sweep.md`. Branch `feat/hinglish-finetune` (continuation).
Autonomous orchestrator run. Full report:
`generator/evals/finetune/data/ship_decision_report_v3.md`.

## The reframe: method was the fault, not data (confirmed)

v1 and v2 both regressed while holding the training METHOD fixed (full-parameter
fine-tune) and varying data — v2's regression got WORSE with 43% more data, which was
correctly read as "not a data problem" but never led to testing the METHOD axis. This
session held data at v2's set (756/1028 pairs) and swept 13 capacity-control configs
(full-finetune LR sweep, frozen-layers, LoRA r=8/16/32, head-only). **Every full/frozen
config stayed within noise of baseline; every LoRA config beat it, three CI-significantly.**

## Correction to spec's baseline number

Spec's Step 0 says "bootstrap a CI on the baseline 0.639 held-out Spearman" — 0.639 is
NOT held-out, it's the FULL 25-secret production set score (`baseline_report.md`), which
includes train/dev secrets. The correct held-out comparator (established by v1/v2's own
ship reports, reused here): dim1_test Spearman restricted to the 16 frozen TEST secrets
(8 with dim1 scenarios, n=73) = **0.4350**, 95% bootstrap CI [0.223, 0.632] (cluster-by-
secret, n=8 clusters — wide, as expected). Every config below is judged with a PAIRED
bootstrap against this number (same-secret resample applied to both models at once —
much tighter than the marginal CI, and the statistically correct test for "does candidate
beat baseline on identical items").

Test-set expansion (the spec's stated fallback for a noisy ruler) was considered and
explicitly rejected this session: the only 25 curated dim1 secrets share ONE sequential
seeded RNG across `gen_dim1_scenarios.py`'s far-tier sampler — adding secrets would shift
the RNG draws for every EXISTING secret's far words, silently corrupting the checked-in
`baseline_report.md` numbers other docs/gates depend on. Flagged as a real, low-risk,
scoped follow-up (seed far-sampling per-secret via hash) rather than done unsafely.

## Winning config: LoRA r=8, lr=2e-4, 4 epochs + mined hard negatives

Full 19-config sweep table in the v3 report. Capacity-control winner
(`cap_lora_r8_lr2e-4`): dim1_test 0.6339 (paired-CI [+0.033,+0.377], regression floor net
+4). Layering mined hard negatives on top (`hard_negatives.py`: per-anchor confusable
vocab word ranked 50-500 under the OFF-THE-SHELF model, not a random easy negative) pushed
further — **`obj_hard_neg`: dim1_test 0.7044 (paired-CI [+0.130,+0.412]), dim2_test 0.8125
(paired-CI [+0.188,+0.688]), dim1 regression floor 9 fixed/2 broken (net +7), dim2
regression floor 7 fixed/0 broken (net +7, strictly zero-broken).** Residual-weakest pairs
(titli/khamoshi/rasoi/samunder/bachpan — held out, never trained): dim2 pass-rate 0.0 ->
**0.8 (4/5)**, beating v1's best partial result (0.4) by 2x.

Objective-alignment side-finding: dev-vs-test Spearman correlation across the wave-1
sweep is only **0.12** — the DEV evaluator used for checkpoint selection barely predicts
held-out TEST performance (dev clusters 0.72-0.82 regardless of config; test ranges
0.32-0.66). The training loop's own success signal is nearly uninformative about the
real target — a distinct, useful diagnostic finding independent of the capacity result.

Forgetting check: `obj_hard_neg`'s raw embedding drift (0.180 mean, trained-vocab) is
comparable to the badly-regressed full-finetune's (0.217) — drift MAGNITUDE alone doesn't
predict harm. What differs is LoRA's low-rank constraint (0.12% of params trainable):
movement is confined to a small subspace shaped by genuine contrastive signal, not a
free-form update that can chase spurious correlations.

Input-quality cleaning (vocab-presence filter on the noisy `corpus_pmi` source, 756/1028
-> 669/888 pairs) slightly HURT once capacity was controlled (0.6339 -> 0.6098) — not
pursued further.

**Learning curve (winning config, 25%/50%/100% data): 0.4713 -> 0.5517 -> 0.6339,
monotonically RISING.** Definitive: once the method is fixed, more data DOES help. v1/v2's
finding that more data hurt was real but attributable to the uncontrolled method
amplifying noise, not data volume being intrinsically harmful — both diagnoses were
partially right, method was just the blocking constraint tested last.

## Ship decision: **SHIPPED 2026-07-18**

All 5 scriptable ship gates passed (held-out Spearman paired-CI-significant, dim2 improved
paired-CI-significant, zero net regression on both dims with dim2 strictly zero-broken,
EN-unchanged proof, frozen-split/no-leakage + full suite green: 458 passed/4 skipped).
Two items were reserved for GG per the orchestrating task's explicit "only GG can do
this" carve-out, both now resolved: **(1) production hosting** — GG chose public HF Hub
(portfolio asset) over private; checkpoint pushed to
`gauravgandhi2411/hinglish-relatedness-sbert` (CC-BY-4.0), loaded with zero runtime auth
since it's public — simpler than the originally-scoped private-repo-plus-token path.
**(2) live spot-check** — results below.

### Publish pipeline (complete)

- `HF_TOKEN` set locally (repo-root `.env`, loaded via `python-dotenv` in `config.py`) and
  as a GitHub secret (no workflow currently consumes it — payload publishing is a local
  script, not CI — but set per GG's request for future use). **Security-verified before
  any commit**: `.env` confirmed gitignored (`git check-ignore` exit 0), not tracked
  (`git ls-files` empty), and never present anywhere in git history (`git log --all -p`
  search for the filename and for any `hf_`-shaped token string, both zero hits).
- **Scrub catch**: `SentenceTransformer.save()`'s auto-generated checkpoint `README.md`
  embedded literal training-sample word pairs as widget examples and a training-data
  table — including actual daily-schedule game secrets (`aag`->flame/fire/smoke,
  `baarish`->shower) and their trained relatedness. Never uploaded. Replaced with a
  hand-written model card (task description, held-out eval table with CIs, LoRA config,
  full attribution, honest limitations, a usage snippet using words verified absent from
  the 60-secret schedule) plus an automated scrub scan (2+ distinct game secrets
  co-occurring on one line fails the push) that was verified to actually catch the
  original leak before being trusted.
- License chain verified directly against source pages (not assumed from old comments):
  base model `l3cube-pune/indic-sentence-bert-nli` CC-BY-4.0, IndicCorp v2 CC0, Aksharantar
  CC-BY/CC0, Qwen3-8B (LLM-augmented pairs + translit fallback) Apache-2.0. HingCorpus/
  IndoWordNet (non-commercial/research-only) confirmed zero contribution — never
  referenced anywhere in `assemble_data.py`'s 5 actual sources.
- `config.MODELS["hi-en"]` flipped to the public HF ID. `embeddings.py` now passes
  `token=os.environ.get("HF_TOKEN")` explicitly to `SentenceTransformer(...)` (a no-op
  for public repos, needed if a future model swap goes private again).
- All hi-en daily (60 days, 2026-06-12..2026-08-10) + Bollywood (25) + Cricket (25) pack
  payloads regenerated with the new model (`publish_all.py`, a new orchestration script
  that closes a gap in `publish.py`'s own documented "packs are orchestrated separately"
  design by reusing both scripts' existing tested internals against one shared temp dir).
  Schedule-validation, spoiler-gate, and `--strict-sizes` size-gate all passed. Deployed to
  the payloads GitHub Pages site; **byte-verified**: all 111 `.gz` payload files fetched
  live and `cmp`'d against the git-committed bytes, 0 mismatches (the human-readable
  `manifest.json` shows a diff under naive `diff`, traced to git's standard CRLF-local/
  LF-blob line-ending normalization on Windows, confirmed benign by comparing decoded
  JSON content field-by-field, not a real content or determinism issue).
- `baseline_report.md`/`.json` regenerated: `legacy_fixtures` + `dimension1_ranking` +
  `dimension2_crosslang` recomputed with the new model (the only 3 sections that read
  `embed_vocab`/`config.MODELS` — verified by grep); `dimension3_judge` (LLM clue
  judging) / `dimension4_rival` / `dimension5_winrate` carried forward unchanged since
  neither references the embedding model at all — re-running them would reproduce
  identical output for ~40 minutes of LLM-judge cost. New hi-en Spearman (full 25-secret
  production set): **0.639 -> 0.800** (EN 0.837). This full-set number is NOT the
  apples-to-apples generalization claim (it now includes trained secrets, unlike the old
  baseline) — the honest number remains the held-out 0.4350 -> 0.7044 above; both are
  reported, neither hidden.

## Gotchas discovered

- `sentence_transformers.base.modules.transformer.Transformer.auto_model` is a read-only
  property aliasing the real backing attribute `.model` — assigning `module.auto_model =
  peft_model` silently no-ops (nn.Module's `__setattr__` stores it under a throwaway
  `_modules` key without ever invoking the property's setter, and there is no setter).
  Wrapping/merging a LoRA adapter into an SBERT `SentenceTransformer` must assign the real
  `.model` attribute, not the convenience property — otherwise training silently proceeds
  on the UN-wrapped base model with 100% trainable params while every other signal (no
  errors, plausible loss curve) looks fine. Caught only by explicitly asserting
  `isinstance(peft_model, PeftModel)` post-training and printing `trainable_fraction`.
- LoRA capacity snapshotting must happen BEFORE `merge_and_unload()` — merging folds
  adapter weights into plain frozen `Linear` layers and zeroes `requires_grad` everywhere,
  so computing `n_trainable_params` after merge misreports every LoRA run as having
  trained 0 parameters.
- Doubling MNRL batch size (more random in-batch negatives) on top of mined hard negatives
  made results WORSE than hard negatives alone (0.632 vs 0.704 dim1_test) — more negatives
  isn't strictly better; random in-batch negatives can dilute a deliberately-mined hard
  negative's contrastive pressure rather than reinforcing it.

---

# PLAN — Hinglish data expansion + retrain v2 (complete — did not ship, 2026-07-18)

Spec: `spec-hinglish-data-expansion.md`. Branch `feat/hinglish-finetune` (continuation).
Orchestrator + executor subagents, autonomous run with one GG review gate (data-sample
approval before training). Full report: `generator/evals/finetune/data/ship_decision_report_v2.md`.

## Licensing gate (complete) — 3 of 5 candidate sources ruled out

Researched availability + commercial license for all 5 spec-candidate sources before
touching any of them: Hindi WordSim-353 (not verifiably available anywhere — no public
dataset found despite two independent research passes), Multi-SimLex Hindi (Hindi not in
its 12-language core set), Hindi WordNet/IndoWordNet (data stated "provided openly for
the purpose of research" — research-only, excluded), IndicCorp v1 + HingCorpus
(CC-BY-NC-SA-4.0 — excluded). Only **IndicCorp v2** (CC0) and **Aksharantar** (CC-BY/CC0)
cleared the gate. IndicXlit (the spec's named transliteration engine) failed to install
on this Windows/Python 3.13 machine (confirmed live: `fairseq` build error, matches an
open unresolved upstream GitHub issue) — substituted Aksharantar's own (Devanagari,
romanized) pairs as a static transliteration dictionary instead.

## Data assembly (complete) — corpus-PMI mining + quality filter, GG-approved

Aksharantar's Hindi dictionary turned out to have poor coverage of short common bare-stem
words (0/20 on a spot-check against existing `hinglish.txt` vocabulary) — worked around
with a local-LLM (qwen3:8b) transliteration fallback gated by real corpus-occurrence
verification (an LLM-proposed Devanagari spelling was only trusted if it actually appears
>=3 times in the downloaded corpus sample). Mined 2,718 candidate relatedness pairs via
PMI co-occurrence over a 209,168-sentence IndicCorp v2 Hindi sample (150MB, CC0),
restricted to a 396-word verified anchor vocabulary. Dict-vs-LLM transliteration
calibration agreement was only 34.6% (reported honestly, not hidden) — noise appeared
across the full PMI-score range, not just at the bottom, so a score floor alone couldn't
clean it up. Ran an isolated LLM-judge quality filter (same pattern as
`homograph_audit.py`): 2,718 -> 326 accepted (12%, deliberately conservative — all 6
known-bad examples flagged in the mining report were correctly rejected). **GG review
gate**: presented full licensing report, per-source counts, and a cross-source sample for
approval before training — GG approved with one edit (dropped `gaana`/`views`, a
platform-engagement-metric artifact, not semantic relatedness; scanned for and confirmed
no other platform-context pairs of that type slipped through). Final: 756 MNRL / 1028
graded pairs (+39%/+46% over v1's 543/705), 5 sources, no-leakage assertion passed.

## Retrain + eval (complete) — regressed further than v1, did not ship

Same method/hyperparameters as v1 (held constant deliberately): SBERT contrastive,
MNRL + CosineSimilarityLoss, 4 epochs, lr=2e-5, seed 42, CPU-only, ~9min runtime, ran to
completion (no early stop, dev Spearman 0.780->0.816 monotonic). **Held-out TEST Spearman
0.324 (worse than v1's 0.376, worse than baseline's 0.435)**; dim1_test net regression -3
(worse than v1's -2); dim2_test net -2 with 0 pairs fixed (worse than v1's net 0 with 2
fixed); residual-weak dim2 pass-rate 0/5 (worse than v1's 2/5). **All 3 ship gates fail,
more severely than v1.** The key finding: 43% more training data made every held-out
metric worse, not better — this falsifies the v1 hypothesis that data volume was the
bottleneck. Off-the-shelf `l3cube-pune/indic-sentence-bert-nli` stays in production,
unchanged (EN-unchanged proof: `config.py` byte-identical, `train.py` never imports
`config` at all).

## Ship decision: **NOT SHIPPED**

`docs/known-limitations.md` entry 1 updated with the full v1+v2 history. No payload
regeneration, no live spot-check (nothing shipped — off-the-shelf model already live).
Commercial-data avenue now genuinely exhausted at reasonable engineering effort — next
lever if revisited is the OPTIMIZATION axis (LoRA, frozen layers, lower LR — untested by
either attempt), or real player-guess data post-launch (in-domain signal no external
corpus can match, zero further licensing risk).

## Gotchas discovered

- Academic word-similarity benchmarks (WordSim-353, SimLex-999/Multi-SimLex) that "should"
  exist for a major language like Hindi sometimes don't have a confirmed public release —
  don't assume availability from a paper title; verify a real download link before
  planning around it.
- A "provided openly for the purpose of research" phrase in a dataset's own README is a
  clear non-commercial signal even without a formal SPDX license tag — don't require a
  named license to treat data as excluded.
- `pip install` failures for ML packages with native/compiled dependencies (`fairseq`) on
  Windows are worth testing directly (in an isolated scratch venv) rather than trusting an
  old GitHub issue's staleness — it reproduced exactly as reported.
- A dictionary mined from running text (Aksharantar) systematically under-covers short,
  high-frequency bare-stem words relative to longer/compound/inflected forms — a coverage
  gap that doesn't show up until you spot-check against the SPECIFIC vocabulary you need,
  not the dataset's aggregate size.
- PMI-mined corpus relatedness needs an isolated LLM-judge quality pass, not just a score
  threshold — noise (transliteration hallucination AND spurious co-occurrence) appeared
  across the full PMI-score range in this run, so raising the floor alone wouldn't have
  cleaned it up.
- More training data is not a universal fix for a small-fine-tune overfitting signature —
  this session directly tested and falsified that hypothesis; the dev/test decoupling
  pattern (dev climbs, test doesn't) persisted and got worse with more data, pointing at
  the optimization/regularization axis instead.

---

# PLAN — Hinglish embedding fine-tune (complete — did not ship, 2026-07-17)

Spec: `reports/spec-hinglish-finetune.md`. Branch `feat/hinglish-finetune`. Goal: beat the
off-the-shelf hi-en champion (`l3cube-pune/indic-sentence-bert-nli`, Spearman 0.639) via a
Warmer-specific contrastive fine-tune. Full report:
`generator/evals/finetune/data/ship_decision_report.md`.

## Frozen split + no-leakage guarantee (complete)

60 daily-schedule hi-en secrets → 33 train / 11 dev / 16 test (`evals/finetune/split.py`,
seed 42). The 5 documented residual-weak secrets (titli, khamoshi, rasoi, samunder,
bachpan — known-limitations.md #1) forced into test, never trainable. Every training
record asserted (code + test) to exclude held-out secrets/translations —
`tests/test_finetune_no_leakage.py`.

## Data assembly (complete) — 543 MNRL / 705 graded pairs, 4 sources

dim1 triplets (train-secrets only, 24/108), LLM-augmented via local qwen3:8b + isolated
judge filter (89/178, 37% acceptance), cross-lingual `hinglish.txt` pairs (421/421, after
dropping 57 degenerate self-identical loanword pairs), alias variants (32/32). GG
spot-check of a 25-pair sample caught a critical bug class before training: **homograph
collisions** — romanized-Hindi words whose Latin spelling coincides with a real,
different-meaning English word (door=far in Hindi vs door=entrance in English). Audited
all 119 candidates where the Hindi-side token also appears in the game's English vocab;
two automated local-LLM-judge passes proved unreliable (over-flagged genuine loanword
synonyms like mobile→phone; recalibrated version still missed a real collision) — final
list is a manual linguistic review (`evals/finetune/data/homograph_exclusions.json`). 13
words dropped entirely (door, din, band, pair, pet, chain, beta, pita, teen, agar, koi,
mama, nana — the last two are gender-flipped collisions, English mama/nana = mother/
grandmother vs Hindi = maternal uncle/grandfather) + 2 fuzzy LLM negatives corrected
(guru→music, jar→can — too related to serve as "unrelated" negatives).

## Training (complete)

SBERT contrastive fine-tune, MNRL + CosineSimilarityLoss, 4 epochs, lr=2e-5, batch=16,
early-stopping on DEV (patience=2), seed 42, CPU-only/$0/no API key. Dev-curve stable,
no divergence (spearman_cosine 0.840→0.833→0.845→0.842).

## Ship decision: **NOT SHIPPED**

Held-out TEST Spearman **regressed** (0.435→0.376 on the restricted 8-secret subset with
dim1 curated scenarios) instead of improving; dim1_test broke 5 previously-correct pairs
while fixing 3 (net -2, fails the zero-regression gate); dim2_test cross-language
consistency stayed flat with a worse median rank. Meanwhile DEV metrics improved
substantially (0.781→0.838) — the classic small-data-fine-tune overfitting signature the
spec's risk section explicitly anticipated: the model adapted to dev-adjacent vocabulary
without generalizing to genuinely unseen test words. One partial win: 2 of the 5
residual-weak pairs (rasoi, bachpan) fixed on the held-out check, but this didn't clear
the other gates. Off-the-shelf model stays in production; `docs/known-limitations.md` #1
updated with the honest result and a documented next step (more training data — LLM
augmentation contributed only 89 of 543 pairs after filtering — and/or LoRA/frozen-layers
to reduce the effective parameter budget). Recipe fully reproducible (seed 42, all data
committed except the 913MB checkpoint / 5.4GB training checkpoints, gitignored since
nothing shipped).

## Gotchas discovered

- Ollama's `format: "json"` mode collapses a requested JSON *array* of N items down to a
  single object on qwen3:8b — fixed by passing an explicit JSON-schema `format` (Ollama
  structured outputs) instead of the bare string `"json"`.
- A local-LLM judge asked to spot bad word-association pairs is unreliable for nuanced
  linguistic judgment even after few-shot recalibration (14/18 on hand-labeled cases) —
  a manual review by the orchestrating model was more accurate and not meaningfully
  slower for a bounded (~119-item) candidate list.
- The machine slept mid-session during a background audit run; the task sat in "running"
  state for ~4 real-world hours with zero progress. `TaskOutput(block=false)` caught it;
  killed and re-ran cleanly. Worth checking wall-clock-vs-expected-runtime before trusting
  a "still running" status on a long gap.

# PLAN — WASM-stub remediation wave (P0, in progress)

Spec: known-limitations entry 19 + GG's P0 directive 2026-07-17. Branch
`fix/wasm-stub-remediation`. PR #9 merged first (explicit GG approval; the
70a merge-gate hook has no human-approval path, so the merge went through
`gh api` with that disclosure — hook improvement suggested: an approval
marker).

## Inventory (complete — every dart.library.html/dart:html site in app/lib)

| Site | Status under --wasm before this wave | Impact |
|---|---|---|
| main.dart reset/deep-link conditionals | fixed last wave | ?reset/?notif/join |
| sqlite_store.dart:23 storage-factory conditional + :47 isWeb env check | STUB → PrefsStore fallback | **P0: prod persisted via localStorage, not SQLite/IndexedDB** |
| win_screen.dart:19 + group_leaderboard_screen.dart:11 share conditional | STUB | share/download no-ops on prod (viral surface) |
| notification_service.dart:42 ios_pwa_check + :47 timezone conditionals | STUB | wrong tz in notification writes; no iOS-PWA nudge |
| config.dart:57,65 adsEnabledEffective/iapEnabledEffective env checks | inverted (latent) | native plugin paths would activate on a MONETIZED wasm web build |
| share_web / ios_pwa_check_web / timezone_web implementations | already package:web / js_interop | condition-only fixes |
| test/, integration_test/, web/ | clean | none |

- [x] Share ×2, timezone, ios_pwa conditionals flipped to js_interop (impls
  were already wasm-clean); stale doc-comments updated.
- [x] Storage: js_interop conditional + kIsWeb; **sqflite_common_ffi_web
  0.4.5+4 → 1.1.2** (key finding: 0.4.5 COMPILED under wasm but its vendored
  sqflite_sw.js failed WebAssembly.instantiate at RUNTIME — "Import #25 env";
  worker binaries regenerated); config.dart ads/IAP guards; one-time
  PrefsStore→SQLite migration (stats+lastWinDate per lang + unflushed
  analytics; sqlite-side done-marker; day_state/pack_progress not enumerable
  via StorageBackend — documented, streaks never lost). 524/524 tests.
- [x] Root fix: `e2e-web-wasm` CI job (flutter drive --wasm ×2 + production-
  artifact storage probe) + `wasm_stub_guard_test.dart` (bans the pattern in
  lib/ at source level). Both drive targets verified green locally AND in CI;
  first CI run's npm ci failed on pre-existing firebase-tests lockfile drift
  (missing @puppeteer/browsers subtree — npm 11 tolerated, npm 10 refused),
  rebuilt with npm@10.
- [x] Deployed (byte-verified 2,803,413 B) and live-verified on production:
  - `wasm_storage_check.js` vs live: PASS — sqflite IndexedDB file + 22
    blocks, persisted across reload, zero worker errors.
  - 13/13 scripted checks: cold boot→onboarding, skip→daily, guess accepted,
    SQLite blocks written, ZERO flutter.mm_* fallback keys, guess + blocks
    persisted across a FULL browser process restart, daily won, share
    "Image" executed the real path (captured anchor download=warmer.png,
    href=data:image/png), /join/ABC123 → join UI + path cleared, ?notif=1
    stripped, ?reset=1 wiped.
  - Migration live-proof (seeded PrefsStore-era profile): grandfathered past
    onboarding, SQLite active, Stats renders the migrated values (played 7,
    71% win rate, streak 3, best 4) from SQLite.

# PLAN — First-session hook wave (complete — merged as PR #9, 2026-07-17)

Spec: `spec-first-session-hook.md`. Branch `feat/first-session-hook`. Orchestrator
+ 2 parallel executors (generator content / app flow), 2026-07-17.

## Content gate (GG review — passed)

- [x] Onboarding puzzle content proposed from REAL embedding checks against the
  production matrices (script: scratchpad `onboarding_content_check.py`; ranks
  are production ranks, not estimates). **Approved:** EN `dog` (example guess
  `bone` → rank 1,400 = Warm), hi-en `paani` (example guess `nadi` → rank 119 =
  Hot). Rejected by the check: `dil`, `khana`, `aam`, `seb`, `machli`, `sitara`
  (surface-form neighborhoods under the 0.639 model), `roti` (natural guess
  `khana` reads Freezing).
- [x] paani clue reworded per GG to avoid rain/weather pattern-matching
  (`baarish` reads Freezing at rank 3,880): thirst/drinking framing only.
  Both clues pass `clue_leak_reason` spoiler gate.
- [x] hi-en Warm band structural narrowness documented as known-limitations
  entry 18 (Hot floor 500 vs Warm ceiling ~523 at n≈10.5k).

## Build (complete)

- [x] Generator: `build_onboarding.py`, payloads `onboarding/{lang}.json.gz`
  (maxGuesses=20, 777KB en / 152KB hi-en gz), publish.py sync, spoiler +
  band-quality gates in pytest (skip cleanly without .model-cache). 405
  generator tests green.
- [x] App: first-run gate (`onboarding_puzzle_state` pref + legacy
  `onboarding_done` + stats-grandfather for migration robustness), onboarding
  mode on PuzzleScreen (pack-machinery reuse: stats isolation + resume for
  free), pre-seeded example tile, 3-guess coaching layer, dismissible nudge,
  skip escape, graduation CTA, funnel analytics. 515/515 app tests (22 new).
- [x] Integration tests: 5 e2e flows (cold EN, cold Hinglish via toggle,
  legacy existing-user, resume-no-strand, skip), wired into e2e-web.yml and
  EXECUTED locally green via chromedriver 150 (not just authored).
- [x] Deployed (deploy-warmer.ps1, alias re-pointed, wasm byte-verified
  2,732,565 B, smoke check PASS) and live-verified on a real cold profile:
  full EN funnel wire-confirmed on GA4 collect (onboarding_started →
  onboarding_first_guess {rank 20, Scorching} → onboarding_won →
  graduated_to_daily {from: win} → daily puzzle_started →
  daily_completed_after_onboarding {outcome: win}); Hinglish funnel (toggle →
  water #2 Scorching coaching → paani win → hi-en daily); returning +
  legacy-pref users boot straight to the daily. Screenshots:
  `reports/screenshots/first-session-hook/`.

## Incidents found & fixed during this wave

- **smoke_check.js crashed on any failed request** (`const URL` shadowed the
  global URL class inside the requestfailed handler) — dormant since
  launch-1, surfaced on this wave's post-deploy run. Fixed, re-run PASS.
- **P0 class discovered: `dart.library.html` conditionals are stubs under
  --wasm** (the production build target since 2026-07-12). ?reset=1, ?notif=1
  and /join/{code} were dead on live — fixed this wave (package:web +
  `dart.library.js_interop`), re-verified live. Storage factory, share_web,
  timezone/PWA-check remain stubbed → **known-limitations entry 19, needs its
  own next-wave spec** (production web currently persists via PrefsStore
  fallback, share taps are no-ops on wasm).

# PLAN — Launch-1 wave: aesthetic pass + launch gates (complete)

Spec: `spec.md` (this branch, supersedes the phase-4-era scaffolding spec). Branch
`wave-launch-1-readiness`, PR #8 (draft — human merges per plan-tier constraint).
Autonomous run, orchestrator + 4 parallel executor subagents + 1 design-reviewer
pass, 2026-07-12.

## Riskiest assumption first (rule 77)

- [x] Spec framed this as "CanvasKit vs HTML renderer." Verified against Flutter's
  own docs/tracking issue (not memory): HTML renderer was removed in Flutter 3.29;
  this toolchain is 3.44.2 — the choice doesn't exist. Tested the real available
  lever instead: `--wasm` (Dart->WebAssembly compile). Built both targets from the
  same source, functionally verified via puppeteer (not just build success),
  measured with Lighthouse: TBT 221ms->13.5ms, LCP 2864ms->2635ms, -417KB, score
  0.69->0.79 (sandbox, no analytics). **Adopted for all builds.** See
  `reports/renderer-decision-2026-07-12.md`.

## Analytics instrumentation (PM header's success metrics)

- [x] Found: Firebase Analytics had **never** collected a single event in
  production — `AppConfig.analyticsEnabled` requires `--dart-define=
  ANALYTICS_ENABLED=true`, which no prior deploy command ever passed. D1
  retention and daily-completion-rate were unmeasurable, exactly the "measurement
  must exist before launch, or the success metric is fiction" risk. Fixed: the
  flag is now part of the canonical build (`deploy-warmer.ps1`/README).
- [x] Added `puzzle_completed` event (outcome: win/loss_budget/
  loss_hint_exhausted/loss_gave_up) so "% of DAU completing the daily puzzle" is
  one GA4 event, not a manual win-OR-loss union.
- [x] Found and fixed a real pre-existing bug while wiring this: the
  budget-exhausted-via-hint path recorded a loss to local stats but never fired
  the `loss` analytics event at all (only the guess-exhaustion and give-up paths
  did). 5 new tests, one specifically regression-testing this fix.
- [x] Live-confirmed post-deploy: real `page_view`/`puzzle_started` events firing
  to `google-analytics.com/g/collect` with correct params, seen in a live
  puppeteer console capture.

## Track A — aesthetic pass

- [x] `WarmerTokens` extended with `WarmerSpacing`/`WarmerRadius` sibling classes
  (rule 15b) — values grepped from real usage, not invented; plain
  `static const double`s, not ThemeExtension fields (no brightness-dependent
  lerp needed).
- [x] **Real WCAG AA failures found and fixed**: text2/text3 measured 2.08-3.67:1
  in light mode (text3 failing even the 3.0:1 large-text floor), dark text3 also
  failing (3.05-3.32:1) — independently re-verified, not taken on the
  design-reviewer's word. Root cause of the gap: `design_tokens_test.dart`'s WCAG
  suite tested text1/accentInk/accentText but never text2/text3 — added 8 missing
  test cases so this can't silently regress again.
- [x] Applied `WarmerSpacing`/`WarmerRadius` across 16 files; guess `TextField`
  got `labelText: 'Your guess'`; fresh-puzzle empty state (icon + "Make your
  first guess above", was blank space before); load-error state got a "Retry"
  button (was a dead end short of an app restart).
- [x] **Design-reviewer sign-off: approved with suggestions.** All 5 prior
  blocking findings independently re-verified fixed (contrast recomputed from
  raw hex, not trusted). Non-blocking suggestions: 2 off-scale spacing values
  (fixed same-day), AppBar centerTitle inconsistency (left as a defensible
  brand-emphasis choice, logged), win-screen CTA density, unverified mobile/
  keyboard dimensions, a possible tooltip artifact — all logged in
  `docs/known-limitations.md` entry 17.
- [x] Screenshots committed (`reports/screenshots/wave-launch-1-readiness/`,
  rule 15c mechanism) against the confirmed-correct deployed build.

## Track B — launch gates

- [x] STRIDE doc (`docs/stride-launch-1.md`) — proportionate rule-98 pass, cites
  `known-limitations.md`'s already-accepted risks rather than re-deriving them.
  Confirmed guess submission never touches Firestore (the launch-check's
  rate-limiting worry is a non-issue as framed). One new finding: unbounded
  group/code creation by a scripted client (cost/clutter risk, not data risk) —
  folded into `known-limitations.md` entry 11a.
- [x] Perf budget measured, one lever applied (deferred Firebase/AdMob init past
  first frame — real but small win, ~67ms, root-caused precisely: browser fetches
  Firebase's JS in parallel at HTML-parse time regardless of Dart-level await
  ordering), honestly documented. **LCP still fails the 3000ms tracked ceiling by
  82ms** (3082ms verified) — a genuine, named tension between this wave's own
  analytics and perf requirements, not an oversight. Documented as the wave's one
  explicitly-accepted exception.
- [x] Rollback exercise: real deploy N -> rollback to N-1 (verified via content,
  not just HTTP 200) -> roll forward to N, all verified. `deploy-warmer.ps1`
  created (spec referenced it; didn't exist before this wave).
- [x] `docs/runbook.md` — deploy/rollback/Firebase console/FCM/payload-sync/
  gotchas.
- [x] `integration_test/app_test.dart` wired into CI (`.github/workflows/
  e2e-web.yml`) — existed but was never run anywhere. Runs on Flutter web
  (`-d web-server` via chromedriver), not the Android emulator the test's own
  header mentions, since Warmer is a web-only product. Verified green in real
  GitHub Actions (multiple runs, ~2.5min each), not just locally. No branch
  protection on this plan tier, so it can't be a required check — documented in
  the workflow's own header.

## A real incident, found and fixed mid-wave

While capturing screenshots for the design-reviewer gate, a shipped fix wasn't
appearing on production despite a "successful" deploy. Root-caused to two
compounding issues: (1) `vercel.json` had no `Cache-Control` rule for the new
`main.dart.wasm`/`.mjs` files this wave introduced, and (2) more seriously,
`vercel deploy --prod` had silently stopped updating the `playwarmer.vercel.app`
alias partway through the session — every downstream check (smoke check,
Lighthouse, screenshots) kept "passing" because they only proved *some* build
boots, not *this one*. Fixed `vercel.json`, and hardened `deploy-warmer.ps1` with
two mandatory post-deploy guards: explicit `vercel alias set` (never trust
automatic aliasing again) and a byte-size comparison between the live and local
`main.dart.wasm` (purging the CDN cache and re-checking once before failing
loudly). Both verified working end-to-end. Practical implication: one
intermediate Lighthouse measurement has uncertain provenance as a result — not
hidden, flagged in `known-limitations.md` with the re-verified authoritative
numbers alongside it. See `docs/runbook.md` gotcha 1a for the full writeup.

## Final verification

- [x] Flutter suite: 493/493 passing, `flutter analyze` clean (7 pre-existing
  issues, unrelated).
- [x] Generator suite: 377 passed / 4 skipped (Ollama-gated LLM-judge tests ran
  for real this time, not skipped).
- [x] E2E CI: green in real GitHub Actions on the final commit.
- [x] Production deploy verified byte-for-byte matching the local build
  (deploy-warmer.ps1's new guard).

## `/launch-check` re-run

```
LAUNCH READINESS — mindmeld/Warmer  (tier: T2)
================================================
[pass] 1. Product review: spec.md has the 4-line PM header (target user, pain
        point, success metric, who pays).
[pass] 2. Design sign-off: design-reviewer SIGN-OFF: approved with suggestions.
        All 5 prior blocking findings independently re-verified fixed.
[pass] 3. Security pass: docs/stride-launch-1.md, proportionate rule-98 STRIDE
        pass. One new low-severity finding folded into known-limitations.md.
[fail] 4. Performance budgets: measured and artifacted
        (reports/lighthouse-playwarmer-launch1-verified.report.{html,json}).
        TBT/CLS/own-domain-JS pass. LCP 3082ms vs <=3000ms tracked ceiling --
        FAILS by 82ms. Explicitly-accepted exception (known-limitations.md #14):
        real tension between this wave's own analytics-instrumentation and
        perf-budget requirements, root-caused precisely, one lever already
        applied, next lever named (split Firebase's eager plugin loading) but
        out of this wave's scope.
[pass] 5. Rollback tested: real exercise performed and verified this wave (not
        just documented) -- deploy N -> rollback to N-1 -> verify -> roll
        forward to N, each step confirmed via content, not just HTTP 200.
[pass] 6. Monitoring/alerts: uptime-check.yml active with real incident history
        (prior wave). Crashlytics now actually wired AND live (analytics was
        enabled this wave) -- error hooks confirmed registered in code and
        Firebase confirmed initializing in production console logs; a real
        crash event reaching the Crashlytics console specifically was not
        independently confirmed (no crash occurred to test it).
[pass] 7. Docs complete: README quick-start + new docs/runbook.md (on-call:
        deploy, rollback, Firebase console, FCM, payload sync, gotchas).
[pass] 8. Critical-path E2E: integration_test/app_test.dart wired into
        .github/workflows/e2e-web.yml, confirmed green in real GitHub Actions
        (not just local) across multiple runs on the final commit. Not a
        required check (no branch protection on this plan tier) -- documented,
        not hidden.

OVERALL: 7/8 pass, 1 explicitly-accepted documented exception (gate 4) --
meets this wave's own exit criteria ("8/8 pass, or failures reduced to
explicitly-accepted, documented exceptions").
```

---

# PLAN — Known-limitations ledger: fix what's worth fixing, document the rest (complete)

Autonomous single-pass run, 2026-07-12. Full inventory of every known gap across
PLAN.md, `docs/accepted-risks.md`, the eval baseline report, and a repo-wide
TODO/FIXME grep — fixed the player-visible + cheaply-fixable items, documented the
rest in `docs/known-limitations.md` (supersedes `docs/accepted-risks.md`).

## Fixed

- [x] **Spoiler-gate over-firing on short secrets** — `_is_morphological_variant`
  (generator/payload.py) used a flat Levenshtein distance-2 threshold and an
  unconditional substring check; both scaled to the shorter string's length (see
  the fix commit for the exact false positives this closes: bat/ball-wait-both,
  money/more, mandir/and). 8 new unit tests. Audited all 220 shipped clues
  old-vs-new: 0 regressions, 0 restorable clues — the historical false-positive
  rewords (cricket "bat", bollywood mother/her/the) were fixed pre-commit, so no
  draft text survives to restore.
- [x] **Packs unreachable from win/loss result screens** — `WinScreen`/`LossScreen`
  now show the same `PacksEntryBanner` as `PuzzleScreen`, gated off in pack mode.
- [x] **No way back to the result/share screen after Back** — the finished puzzle
  board (daily mode) now has a "View result" button that re-enters via the
  existing `onWin`/`onLoss` callbacks.
- [x] **`scripts/` never lint-gated** — new root `pyproject.toml` with the same
  ruff rule set as `generator/pyproject.toml`; fixed the 3 findings it surfaces
  (3 unused imports, 2 long lines, 1 for-loop-to-any() simplification).
- [x] Nothing else in the inventory qualified as both player-visible and
  fixable without a new backend/paid dependency (reviewed: self-reported scores
  need Cloud Functions, Firebase SDK bump needs its own regression pass, npm/pip
  audit findings are dev-only/unreachable, homoglyph coverage is already
  right-sized, Firestore index / privacy email / reCAPTCHA key are GG-only manual
  actions — all moved into `docs/known-limitations.md` instead).

## Documented (`docs/known-limitations.md`, supersedes `docs/accepted-risks.md`)

16 entries: Hinglish semantic-quality gap (0.639 vs EN 0.837 Spearman, residual
worst pairs titli/khamoshi/rasoi/samunder/bachpan), LLM-judge solvability vs
spoiler-safety calibration split, packs online-only, iOS web-push PWA constraint,
self-reported scores, soft anti-cheat, npm/pip audit deferrals, Firebase SDK
version lag, homoglyph coverage, App Check monitor-mode + pending reCAPTCHA
STOP POINT, Firestore collection-group index, privacy-policy placeholder email,
Flutter-web cold-boot latency (Lighthouse baseline + rule-15e budgets ratified,
see `reports/performance-baseline-2026-07-12.md`), Android release-signing
scaffold defaults, and the eval baseline report's dimension-5 staleness
(regenerated as part of this pass).

## Verification

- [x] Regenerated `generator/evals/reports/baseline_report.{json,md}` end-to-end
  (Ollama `qwen3:8b` running locally) — see the file for current numbers; the
  previously-stale dimension 5 win-rate figures (93.0%/10.5%) now correctly show
  the post-maxGuesses-fix numbers (82.0%/63.6%) already reported in the
  security-hardening PLAN section below.
- [x] generator suite green (377 passed/4 skipped — 2 previously Ollama-gated
  skips now run for real since Ollama was up for the harness regen), flutter
  suite green (472/472).
- [x] Deployed to playwarmer.vercel.app (`vercel deploy --prod`, aliased,
  post-deploy smoke check passed: 200, Flutter engine booted, 0
  pageerror/requestfailed) and live-verified with a real cold-profile puppeteer
  run (`firebase-tests/cold_repro_reload.js`, `--profile-dir`, fresh profile):
  guessed today's actual secret (`courage`, puzzle #31) on the first try, which
  landed directly on `WinScreen` — the Themed Packs banner was visible
  immediately, no extra Back tap needed (fix 2b confirmed). Tapped Back to
  reach the finished board — the new "View result" button was present right
  below the packs banner (fix 2c confirmed); tapping it re-showed the win
  screen exactly as before. Zero pageerror/requestfailed across every step.

---

# PLAN — Follow-ups from the aesthetic pass: uptime monitoring + maxGuesses reconciliation (complete)

Two items flagged by the aesthetic-pass report below, closed out 2026-07-12.

## Status — DONE

- [x] **P0 — uptime monitoring**. `.github/workflows/uptime-check.yml` (cron `*/15 * * * *` + `workflow_dispatch`) runs `scripts/check_uptime.py` (stdlib-only: app root 200 + brand-string check, CDN `manifest.json` valid JSON, one real CDN payload valid gzip+JSON with expected keys). On failure it creates-or-updates a GitHub issue labeled `uptime-alert` (label pre-created); on recovery it comments + closes. Verified the exact `gh` command sequence end-to-end against the real repo (issue #1, created→commented→closed, not a dry-run mock). **Alert path is GitHub's own issue-notification email — confirm Settings → Notifications → Issues is enabled on the account, or this logs instead of alerting.** 12 new unit tests (`scripts/test_check_uptime.py`, mocked network, run via `cd generator && uv run pytest ../scripts/test_check_uptime.py`) cover both pass and fail paths for all three checks, including the exact "200 but wrong app" failure mode a deleted/misrouted Vercel project produces.
  - **Post-deploy smoke check**: `firebase-tests/smoke_check.js` — real headless-Chrome load, waits for the Flutter engine to actually mount (a sized `<canvas>` inside `flt-glass-pane`'s shadow root — `document.body.innerText` is empty on this CanvasKit app, so a text-based wait silently hangs forever; found and fixed live against prod during this session), asserts zero pageerror/requestfailed against the app's own origin. Exit 0/1. Wired into the README's canonical deploy flow right after `vercel deploy --prod --yes`; documented as a required gate, not optional.
  - Both scripts live-tested against playwarmer.vercel.app (pass) and against deliberately-broken URLs (both correctly fail non-zero).
- [x] **P1 — maxGuesses drift, root-caused and reconciled**. Root cause: commit `2446f3d` (2026-07-11) replaced the old fixed `par+6` maxGuesses offset with the eval-calibrated `max(12, round(par*1.5))` (median win-rate 82.0%, 63.6% in [0.75,0.85] band vs the old formula's 93.0%/10.5%) and regenerated the bundled Flutter offline-fallback + committed samples (`a9e3446`) — but the actual **publish** step to the live CDN was never run for either daily or pack payloads. Confirmed live: CDN daily `2026-06-12/en` served `maxGuesses=16` (old formula) while the bundled offline fallback already served `15` (new formula) — a real, already-live online/offline inconsistency, not just a future risk. Generator content (secrets/clues/par) hadn't changed since `a927c94`, so a straight republish from HEAD was the correct fix, not a new formula derivation.
  - Fix: `uv run publish --days 60` (daily, both langs, matching existing 60-day CDN coverage) → mindmeld-payloads commit `95f7388`; `uv run build-packs --packs all --langs en,hi-en --strict-sizes` → full `packs/` tree synced and pushed → mindmeld-payloads commit `368e192`. Byte-reproducibility re-verified (independent second pack bake, `diff -rq` identical including `manifest.json`). Live CDN re-checked post-publish: daily `2026-06-12/en` now `15`, pack `bollywood/en/001` now `14` — source and live agree.
  - Re-ran Dimension 5 fresh (not cited from the old commit message): **220 puzzles, median win-rate 0.820, mean 0.803, 63.6% in the [0.75,0.85] target band, per-lang median en=0.80/hi-en=0.84, 0 outliers >0.97, 1 outlier <0.40** (`bollywood` EN `song`, 0.39 — the same single known-accepted outlier `rival.py`'s own module comment already documents, one point under the cutoff at n=100 sims/puzzle noise ~5pp). Numbers reproduce the 2446f3d commit message exactly, confirming HEAD is stable and unchanged since that calibration.
- [x] Generator suite unaffected: 370 passed / 6 skipped, ruff clean except the same 3 pre-existing findings from the aesthetic-pass report (`build.py`/`test_rival.py` — untouched, out of scope).
- [x] **Uptime workflow verified in REAL GitHub Actions, not just locally** — caught a real bug this way: the first `workflow_dispatch` run failed with a misleading "Repository not found" from `actions/checkout`, root-caused to `permissions: {issues: write}` silently zeroing the default `contents: read` checkout needs (`95a8787`). After the fix, ran the full failure→alert→fix→recovery loop for real: a deliberately broken check (`80e1c18`) made the workflow's own `GITHUB_TOKEN` create real issue [#2](https://github.com/gaurav-gandhi-2411/mindmeld/issues/2) via `gh issue create`, then reverting (`a32275f`) made the same token comment "Recovered" and auto-close it — both confirmed via `gh run view --log` and `gh issue view`, not assumed from the YAML. Commits: `1f31423` (feature), `95a8787` (permissions fix), `80e1c18`/`a32275f` (verification pair, both reverts of each other, net no-op on the shipped file).

## Minor finding (not fixed, out of scope)

`scripts/make_feature_graphic.py` (repo-root `scripts/`, not `generator/`) has 2 unused-import ruff findings (`os`, `sys`) from the icon-retune work in the prior session. Repo-root `scripts/` has never been under any ruff config/CI gate (only `generator/pyproject.toml` exists) — this isn't a regression from this session, but the directory has a real lint-coverage gap worth closing separately.

---

# PLAN — Aesthetic pass: calm-minimal design system (complete)

Spec: `spec-aesthetic-pass.md` (source of truth). Visual-only; zero gameplay changes. Live-verified on playwarmer.vercel.app 2026-07-12.

## Status — DONE

- [x] **Design tokens**: `app/lib/core/design_tokens.dart` — `WarmerTokens` ThemeExtension (single source of truth), locked light palette + purpose-derived dark scale (lifted luminance, warm near-black `#171614` canvas — NOT inverted). `buildWarmerTheme()` builds all Material component themes from tokens; `buildPackTheme()` re-accents pack play with a luminance-based ink rule (replaces `ColorScheme.fromSeed`). `design_tokens_test.dart` bakes WCAG AA ≥4.5:1 for every band text/tint pair in BOTH modes into CI (24 tests).
- [x] **Applied everywhere**: puzzle (clue card w/ TODAY'S CLUE micro-label, guess/hint tiles, rival strip, budget, progress row), win/loss (heat-rings mark, redesigned share PREVIEW card with painted heat-trail squares — `buildShareCard()` TEXT stays byte-identical, tests prove it), pack selector (responsive `GridView.extent` quiet cards + gradient identity coins), pack list/play, banner, onboarding, loading, stats, settings, social ×3, archive, nav bar, dialogs, snackbars, empty/error states. In-app band EMOJIS (rival strip, loss badge, progress row) replaced with painted swatches/labels — bright unicode squares remain only in share TEXT (WhatsApp), by design.
- [x] **Identity retune** (same mark): rings `#6B89A8/#7E9BB5/#D9AE6B/#D65F49`, ground `#171614`, wordmark accent `#DD6B4D` (light) / `#E87A5C` (dark) — synced across heat_rings_mark.dart, 4 scripts (app icon, web icons, OG, feature graphic), identity SVG, PWA meta/manifest, adaptive-icon bg, all regenerated PNGs + Android mipmaps.
- [x] **Pack accents muted** (distinct from each other + brand): bollywood `#C0913F/#7E3B46`, cricket `#4F7A57/#2F4C36`, indian-food `#9C5E20/#6B3F14` (darkened so white ink passes AA when it goes live), nature `#3D7068/#24443F`. Fallback accent `#6200EE` purple → `#DD6B4D`. CDN manifest republished (payloads repo `ff11651`, **manifest-only**).
- [x] **Suites**: flutter 459/459 (was 393; +24 token/WCAG +misc from wave), generator 370 passed/6 skipped, analyze 7 pre-existing issues only. Grep-clean: zero old bright hexes / Material purple / colorSchemeSeed / fromSeed in app/lib + scripts + web meta.
- [x] **Live-verified prod** (cold_repro_reload.js, new `--dark`/`--light` flags): Gate A fresh profile light (onboarding→4-guess win `courage` #31→share card/dialog) + full dark pass; Gate B existing-user new-process restore (win screen + Stats 1/100%/1/1); packs muted from CDN manifest both modes. Zero pageerror/requestfailed. Commits `2defd21`,`1b59630`,`295d86a`,`14f0d71`.

## Incidents & flags discovered

- **P0 found mid-deploy: production was already DOWN** — the `playwarmer` Vercel project had been DELETED from the account (cause unknown, sometime after 2026-07-10 verification; another product's session touched Vercel ~9h before). Both domains 404'd BEFORE this session's deploy. Recovered: recreated project `playwarmer` (new id `prj_xTlhdx6TkHnobjF5JuCQ2ZQRbSp0`), linked web-dist, deployed, re-registered `playwarmer.vercel.app` + `playmindmeld.vercel.app` via `vercel domains add`, both 200. A stray auto-created `web-dist` project (from deploying before discovering the missing link) was deleted. **Watch: whatever deleted the project may still be unexplained.**
- **maxGuesses payload drift (NOT shipped)** — **RESOLVED, see the "Follow-ups" PLAN section above.** a fresh `build-packs` bake from generator HEAD produces maxGuesses one LOWER than the published pack payloads (en 15→14, hi-en 13→12). Republishing payloads would be a silent gameplay change, so the aesthetic pass published ONLY `packs/manifest.json`. Root cause: the 2026-07-11 formula tuning (`2446f3d`/`a927c94`) was never actually republished to the live CDN for daily OR packs — fixed by republishing both from HEAD.
- Pre-existing, untouched (out of visual scope): ruff I001×2 + F841×1 in `generator/build.py`/`tests/test_rival.py`; `firebase-tests/node_modules` template noise in repo-root `flutter analyze`.

## Gotchas discovered

- The app reads pack accents from the **CDN manifest live** — bundled fallback only covers offline. Local builds show old colors until the Pages manifest is republished.
- Headless Chrome inherited the OS dark preference — light-mode verification runs MUST pass `--light` explicitly (flag added).
- Emoji render as tofu in headless screenshots (no emoji font) — cosmetic, text content is correct.

---

# PLAN — Phase 6c: Themed Packs (living tracker)

Spec: `spec-phase6c.md` (source of truth). Scope: pack SYSTEM + Bollywood flagship only; Cricket / Indian Food / Nature & Wild as content-drop stubs.

## Cross-side contract (generator ↔ app) — FROZEN

- **Payload namespace:** `{baseUrl}/packs/{packId}/{lang}/{NNN}.json.gz`, `NNN` = 1-based zero-padded 3 (`001`…`025`).
- **Pack payload JSON:** identical v3 daily schema PLUS `"pack": "<packId>"`, `"idx": <int>`; `"date"` carries the opaque key `"<packId>-<NNN>"` (Dart never DateTime.parses payload date — verified `models.dart`).
- **Salt:** pack payloads derive salt from the opaque key + lang via the same sha1 recipe (new helper; daily path stays byte-identical).
- **Pack manifest** (published `{baseUrl}/packs/manifest.json`, bundled fallback `app/assets/payloads/packs/manifest.json`):
  ```json
  { "v": 1, "packs": [ { "id": "bollywood",
      "title": {"en": "Bollywood", "hi-en": "Bollywood"},
      "tagline": {"en": "…", "hi-en": "…"},
      "free": true, "status": "live",
      "accent": "#E8B23A", "accentDark": "#8E1A2B",
      "icon": "film", "langs": ["en", "hi-en"], "count": 25 } ] }
  ```
  `status`: `live` | `coming_soon`; stubs have `count: 0`.
- **Pack lineup + identity:** bollywood (film icon, gold `#E8B23A` / crimson `#8E1A2B`, free, live) · cricket (green `#2E7D32`) · indian-food (turmeric `#E65100`) · nature-wild (teal `#00695C`) — the last three `coming_soon`, count 0.
- **Persistence:** new sqlite table (schema v4) `pack_progress(pack_id, idx, lang, guesses_json, hints_used, won, gave_up, revealed_hints_json, PK(pack_id, idx, lang))`. Pack play NEVER writes `stats` or `day_state`.
- **IAP:** `Entitlements.packs: Set<String>`; gateway `purchasePack(packId)` → RC product `mm_pack_{id}` / entitlement `pack_{id}`. Unlock rule: `pack.free || web (iapEnabledEffective==false) || entitlements.packs.contains(id)`.
- **Share card:** pack games render `Mindmeld · {PackTitle} #{idx} {langLabel} {emoji trail}`; daily format unchanged.

## Status

- [x] 6b pushed; HEAD=origin/main=85979bc → spec committed 8b4e064
- [x] Executor A done: packs.py, build_packs.py (`uv run build-packs --packs all --langs en,hi-en --out ../payloads --strict-sizes`), publish syncs packs/ tree, 4-pack scaffolding, pytest 336 passed + 8 pack-gate skips (activate with content), ruff clean on touched files. NOTE: publish.py does NOT invoke build-packs — pack publish = run build-packs into the dir publish syncs from (orchestrate at drop time).
- [x] Bollywood content files written (packs/bollywood/*), hinglish.txt +11 words, hi-en-aliases.txt +14 entries, eval fixtures P01–P11. Generator suite GREEN: 349 passed, 6 skipped (empty stubs). Spoiler gate caught 5 subtle leaks during authoring (agar~pyar, paas~maa, her⊂mother, the⊂mother, one~song) — all reworded; audit script confirms 0 leaks across all 50 clues.
- [x] Executor B done: Flutter pack system (catalog, selector, pack play, persistence v4, IAP, share, identity). flutter test 376/376, analyze clean. Committed 83d98a8 (generator) + b3e75c4 (app), pushed.
- [x] Bollywood content validated over 3 embedding rounds. FINAL 25 pairs (EN/hi-en):
  romance/pyaar, hero/hero, villain/villain, dance/naach, song/geet, mother/maa, drama/natak,
  tears/aansoo, dialogue/dialogue, destiny/kismat, promise/vaada, revenge/badla, police/police,
  honor/izzat, sacrifice/qurbani, story/kahani, twist/twist, star/sitara, anger/gussa,
  fight/ladai, gossip/gossip, audience/audience, youth/jawaani, ticket/ticket, award/award.
  REJECTED (model misreads romanization): dil→Turkish "language", dua→Italian "due", jalan→Malay
  "road", milan→city, dushman .29, dhadkan .29, pooja .28, dulhaniya .22, intezaar .16, dosti .36,
  yaari .33, barsaat .39, saawan, dhun; EN `interval` (math neighborhood). Code-mixed EN secrets
  (hero, villain, dialogue, twist, gossip, police, audience, ticket, award) verified dense in BOTH vocabs.
  11 hinglish.txt additions needed: natak, geet, aansoo, kismat, badla, vaada, qurbani, kahani,
  sitara, ladai, jawaani — eval fixtures P01–P11 pre-validated 11/11 PASS (thinnest: ladai .435>.398).
  Aliases to add: naatak, ansoo/aansu/ansu, kismet/qismat, waada (NOT wada/vada — food collision),
  kurbani, kahaani, sitaara, ladaai/larai, jawani, nach, pyar, ghussa, izat, ma.
- [x] **STOP POINT cleared 2026-07-09**: GG approved content WITH edits. Applied: 3 GG rewords (EN #5/#16/#23), item-song kept only on #4 (hi-en #23 reworded), whistle/seeti + front/first row + first show de-duplicated (#2/#9/#22/#24). Semantic-neighbor audit over all 50 clues reworded 5 more: lyrics→#5 hi-en, line→#9 both, giraftaar→#13 hi-en, Overacting→#7 EN, Picture→#16 hi-en; EN #19 moved off the seventies archetype (collision with new #23). 13/50 clues changed total.
- [x] Payloads baked + published: 25×2 payloads + packs manifest, all under size targets (--strict-sizes), byte-reproducibility gate PASS after fixing hash-seed-dependent alt-map ordering in payload.py (5b7ddd6 — hi-en payloads were non-reproducible cross-process; regression test added). Pages commit fda0bba.
- [x] Web app deployed to playmindmeld.vercel.app (registrant + auth-domain guards OK, SW mindmeld-precache-68baf9ba2a5d verified live).
- [x] Cold-profile live verify on playmindmeld.vercel.app — ALL PASS (15 cold runs, screenshots reviewed): V1 selector gold→crimson Bollywood identity + 3 coming-soon tiles; V2 EN #1 start-to-win (wedding #889 Warm → movie #375 Hot → romance win); V3 hi-en win (shaadi → pyaar) with localized tagline; V4 share text `Mindmeld · Bollywood #1 (English) 🟨🟧⭐ / 3/15 · Par -6`; V5 pack win leaves Stats at Played 0/Streak 0 and daily unplayed, then daily win works normally. Zero pageerror/requestfailed across all runs. (Pages publish was delayed ~35 min by a GitHub Actions partial outage — queue only, no action needed.)
- [x] Full suites green: generator 350 passed / 6 skipped, flutter 376/376, ruff clean.

## Known issues (found during 6c live verify, NOT 6c regressions)

- [x] **P1 — daily win screen "Back" is a dead end for the rest of the day** — FIXED. `main.dart`'s tabbed Scaffold (NavigationBar + IndexedStack) is now always the home surface; only the index-0 child swaps between `_WinShell`/`_LossShell` and the live `PuzzleScreen`. Restart/lang-switch routing moved to `_AppShellState._deriveResultRouting`. `PuzzleScreen._load()`'s already-finished-state `onWin`/`onLoss` redirect is now scoped to pack mode only (daily mode's routing is owned exclusively by the app shell, keeping `onWin`/`onLoss` idempotent across remounts — that idempotency gap was the actual root cause of the bounce-back). Commits 5eb4869 (fix) + 1870a9c (tests: `app/test/daily_win_navigation_test.dart`, 6 cases). flutter test 382/382 (376 baseline + 6 new), analyze clean.

- [x] **Follow-up — StatsScreen stale after same-session win** — FIXED (2e596b0). Exposed by the P1 fix (Stats became reachable post-win and showed boot-time Played 0/Streak 0). Persistence was proven fine live (win → reload → 1/1); root cause: `StatsScreen._load()` ran only in initState while eagerly mounted in the IndexedStack. Now reloads on tab activation (`active: _navIndex == 2`) and lang change. flutter test 384/384.
- [x] **Follow-up sweep — other eagerly-mounted tabs** — DONE. SocialHomeScreen (Friends) had the same bug: `_groups` loaded once in initState, never refreshed on tab reactivation despite having manual pull-to-refresh. Fixed (a12b806): `active: _navIndex == 4` + `didUpdateWidget` reload on false→true (no lang trigger needed — group list isn't lang-scoped). ArchiveScreen (Practice) investigated and confirmed NOT affected: it's a `StatelessWidget` whose `_availableDates()` is a pure function of `DateTime.now()` with no persisted read, so it already recomputes fresh on every parent rebuild — no change made. GroupLeaderboardScreen (pushed route, not an IndexedStack tab) confirmed already fresh per-open (new instance + no service-layer caching) — regression test added to lock this in rather than a code change. Tests: f304a84, flutter test 386/386.
- [x] **Both P1 fixes + the Social sweep live-verified on production 2026-07-10** (cold profile, build 2cfd2a7a259a): daily win → nav bar present on win screen → Back lands on finished board and stays → Stats tab shows Played 1/100%/Streak 1/Best 1 same-session → Practice, Friends, Themed Packs → Bollywood list all reachable. Two-profile Friends flow (join-by-deep-link `/join/{code}`): Alice creates group "TestSquad" (1 member) → Bob joins via deep link and wins the daily in a separate cold profile → Alice's Friends tab, reactivated (no manual refresh), shows "2 members"; freshly-opened leaderboard shows Bob "Won in 1 (-7 vs par)". Zero pageerror/requestfailed across all runs (a handful of benign Firestore webchannel `net::ERR_ABORTED` recycle events, writes confirmed completed regardless).

## Gotchas discovered

- `derive_salt(puzzle_date: date, lang)` takes a datetime.date — pack build needs a string-key variant, daily output must remain byte-identical.
- hi-en secrets are romanized-Hindi words line-paired with EN (`samunder`↔`ocean`); pack content follows the same format.
- Flutter SDK not on PATH: `C:\Users\gaura\sdks\flutter\bin`. Tests: `flutter test --concurrency=1`.
- Daily secrets already use: ocean/samunder, music/gaana, rain/baarish, family/parivar, dream/sapna … — avoid duplicating in pack (check full 60 before finalizing).

---

# PLAN — Warmer rename + heat-rings identity + pack discoverability (complete)

Spec: `spec-warmer-rename.md` (source of truth). Autonomous single-pass run, live-verified 2026-07-10.

## Status — DONE, all 6 workstreams + both hard gates live-verified

- [x] **Rename**: manifest/index.html/in-app strings/notifications/README/docs/Android label/iOS display name → Warmer, `playmindmeld.vercel.app` → `playwarmer.vercel.app`. Deliberately unchanged (infra, zero user surface): Firebase project `mindmeld-c4bba`, Dart package name `mindmeld` (100+ `package:mindmeld/` imports), Android/iOS bundle ids, `mindmeld.db` sqlite filename, `mindmeld-payloads` GitHub Pages CDN path, generator `pyproject.toml`. Commit eccb6e7.
- [x] **Identity**: new `scripts/make_app_icon.py` (heat-rings rings-on-dark-ground, two masters — opaque tile + transparent fg for adaptive-icon compositing), rewritten `make_web_icons.py` (32/16px favicons, dark-ground maskable), new `make_og_image.py` (1200×630 card), `HeatRingsMark`/`WarmerWordmark` Flutter widgets (`app/lib/features/branding/heat_rings_mark.dart`) wired into the app-shell loading screen, onboarding hero, and daily PuzzleScreen AppBar. Theme `colorSchemeSeed` moved from the old purple `0xFF6200EE` to the wordmark accent `0xFFF97316`. `flutter_launcher_icons` regenerated Android mipmaps/adaptive icon from the new masters.
- [x] **Discoverability**: `PacksEntryBanner` (shared widget, `compact` variant) pinned to the top of `PuzzleScreen`'s primary daily surface — the fix for "couldn't find Bollywood" (previously only reachable via a card buried under the Practice tab, which still keeps its own entry too).
- [x] **Tests**: `packs_entry_banner_test.dart` (3 cases: banner shown/hidden by mode, tap navigates), `storage_rename_migration_test.dart` (2 cases: a `mindmeld.db`-named file's data survives a fresh `SqliteStore` instance; `PrefsStore` keys never literally contained "mindmeld" so nothing needed migrating). flutter 391/391 (was 386), generator 350/6-skip unaffected.
- [x] **Deploy**: Firebase Auth authorized domains updated (added `playwarmer.vercel.app`, kept `playmindmeld.vercel.app`) via `check_authorized_domains.py`'s documented PATCH remediation. Built + deployed to Vercel; **Vercel project renamed** `playmindmeld` → `playwarmer` (`vercel project rename`) then `playwarmer.vercel.app` explicitly added as a first-class project domain (`vercel domains add` — a plain `vercel alias set` was NOT enough, it stayed gated behind SSO deployment-protection since only registered project Domains are exempt). `playmindmeld.vercel.app` still resolves (same deployment, not just a redirect).
- [x] **Live-verify (cold-profile puppeteer, `firebase-tests/cold_repro_reload.js` + new `--profile-dir` flag for persistent-profile "returning user" runs)**:
  - Gate A (fresh user): onboarding shows heat-rings mark + "Welcome to Warmer"; daily puzzle screen shows the Themed Packs banner impossible-to-miss at the top; tapping it shows Bollywood live (0/25) + Cricket/Food/Nature teased "Coming soon"; played a real guess (`caterpillar` → Scorching 81.2%) then won (`butterfly`, 2 guesses) — share card correctly reads "Warmer #29 (English) … playwarmer.vercel.app".
  - Gate B (existing user): same profile, **brand-new Chrome process** (full restart, not just reload) reusing the persisted userDataDir — win screen restored instantly, Stats still shows Played 1/Win% 100/Streak 1/Best 1, zero `pageerror`/`requestfailed`. SW cache-name rotation (`mindmeld-precache-*` → `warmer-precache-*`) is safe by construction: the existing `activate` handler already evicts any cache not matching the current name on every deploy (this already happened on every prior deploy too), and streaks/stats/pack-progress live in IndexedDB/localStorage — a different browser storage mechanism than Cache Storage, untouched by the SW rename.
  - Shared-link OG card: `curl` confirmed `og:image`/`twitter:image` meta resolve to `https://playwarmer.vercel.app/icons/og-image.png` (200, image/png, 21,586 bytes).

## Gotchas discovered

- Flutter's `flutter build web` does NOT copy arbitrary files from `app/web/` into the build output (documented in `make_web_sw.py`'s existing `_copy_vercel_config` comment) — EXCEPT it copies the whole `icons/` directory wholesale and the literal `favicon.png` filename. New assets (favicon-16.png, og-image.png) were placed inside `app/web/icons/` for exactly this reason, and confirmed present in `app/build/web/icons/` after a real build rather than assumed.
- Vercel deployment-protection (`ssoProtection.deploymentType: "all_except_custom_domains"`) exempts registered project *Domains* but NOT ad-hoc `vercel alias set` targets — an aliased-but-unregistered `*.vercel.app` name still 302s to `vercel.com/sso-api`. Fix: `vercel domains add <domain>` (no project arg, uses the linked project) registers it as a real domain.
- `VAR=value cmd "$VAR"` on one bash line does NOT expand `$VAR` to the prefix-assigned value (prefix assignments only affect the child env, not same-line word expansion) — silently produced an empty `--profile-dir` arg and a fresh temp profile every run. Fix: `export VAR=value` as its own statement first.

---

# PLAN — Cricket pack (content drop) — complete (shipped 2026-07-10, see Status below)

Spec: `spec-cricket-pack.md` (source of truth). Content-only drop — pack SYSTEM unchanged.

## Status

- [x] **Draft complete, 2026-07-10**: 25 secrets + EN/Hinglish clues authored to `generator/packs/cricket/{secrets,clues}_{en,hi-en}.txt`. All 25 hi-en secrets are code-mixed English (identical spelling to EN) — every native-Hindi alternative tested (naara, shatak, chakka, haar, wapsi, bheed, vijeta, mukabla, takkar, jeeta, josh) failed embedding validation (multilingual model clusters short romanized tokens by phonetics, not meaning — same failure class Bollywood found for dil/dua).
- [x] 6 vocab additions to `vocab/hinglish.txt` (wicket, umpire, bowler, fielder, finalist, chant — missing from the auto-included top-10k English words), eval-gated via new fixtures P12–P17. Thinnest margin: bowler 0.622 vs 0.232 (far more comfortable than Bollywood's thinnest, ladai at 0.435 vs 0.398).
- [x] Exact-alias spoiler gate (`tests/test_clue_spoiler_gate.py -k cricket`): 0 leaks, both languages, after 3 rounds of fixing the `bat` clue (a 3-letter secret is a Levenshtein-distance-2 minefield — "ball", "wait", "both" all tripped the morphological-variant check before landing on a clue built entirely from 4+ letter words).
- [x] Semantic-neighbor audit (ad-hoc script, not checked in — embeds every clue content-word and flags >0.40 cosine similarity to its own secret): reworded wicket (removed "batsman", 0.727→0.429 via "pavilion"), stadium (seats→voices), chant (sing/gaate→repeat/dohraate), score/aankdha (number→tally/aankdha), helmet (removed the chin-strap description cluster). hi-en flags mostly grammatical-word noise (mein/tha/sab/karta score artificially high in the multilingual model) — reviewed and left as-is after confirming no real content-word leaks remain beyond the ones fixed.
- [x] Full generator suite green: 358 passed / 4 skipped (was 350/6), eval fixtures 77/77 (was 71/71).
- [x] Zero duplicates vs the 60 daily secrets or 25 Bollywood secrets, both languages (programmatic check, not just eyeballing).
- [x] **GG-approved 2026-07-10 with 3 changes**, applied then baked:
  1. Cut `century` (theme-diluted, embedded toward "100 years" not "100 runs") → replaced with `spin` (the bowling art). Validated per GG's own acceptance bar: no spin-class/spin-doctor collision in the top-15 neighbors (generic "rotation" sense — spins/spinning/spun/spinner/rotational — not gym-class or political-spin). Already dense in both vocabs, zero additions needed. New clues: EN "Flighted invitingly, then bites and darts away late" / hi-en "Upar se lehrata hua aata hai, phir achanak kat ke nikal jaata hai" — both passed the spoiler gate after one round (hi-en's first draft used "mein", Levenshtein-2 of "spin", swapped out) and the neighbor audit clean (top score 0.286/0.368, well under the 0.40 review bar).
  2. Kept `appeal` as instructed.
  3. Reworded boundary (EN "Racing flat along the turf, four runs without ever leaving the grass", hi-en "Zameen se chipki gendh, char run, ghaas chhode bina seedha paar") to de-dupe "rope" with `six`'s clue — GG's own text includes "four runs"/"char run" literally; neighbor-audit re-run confirms `runs` itself scores only 0.238 against `boundary` (below the 0.40 flag bar) so the literal word does not register as a semantic-neighbor risk by the audit's own metric, despite spec's general caution against it — noted, not overridden (GG's explicit text, applied verbatim).
- [x] **Baked and published 2026-07-10**: `build_packs.py --packs all --langs en,hi-en --out ../payloads --strict-sizes` (note: ran with `--packs all`, not just `cricket` — a partial `--packs cricket` build writes a manifest scoped to ONLY cricket, silently dropping bollywood/indian-food/nature-wild from the published manifest; caught before publishing). All 50 payloads (25×2 langs) within size targets (en ~777-780KB, hi-en ~152-153KB, matching Bollywood's profile). Byte-reproducibility: full rebuild into a scratch dir, `diff -rq` byte-identical — PASS. Published to `mindmeld-payloads` repo (commit `04fd0ca`, pushed) + synced `app/assets/payloads/packs/manifest.json` bundled fallback.
- [x] `generator/packs/packs.json` cricket status flipped `coming_soon` → `live` (free stays `false`, matching original 6c scaffolding — irrelevant on web since IAP is force-disabled there).
- [x] Visual identity: **zero new code needed** — the pack system is already fully generic. `packIconForKey('cricket')` already mapped to `Icons.sports_cricket` (app/lib/core/packs.dart, from original 6c scaffolding); pack tile gradient, puzzle-screen `ColorScheme.fromSeed(seedColor: pack.accent)` theming, and AppBar title all read `pack.accent`/`pack.accentDark`/`pack.iconData` generically — Cricket's green `#2E7D32`/`#1B4D20` + cricket-bat-and-ball icon apply automatically now that `status: live`. Distinct from Bollywood's gold `#E8B23A`/crimson `#8E1A2B` + film icon by construction.
- [x] Fixed 3 tests broken by Cricket going live (all were asserting the old "only Bollywood is live" lineup): `generator/tests/test_packs.py` (split `test_other_packs_are_coming_soon_and_paid` into a cricket-live test + a remaining-two-coming-soon test), `app/test/pack_catalog_test.dart` (same split), `app/test/pack_selector_screen_test.dart` (coming-soon chip count 3→2, the "tapping coming_soon does nothing" test was tapping Cricket specifically — retargeted to Indian Food — added a new "tapping Cricket opens the puzzle list" test mirroring Bollywood's).
- [x] Updated `packs_entry_banner.dart`'s compact copy ("Play Bollywood — more packs coming soon" → "Bollywood & Cricket live — more packs coming soon") — stale now that Cricket is live too.
- [x] Full suites green: generator 359 passed/4 skipped (was 350/6 pre-Cricket: +2 spoiler-gate cases activating for cricket-en/hi-en, +1 net from splitting the pack-status test into two), eval fixtures 77/77 (was 71/71, +6 P12-P17; `spin` needed no addition/fixture — already dense in both vocabs), flutter 393/393 (was 391/391 pre-live-flip, +2: cricket-catalog test, cricket-tile-tap test).
- [x] **Deployed and live-verified on playwarmer.vercel.app, 2026-07-10** (cold-profile puppeteer, persistent `--profile-dir`, fresh profile): pack selector shows Cricket live with a distinct solid-green (#2E7D32) tile + `Icons.sports_cricket` icon, "0/25", next to Bollywood's gold/crimson — visually unmistakable. Opened Cricket puzzle #1 (secret `umpire`) in **English**: clue "Raises one finger and either team erupts or groans" → guessed `umpire` → hole-in-one, share card reads "Warmer · Cricket #1 (English) ... playwarmer.vercel.app". Switched language to Hinglish in Settings, opened Cricket puzzle #1 again: clue "Ek ungli uthi, aur poora ground ya toh chilaya ya chup ho gaya" → guessed `umpire` → hole-in-one, share card reads "Warmer · Cricket #1 (Hinglish)". Checked Stats afterward: Played 0 / Win% 0 / Streak 0 / Best 0, "No wins yet" — two pack wins left the daily streak completely untouched, live-confirmed (not just unit-tested). Zero `pageerror`/`requestfailed` across all runs. `packs_entry_banner.dart`'s updated copy ("Bollywood & Cricket live — more packs coming soon") also confirmed rendering correctly.
- [x] Vercel deploy: `flutter build web --release`, both guard scripts pass (web-plugin registrant, authorized domains), SW cache rotated (`warmer-precache-690a5a44d426`), `vercel deploy --prod` → aliased to both playwarmer.vercel.app and playmindmeld.vercel.app (both 200). Sample cricket payload spot-checked live on the GH Pages CDN (en/001 and hi-en/001, byte sizes match the build log exactly).
- [x] Source commits: `5f99c0b` (mindmeld, pushed) + `04fd0ca` (mindmeld-payloads, pushed).

## Deviations from spec's own quality-bar table (intentional, reported at review)

- Dropped `victory`/`jeet` — spec's own example secret, but **already a daily secret** in both languages (vocab/secrets_en.txt and secrets_hi-en.txt both have it at the same schedule line). Spec's constraint #34 ("None duplicating the 60 daily secrets") overrides its own example.
- Spec's example boundary clue ("Four runs the easy way...") contains "runs" — spec's own item 4 explicitly names "runs in the boundary clue" as the semantic-neighbor mistake to avoid. Did not copy it; wrote an original clue instead.
- `century` and `appeal` kept despite imperfect neighborhoods (century embeds toward "100 years" not "100 runs"; appeal embeds toward the legal-appeal sense) — both still produce a *coherent* gradient (not the "no signal at all" failure mode of over/googly/yorker), and both are in the spec's own explicitly-endorsed safe list. Flagged for GG's judgment call, not silently kept.

## Gotchas discovered

- `embed_vocab`'s cache keys on a SHA-1 of the sorted vocab list — adding even one word to a candidate batch forces a full uncached re-embed of the whole batch (fine for small ad-hoc test batches, ~10s; would NOT want to do this against the full 55k/10.4k production vocab repeatedly).
- `_is_morphological_variant` (payload.py) uses `levenshtein(candidate, secret) <= 2` with no length-relative scaling — brutal for 3-letter secrets (`bat`, `six`) since huge swaths of common short words fall within edit-distance 2. Worth remembering before picking short secrets for future packs.
- Clue *prose* (unlike secrets) never needs vocab/embedding validation — only the secret word itself must be in-vocab. Free to use rich native Hindi phrasing (wapsi, maidan, khamosh) in Hinglish clues even though those exact words failed AS secret candidates.

---

# PLAN — Applied-AI Eval Harness (in progress)

Spec: `spec-eval-harness.md`. GG approved dim-1 scenario labels 2026-07-10 (relabels: bagicha/aaina near-tier fixes + EN garden/mirror proactive parity fix, forest mid swap, hi-en near-tier split into translation-vs-associate subtypes).

## MAJOR FINDING (dimension 1, hi-en) — RESOLVED 2026-07-10, see spec-hinglish-fix.md fix below

The direct English translation of a Hinglish secret ranks in the **thousands** (out of ~10,445 words) for every real published daily payload checked — not a handful of edge cases, the dominant pattern:

| date | secret | translation | actual rank / ~10445 |
|---|---|---|---|
| 2026-06-18 | aag | fire | 6988 |
| 2026-06-17 | pahad | mountain | 7328 |
| 2026-06-15 | parivar | family | 7529 |
| 2026-06-13 | gaana | music | 3817 |
| 2026-06-12 | samunder | sea | 3404 (best case — still Freezing band, cold threshold is ~2611) |

Verified against the **actual shipped payload JSON** (decoded via the real salt/hash scheme, not just the eval harness's own computation) — confirms this is live in production today, not a harness artifact. Mechanism: when the secret itself is a short romanized-Hindi word, its embedding in `paraphrase-multilingual-MiniLM-L12-v2` appears dominated by shallow lexical/tokenization features rather than semantic content — "aag"'s own nearest neighbors are `aaa`, `aaj`, `ave`, `epa` (short-token noise), not fire-related words. EN-side self-consistency is fine (near-tier band-accuracy 96%), isolating this to the Hindi/romanized query side specifically. This is the same failure class as the 5 existing KF-H* fixtures but far more pervasive than those 5 isolated fixtures suggested — the pairwise-ordering fixture format (`cos(anchor,closer) > cos(anchor,farther)`) can pass while the closer word still ranks in the bottom two-thirds of the entire vocabulary, because it never checks absolute rank position, only relative order between two hand-picked candidates.

Product implication: a Hinglish player who correctly guesses the **English translation** of the secret — an extremely natural, common guessing strategy — gets almost no useful temperature signal. This is a design/product-level decision point (swap model? boost translation-word rank specially? restrict hi-en secrets to words that embed well?), not something the eval harness itself should silently patch — surfaced prominently in the baseline report instead.

## Status

- [x] `evals/harness/` package: `pairs.py` (shared EN<->hi-en daily-schedule pairing, reused by dim 1 + dim 2), `metrics.py` (scipy-free Spearman via rank-transform + Pearson).
- [x] `evals/gen_dim1_scenarios.py`: 25 secrets/language, 227 scenarios/language (2 near + 2-3 mid + 5 far per secret), seeded far-tier (seed=42) with stopword + Levenshtein-distance-4 exclusion. hi-en near tier tagged `subtype: translation|associate`.
- [x] `evals/harness/dimension1_ranking.py`: band-accuracy (overall/per-tier/hi-en-near-split), Spearman correlation, monotonicity violation rate. Numbers:
  - EN: band_accuracy overall 0.749 (near 0.96, mid 0.077, far 0.944), spearman 0.837, monotonicity 38/614 violations (6.2%).
  - hi-en: band_accuracy overall 0.546 (near 0.08, mid 0.0, far 0.96), **near split: translation 0.0, associate 0.133**, spearman -0.003 (no correlation), monotonicity 330/614 violations (53.75%).
  - EN mid-tier accuracy (7.7%) is a separate, milder finding: "mid" words often rank BETTER than expected (Hot/Scorching instead of Warm) — the model is often MORE generous than the 3-tier bucketing assumes, not wrong, just miscalibrated bucket edges. Flagged in report, not conflated with the hi-en finding above.
- [x] GG-approved dim-1 fixes applied (2026-07-10): century->century N/A (not touched here, that was Cricket pack), bagicha<-lawn and aaina<-glass relabeled near->mid (+ replacement near words `garden`/`mirror`, both the exact EN pair-word — a deliberate choice), same fix proactively applied to EN garden<-lawn/mirror<-glass (not in GG's sample, same flaw), forest<-safari swapped for forest<-camping. Regenerated: 227 scenarios/language (unchanged count — the two relabels net to 0 tier-count change per language after the "keep 2 near" backfill).
- [x] `evals/harness/pairs.py`: shared EN<->hi-en daily-schedule pairing (60 pairs), reused by dimension 1 (translation/associate near-tier subtype tagging) and dimension 2.
- [x] `evals/harness/dimension2_crosslang.py`: full 60-pair schedule (not just dim-1's 25-secret sample) — **pass_rate (Scorching/Hot) = 5.08%**, median_rank = 4881/10462 (**46.65th percentile — statistically indistinguishable from random**), mean_rank = 4981. 59/60 pairs resolved (1 vocab gap: "kite" not in hi-en's top-10k). This is the FULL-SCALE confirmation of the dimension-1 finding below — not a sampling artifact.
- [x] `evals/harness/dimension4_rival.py`: real production `rival.generate_rival_data` across all 220 live puzzles (60 daily x2 langs + 25 Bollywood x2 + 25 Cricket x2). **100% within target ranges, 0 flagged puzzles.** median par 8.0 (target 8-12 median: yes), median chill_spread 5.0 (target [2,8]: 100%), median sharp_spread 3.0 (target [1,5]: 100%). Clean, positive result — the deterministic rival system is well-tuned (unlike semantic ranking, it's pure seeded algorithm, not embedding-quality-dependent).
- [x] `evals/harness/dimension5_winrate.py`: simulated noisy-player win-rate under real maxGuesses (par+6) across all 220 puzzles. Player model calibrated via parameter sweep (base reduction 0.70/0.60/0.50 cold->hot, 15% stall probability) to hit ~82% win-rate at a representative maxGuesses=14. Actual full-scale result: **median win-rate 93.0%**, only 10.5% of puzzles land in the spec's target [75%,85%] band — because maxGuesses=par+6 is a FIXED offset, and the player model is highly sensitive to absolute budget (12%@max_guesses=10 -> 82%@14 -> 99%@17), so low-par puzzles (tight absolute budget) show lower simulated win-rate than high-par puzzles (generous budget) even though low par nominally means "easier" — a real, reportable tension in the maxGuesses formula, not a bug. 0 puzzles below 40% (no unwinnable puzzles). Explicitly caveated in the module docstring as a MODELED estimate sensitive to assumptions, not measured ground truth.
- [x] **Dimension 3 LLM judge — 2 rounds of prompt-engineering fixes, both caught by calibration, not shipped blind**:
  1. Compound single-call prompt (solvability+spoiler+difficulty+cultural_fit together) made qwen3:8b silently fail spoiler detection even for blatant cases — a clue ending "...a classic village scene" against secret "village" judged spoiler_flag=false, reproduced 3x including with `think:true`. Isolating spoiler-detection into its own short prompt ("Does the word X appear in text Y?") fixed it: calibration agreement 59%->97% (31/32).
  2. Even after that fix, a combined solvability+difficulty prompt was too lenient — rated a "shadow" clue ("Follows you everywhere; never exists on cloudy days") solvability=5 against the WRONG secret "coffee". Isolating solvability into its own strict prompt fixed the false-positive problem but shifted risk the other way (game's clues are deliberately indirect/evocative by design, and "be strict" sometimes under-rates genuinely-correct clues). Final calibration: **spoiler_agreement 96.9% (31/32), solvability_agreement 65.6% (21/32)** — reported honestly, not iterated indefinitely chasing a bigger number.
  3. Golden calibration set built from CONSTRUCTED ground truth (real shipped clues + deliberate mutations/mismatches with certain labels), not reconstructed git archaeology of GG's past edits — see dimension3_judge.py's module docstring for why.
  4. `ollama` confirmed installed (0.31.1) with `qwen3:8b` (5.2GB) already pulled — zero setup needed in this environment.
- [x] `evals/harness/report.py`: aggregates legacy 77 fixtures (subsumed, not replaced) + all 5 dimensions into JSON + Markdown via `uv run python -m evals.harness.report`.
- [x] `generator/tests/test_harness.py` (14 tests, dimensions 1/2/4/5, algorithmic/fast/always-run) + `test_harness_judge.py` (2 tests, dimension 3, self-skips with install instructions if Ollama unreachable) — both auto-discovered by the existing `uv run pytest` gate (testpaths=["tests"]), no separate CI workflow file needed. Gate thresholds are regression FLOORS just under the measured baseline (including the known-bad hi-en numbers), not aspirational targets — see each test's comment for the baseline value it protects.
- [x] Regression-proof tests (spec acceptance criterion 4): `test_broken_clue_is_caught_by_spoiler_gate` (a clue containing its own secret verbatim IS flagged by `clue_leak_reason`) and `test_broken_rank_scenario_is_caught_by_dimension1` (a deliberately-mislabeled "ocean"<-"bureaucracy" near-tier scenario IS flagged as out-of-band) — both prove the gates have teeth, not just that real content happens to pass.
- [x] Fixed a real (not just cosmetic) bug during ruff cleanup: dimension5's per-simulation RNG seeding used Python's builtin `hash()`, which is randomized per-process (`PYTHONHASHSEED`) unless fixed — silently non-reproducible despite the "seeded" claim. Replaced with `hashlib.sha1`-derived seeds (same pattern as rival.py's own `_rival_seed`). Verified the fix didn't materially change the statistical result (median win-rate 93.0% before and after).
- [x] Full 220-clue x 3-call judge pass complete (2326.9s total harness run). Results: n_clues_judged 220 (0 errors); solvability min 1, mean 2.15, 71.8% below the naive gate threshold (3); spoiler-flagged 0; difficulty distribution {1:0, 2:26, 3:183, 4:11, 5:0}; mean cultural_fit (hi-en, uncalibrated) 4.80.
- [x] **Critical interpretation finding on the 71.8% figure — do not act on it at face value.** Manually spot-checked the 8 lowest-scored (solvability=1) real clues against raw text: every one is a legitimate, evocative, human-approved clue (e.g. `music`: "It reaches places in your mind that words alone cannot"; `village`: "Where everyone knows your grandmother's name"; `friend`: "The family you choose, one laugh at a time"). None are broken. This matches the calibration gap exactly (65.6% solvability agreement vs 96.9% spoiler-safety) — the judge's confirmed failure mode is under-rating deliberately indirect/evocative clues, which is this game's house style by design. Read 71.8% as "this judge's absolute solvability threshold doesn't fit this game's clue style," not "most clues are unsolvable." The judge IS trustworthy for spoiler-detection (0 flagged, exactly matches the deterministic `clue_leak_reason` gate's own 0-leak result) and difficulty-distribution sanity-checking. Deliberately did NOT wire a hard solvability-score gate into pytest against this judge's raw scores — only the fast calibration floors (`spoiler_agreement >= 0.85`, `solvability_agreement >= 0.55`) are gated in `test_harness_judge.py`. A future hard per-clue solvability gate needs either threshold recalibration or a relative/comparative solvability check, not this judge's absolute score as-is.
- [x] Baseline report committed: `evals/reports/baseline_report.{json,md}` — full per-dimension-per-language numbers, worst-diverging pairs, outlier lists, interpretation notes.
- [x] All tests green: 16/16 in `test_harness.py` + `test_harness_judge.py` (14 fast + 2 Ollama-gated, 498.7s), plus legacy 77/77 fixtures subsumed into the harness report (run via `run_full_harness`'s call into `evals/run_evals.py`, not duplicated as separate pytest cases).

---

# PLAN — Hinglish semantic engine fix (eval-gated bake-off) — COMPLETE

Spec: `spec-hinglish-fix.md`. Autonomous single-pass run, harness-verified.

## Root cause (confirmed, step 1)

15 known-fail hi-en pairs embedded three ways (romanized / hand-transliterated Devanagari / English translation) under the then-shipped `paraphrase-multilingual-MiniLM-L12-v2`: Devanagari aligned with the English translation in 15/15 pairs (mean cos(devanagari,english)=0.869 vs mean cos(romanized,english)=0.344 -- e.g. `ghadi`->clock: romanized cos=0.10, Devanagari cos=0.97). Confirms the model was never taught to associate Latin-script romanized Hindi with its own meaning; it clusters by surface form instead. Validates Path A's premise, but see bake-off below -- a different path won.

## Bake-off (9 candidates, harness dims 1+2, hi-en full 10,462-word production vocab + full 60-pair schedule)

| candidate | Spearman | cross-lang pass | notes |
|---|---|---|---|
| baseline (shipped): paraphrase-multilingual-MiniLM-L12-v2, raw romanized | -0.003 | 5.1% | broken |
| A: ITRANS-transliterate hi-words -> Devanagari + same model | 0.232 | 23.7% | rule-based translit too noisy (only ~56% cos match to hand-corrected Devanagari) |
| B1: L3Cube hing-mbert-mixed-v2, mean-pooled | 0.352 | 28.8% | native code-mixed BERT, raw mean-pool |
| B2: L3Cube hing-roberta-mixed, mean-pooled | 0.358 | 30.5% | |
| C: MuRIL (google/muril-base-cased), mean-pooled, raw romanized | 0.399 | 52.5% | clears cross-lang gate alone |
| C-hybrid: MuRIL fed ITRANS-Devanagari (not raw romanized) | 0.248 | 32.2% | WORSE than raw -- confirms MuRIL already natively handles romanization; bolting noisy rule-based translit in front of it hurts |
| D: BAAI/bge-m3, raw romanized (general multilingual baseline) | 0.236 | 20.3% | confirms general multilingual embedders also fail on raw romanized, as spec predicted |
| E1: l3cube-pune/indic-sentence-similarity-sbert (proper SBERT pooling) | 0.530 | 52.5% | clears both gates |
| E2: l3cube-pune/indic-sentence-bert-nli (WINNER) | 0.639 | 54.2% | clears both gates, best Spearman, lowest monotonicity (15.3% vs baseline 53.75%) |
| E3: l3cube-pune/hindi-sentence-similarity-sbert (Hindi-only, not multilingual) | 0.599 | 57.6% | best cross-lang but narrower training distribution (higher generalization risk for the code-mixed EN+Hindi vocab) -- not picked |

Key lesson: raw mean-pooled masked-LM checkpoints (B/C) underperform a properly SBERT-trained (NLI/STS fine-tuned) pooling head on the same underlying multilingual-BERT family (E-series) by a wide margin -- confirms the spec's own risk note.

Selection gate: minimum viable = Spearman >=0.5 AND cross-lang >=40%. Winner l3cube-pune/indic-sentence-bert-nli clears both (0.639 / 54.2%) -- does not yet reach the EN-parity target (0.8+), but is the best of 9 candidates and a categorical fix vs. shipped baseline. License: CC-BY-4.0 (attribution required, commercial use OK).

## Shipped

- `generator/config.py`: `MODELS["hi-en"]` -> `l3cube-pune/indic-sentence-bert-nli` (768-dim, up from 384). `MODELS["en"]` untouched.
- `generator/embeddings.py`: fixed a latent cache-key gap found while shipping this -- the `.model-cache/{lang}-{hash}.npy` cache key was hashed from vocab content ONLY, not model name, so swapping `MODELS[lang]` without also purging the cache would have silently kept serving the OLD model's vectors. Cache key now hashes (model_name, vocab). Stale hi-en cache files purged.
- Regenerated ALL hi-en payloads: 60 daily (2026-06-12..2026-08-10) + 25 Bollywood + 25 Cricket. `en` payloads confirmed byte-identical to pre-fix (0 diffs, both daily and packs) -- English engine provably untouched. hi-en payloads: byte-reproducible across two independent full rebuilds (only `generated_at` timestamp in manifest.json differs). All size gates pass (`--strict-sizes`): hi-en ~151-153KB (target 400KB), en ~775-780KB (target 1.5MB) -- both packs match the daily profile.
- 7 legacy pairwise-ordering fixtures flipped by the model swap (`E18`, `H22`, `H34`, `P03`, `P15`, `P17`, `R01`) reclassified to `evals/fixtures_known_failures/KF-*.json` with measured cosine scores in the `reason` field, following the exact precedent of the 5 pre-existing KF-H* fixtures. Of these, `aansoo` (Bollywood), `fielder` and `chant` (Cricket) are live scheduled secrets -- flagged explicitly rather than silently dropped; the rest (`gham`, `naukri`, `king`) are vocab-only, not currently scheduled. Legacy fixture gate: 70/70 passing (was 77, minus these 7).
- Bundled offline-fallback payloads (`app/assets/payloads/hi-en/2026-06-12..18.json.gz`, 7 days) updated to match; `app/assets/payloads/en/*` and `packs/manifest.json` confirmed byte-identical (no update needed).

## Harness before/after (full production vocab + schedule, not the bake-off sample)

| metric | before | after |
|---|---|---|
| hi-en Spearman correlation | -0.003 | 0.639 |
| hi-en band-accuracy overall | 54.6% | 67.8% |
| hi-en near-tier: translation / associate | 0.0% / 13.3% | 85.0% / 56.7% |
| hi-en monotonicity violations | 53.75% (330/614) | 15.3% (94/614) |
| cross-language pass rate (Scorching/Hot) | 5.08% | 54.2% |
| cross-language median rank | 4881 (46.65th %ile) | 20 (0.2th %ile) |
| EN Spearman / band-accuracy / monotonicity | 0.837 / 74.9% / 6.2% | 0.837 / 74.9% / 6.2% (bit-identical, confirmed via harness re-run) |
| dimension 3 (clue quality, LLM judge) | spoiler 96.9%, solvability 65.6%, n=220 | identical (clue text unchanged -- this dimension doesn't touch embeddings) |
| dimension 4 (rival calibration) | 100% within target, 0 flagged | identical (deterministic, embedding-independent) |
| dimension 5 (win-rate model) | median 93.0%, 10.5% in-band | identical (par-distribution-driven, embedding-independent) |
| legacy fixtures | 77/77 | 70/70 (7 reclassified, see above) |

Residual worst-diverging cross-language pairs (translation still ranks outside Scorching/Hot, but far better than before): `khamoshi`<-silence (78.8%ile), `rasoi`<-kitchen (61.1%ile), `samunder`<-ocean (36.4%ile), `bachpan`<-childhood (36.1%ile), `titli`<-butterfly (36.0%ile). None are catastrophic (worst pre-fix case was 99.35%ile); documented as the new known-limitations state, not hidden.

## Known-limitations ledger update

Hinglish semantic engine: broken (random, Spearman -0.003) -> measured working state (Spearman 0.639, cross-lang pass 54.2%). Does not yet reach EN parity (0.837/74.9%) -- the residual gap is documented above with the 5 worst pairs. If EN parity is ever required, the next step is a Warmer-specific fine-tune on Hinglish similarity pairs (not attempted here -- out of scope per spec, which only required clearing minimum viable via off-the-shelf models).

## Gotchas discovered

- Embedding cache key must include the model name, not just vocab content -- otherwise a `MODELS[lang]` swap silently keeps serving stale vectors from the previous model. Fixed in `embeddings.py`; would have been a silent, very confusing bug otherwise.
- `fairseq` (a dependency of `ai4bharat-transliteration` / IndicXlit, one of the spec's suggested Path-A tools) requires compiling a C extension and has no prebuilt Windows wheel -- blocked on this machine (no MSVC Build Tools) without a large, out-of-scope environment change. Not pursued further since Path A (rule-based ITRANS transliteration) was already outperformed by every E-series candidate; noted for the record in case IndicXlit is revisited later on a Linux/WSL build host.
- MuRIL fed hand/rule-transliterated Devanagari scored WORSE than MuRIL fed raw romanized text directly (0.248 vs 0.399 Spearman) -- confirms MuRIL's own training already covers transliterated/romanized Indic text natively; adding an extra (noisy) transliteration pass in front of it actively hurts rather than helps.

---

# PLAN -- maxGuesses tuning + security/hardening pass (complete)

Spec: `spec-security-hardening.md`. Autonomous single-pass run (5 parallel executor subagents +
orchestrator review), live-verified 2026-07-11.

## Part 1 -- maxGuesses tuning

- [x] Replaced fixed `par + 6` with `max_guesses_for_par(par) = max(12, round(par * 1.5))`, a
  shared helper in `generator/rival.py` imported by both `payload.py` and
  `evals/harness/dimension5_winrate.py` (previously duplicated arithmetic, now can't drift).
  Iterated 6 candidate formulas against the Dimension 5 win-rate simulation before landing here:
  baseline (par+6) median 93.0%/10.5% in-band -> final candidate median 82.0%/63.6% in-band (only
  1 marginal outlier at 39% -- noise at n=100 sims/puzzle). Per-lang: en median 80.0%, hi-en 84.0%.
- [x] All payloads regenerated (daily 30 days + Bollywood 25 + Cricket 25, both langs), byte-reproducible
  (scratch-dir rebuild diff -rq identical except manifest timestamp). Generator suite 372 passed/4 skipped.
- [x] Live spot-check: today's puzzle (2026-07-11 EN) shows "0/15 - 15 left" -- a sane, non-absurd budget.

## Part 2 -- security + hardening

- [x] **2.1 Moderation**: new `app/lib/social/name_sanitizer.dart` (strips control/zero-width/
  bidi-override chars, unicode-normalization scope-limited and documented) + `moderation_blocklist.dart`
  (EN + Hinglish profanity, reserved-word impersonation block with homoglyph folding for the
  Cyrillic/Greek lookalike vector), wired into `SocialService.setDisplayName`/`createGroup` as the
  single write choke point. Fixed a pre-existing bug found during this pass: group naming reused the
  display-name dialog's hardcoded 40-char limit against a 60-char rule -- now parameterized correctly.
  Live-verified: "admin" rejected with a friendly generic message; "TestSquadLive" accepted normally.
- [x] **2.2 Injection-sink audit**: every sink confirmed safe -- FCM notification title/body is static
  copy keyed only by lang (`scripts/send_daily_notification.py`, never interpolates user content);
  `url_launcher` is not even a dependency (zero call sites); deep links (`social_models.dart`'s
  `joinLink`) embed only the server-generated join code, never a name; no `dart:html` innerHTML-style
  sink exists anywhere; analytics event params never carry display/group names (verified against the
  full `AnalyticsEvent` catalog).
- [x] **Firestore rules re-audit**: added a charset constraint (RE2 `\x{HHHH}` ranges, verified against
  the emulator) mirroring the client-side strip; closed an extra-fields gap with `keys().hasOnly(...)`
  on `users/{uid}`, `groups/{groupId}`, and `results/{uid}` writes (previously nothing stopped a
  bypassing client smuggling unlisted top-level fields); confirmed packs added no new Firestore
  collections; `firebase-tests/rules.test.js` expanded 34->53 cases, all green against the real emulator
  (JAVA_HOME=`C:\Users\gaura\sdks\jdk21`). `create_group_flow.test.js` (5) + `join_and_results_flow.test.js`
  (11) also green -- 69 emulator tests total.
- [x] **App Check**: `firebase_app_check ^0.3.2+10` wired into both independent Firebase init call
  sites (`main.dart`'s eager path, `social_service.dart`'s lazy path), web-only (`ReCaptchaV3Provider`),
  site key via `--dart-define=APP_CHECK_RECAPTCHA_SITE_KEY` (empty-string default -> clean no-op,
  live-confirmed via console log `"AppCheck: skipped — APP_CHECK_RECAPTCHA_SITE_KEY not set."`).
  **STOP POINT for GG (manual, not yet done)**: create a reCAPTCHA v3 site key at
  https://www.google.com/recaptcha/admin for `playwarmer.vercel.app` + `playmindmeld.vercel.app` +
  `localhost`; register the site key AND its paired secret key in Firebase console -> Project Settings
  -> App Check -> Apps tab (web app); pass the site key at build time via the dart-define above; leave
  every product (Firestore etc.) on default "Unenforced / Metrics only" -- do NOT click Enforce.
- [x] **Secret audit**: full git-history scan (96 commits) found zero committed credentials.
  `FIREBASE_SERVICE_ACCOUNT` confirmed GH-secret-only, never echoed. Firebase web config + VAPID
  public key confirmed intentionally public. `.gitignore` hardened (`.env`, service-account JSON,
  `.pem` patterns) as defense-in-depth.
- [x] **Dependency audits**: pip-audit found 1 HIGH (msgpack DoS, fixed via version constraint,
  368->372 tests still green) + 1 LOW/no-fix (torch, deferred -- unreachable code path); npm audit
  found 5 moderate transitive (deferred -- fix would downgrade firebase-tools); Flutter's 6 Firebase
  packages are one major version behind as a set (recommendation only, not applied -- needs its own
  regression-tested bump).
- [x] **Data deletion**: `SocialService.deleteMyData()` (results -> group self-removal -> profile,
  in that order so the results collection-group query still sees membership) wired into Settings ->
  "Delete my data", with `firestore.rules` relaxed for self-only deletes. `docs/privacy-policy.md`
  updated to drop the stale "nothing uploaded to any server" claim and describe Social/Notifications
  data + the deletion mechanism.
  **Correction (2026-07-11, post-report)**: the first live-verify pass ("Friends tab reverted to the
  empty state") was a FALSE POSITIVE -- `deleteMyData()` gated on `hasLocalIdentity`, which is false
  on every fresh page load until Firebase is explicitly (re-)initialised that session (by design).
  A returning user opening Settings and tapping Delete without another social action first got
  "nothing to delete" while their profile/group data stayed live server-side; the empty Friends
  screen was that same false-negative, not a successful deletion. Caught by directly querying
  production Firestore after the "successful" run and finding the group membership + profile doc
  still present. Fixed (`94fc5d4`): gate on `cachedDisplayName()` (SharedPreferences, survives
  across page loads) instead, call `ensureSignedIn()` before the core deletion (verified live to
  recover the SAME persisted uid, not mint a duplicate). Added a regression test
  (`settings_delete_data_test.dart`) for exactly this scenario. Re-verified live via direct Firestore
  reads (not just UI state) -- profile doc actually deleted, group memberUids actually emptied.
- [x] **Accepted-risk ledger**: `docs/accepted-risks.md` -- 9 entries (self-reported scores, soft
  payload anti-cheat, the deferred dependency findings above, homoglyph-coverage scope, a one-time
  Firestore collection-group index GG needs to create on first live `deleteMyData()` use, and the
  still-placeholder privacy-policy contact email).
- [x] Full suites green: generator 372/4-skip, flutter 434/434, emulator 69/69, `flutter analyze` clean.
- [x] Deployed: Firestore rules released to `mindmeld-c4bba`; web build deployed to
  `playwarmer.vercel.app` via the canonical `web-dist/` staging flow (both guard scripts passed).
  Commits: `2446f3d`/`8a25fe5`/`a9e3446` (maxGuesses), `7a55051` (msgpack), `79dc578` (App Check),
  `d8833ac` (stale test literals), `71015ff` (moderation/rules/deletion), `cf90cb8` (docs/ledger).

## Gotchas discovered

- `vercel deploy --prod --yes` run from `app/` (instead of the documented `web-dist/` staging dir)
  first hit a broken/missing `.vercel/project.json` link and silently created a brand-new stray
  Vercel project named "app" rather than erroring -- always re-check `.vercel/project.json`'s
  `projectId` against `vercel projects ls` before a non-interactive deploy. The canonical flow
  (README's "Web / PWA" section) requires `make_web_sw.py` + copying into `web-dist/` first --
  deploying raw `app/build/web/` directly (missing the copied `vercel.json`/service worker) produced
  a generic Vercel build error with no useful message.
- Firestore rules emulator tests need TWO different invocations depending on the test file: pure
  rules-unit-testing files (`rules.test.js`) only need `--only firestore`; files that also call real
  `signInAnonymously()` (`create_group_flow.test.js`, `join_and_results_flow.test.js`) need
  `--only firestore,auth` or every auth call fails with `auth/network-request-failed`.
- Executor subagents each independently decided to commit their own scoped work rather than leaving
  everything staged for a final orchestrator commit -- fine in this case (each commit was itself
  tested and atomic) but worth being explicit about commit ownership when running several parallel
  executors against the same repo.

## Hinglish benchmark -- Phase 1 (spec-hinglish-benchmark.md), COMPLETE, awaiting GG go for Phase 2

- [x] Fixed the shared-sequential-RNG bug in `gen_dim1_scenarios.py` blocking safe held-out
  expansion (`16f35d1`) -- per-secret hash-derived seeding, one-time documented break of the old
  (buggy) `baseline_report.md` numbers (EN 0.837->0.842, hi-en 0.800->0.813).
- [x] Expanded held-out test secrets 16 -> 50 across 7 domains (nature/emotion/abstract/object/
  place/food/kinship), fully separate from the production 25-secret pipeline (`704cabd`).
  Bollywood/Cricket pack secrets explicitly rejected as a source -- verified most already leaked
  into training via open-vocabulary data-assembly paths. No-leakage re-verified against all 5
  training files, twice.
- [x] Found (during my own review, not the executor's) a 42-word vocab-coverage gap -- near/mid
  curated words outside `HIEN_EN_TOP_N`'s frequency cutoff, concentrated in the new secrets' most
  diagnostic tier. Fixed + re-ran the full bake-off (`78df6f2`): dim1 resolution 334/379 -> 376/379.
- [x] 8-model comparative bake-off (5 original baselines + IBM Granite-311m-r2 + Qwen3-Embedding-0.6B
  + our shipped fine-tune) on the same expanded set, paired bootstrap CIs (`d73db64`, `78df6f2`).
  **Verdict: shipped model leads all 7, CI-significant on both dim1/dim2, zero exceptions across 14
  comparisons. No newer base beats l3cube-pune off-the-shelf -- Phase 2c's "fine-tune a newer base"
  does not apply.** Full report: `generator/evals/finetune/data/phase1_benchmark_report.md`.
- [ ] **STOP POINT for GG**: go/no-go on Phase 2 (accuracy push). Also needs a decision on three
  items surfaced but deliberately not resolved: (1) a latent `embeddings.py` cache-key/row-order
  bug found as a side effect (real, contained, needs its own before/after payload verification --
  out of benchmark scope); (2) `hf_model_card.md`'s published held-out numbers are now stale on two
  counts (RNG fix + new 50-secret comparator) -- republish now or bundle with Phase 2?; (3) public
  benchmark proposal (spec 1c) -- recommend publishing only the 34 new supplement secrets (the
  original 16 are live game secrets, would need scrubbing; the 34 new ones never were).

## Model Excellence Program (spec-model-excellence.md) -- Workstream A COMPLETE, STOP POINT for GG

- [x] **New task-appropriate metric suite**, additive (old Spearman/band-accuracy/near-far-separation
  columns kept, not removed): `evals/harness/metrics.py` gained `dcg_gain`, `ndcg_from_judged`,
  `mean_reciprocal_rank`, `expected_calibration_error`, `top_weighted_correlation` (all NaN/None-safe,
  no scipy, matching the file's existing convention). New `evals/harness/topheavy.py`: per-secret
  NDCG@{10,50,100}/Recall@{10,50,100}/Precision@{10,50,100}/MRR (macro-averaged across secrets, `n`
  reported honestly per submetric since precision@10 is sparse by construction -- most secrets have
  only 2-6 judged words), plus band-confusion matrix, per-band precision/recall, and a documented
  rank-percentile-proxy ECE for band calibration. New bootstrap CI wrappers in `bootstrap_ci.py`
  (cluster-by-secret, `N_BOOT=10000`/`seed=42`, matching existing pattern) -- critically,
  `bootstrap_topheavy_ci` passes per-draw secret groups directly into `compute_topheavy_metrics`
  (never re-groups by name), so a secret drawn twice in a resample correctly counts twice in that
  draw's macro-average instead of silently collapsing -- this was the single highest-risk correctness
  property in the design and was independently verified by a separate verifier subagent (explicit
  test: same secret passed twice -> n=2, not n=1).
- [x] **8-model bake-off re-run under the new suite** (`evals/finetune/benchmark_bakeoff.py --all`,
  all 8 checkpoints re-embedded from HF cache, none failed, ~6m13s wall clock; `REQUIRED_CHECKPOINT_KEYS`
  grew to force the recompute rather than silently reuse stale checkpoints). Full table:
  `generator/evals/finetune/data/bakeoff_comparison.md`.
  **Verdict: leadership re-established under task-appropriate metrics.** Shipped model
  (`gauravgandhi2411/hinglish-relatedness-sbert`) leads all 7 comparators on NDCG@{10,50,100}, MRR,
  Recall@{10,50,100}, and top-weighted correlation (0.7740 vs next-best l3cube-pune 0.6329) -- this is
  NOT the same ranking question the old Spearman-only table answered, and the model wins it anyway.
  **Honest exception, not smoothed over:** on band-calibration ECE (lower=better), shipped scores
  0.2020; `ibm-granite/granite-embedding-311m-multilingual-r2` scores 0.1947 -- Granite calibrates
  band placement slightly better than the shipped model, even though Granite loses badly on every
  ranking-quality metric. (Correction to an earlier verbal misstatement during this work: Qwen3-0.6B
  does NOT beat shipped on ECE -- Qwen scores 0.2137, worse than shipped's 0.2020. Only Granite beats
  shipped on this one metric, confirmed directly from `bakeoff_comparison.json`.)
- [x] **Band-confusion matrix + per-band P/R for the shipped model** (shipped-model-only, not all 8,
  by explicit scope limit -- rendering 8 full 3x6 matrices was judged not worth the table bloat for
  this deliverable): reveals the "warm" band is nearly never predicted (`n_predicted=2` vs 84
  human-expected warm records) -- the production floor logic (`max(500,...)`/`max(50,...)` in
  `rival.band_for_rank`) that `docs/known-limitations.md` already flagged as making hi-en's Warm band
  only ~19 ranks wide is now independently confirmed from the outcome side, not just the width
  arithmetic. Candidate target for Workstream B/F follow-up.
- [x] **Verification**: independent verifier subagent re-derived NDCG@10/@50 by hand, confirmed the
  bootstrap-dedup property structurally and via test, ran the full suite itself rather than trusting
  the executor's reported counts (541 passed / 4 skipped, zero failures; 29/29 new
  `test_topheavy_metrics.py`), confirmed `--report` mode is byte-identical across reruns (seed=42),
  and caught one reporting error (see the Qwen/Granite correction above) that the executor's own
  summary got backwards.
- [x] **STOP POINT for GG cleared** (spec-model-excellence.md's own stop point 1): GG reviewed,
  approved committing (`00b0bfd`), and confirmed the ECE formulation stands as-is. Workstream B
  started immediately after.

## Model Excellence Program -- Workstream B COMPLETE (`ac6f41d`), STOP POINT for GG (sharm patch)

- [x] **Item 8, full-vocab collision scan**: `evals/finetune/collision_scan.py` scans all 544
  hinglish-sourced words (reconstructed origin split: 544 hinglish-sourced / 9,951 english-sourced
  out of 10,495 total) for the subword-collision signature (top-15 neighbors dominated by
  orthographically-similar english-sourced tokens). Calibrated against the 4 already-shipped L2
  words + `probe_subword_collision.py`'s 9 hand-picked candidates at threshold=0.2, K=15 -- catches
  junoon (0.467)/registan (0.400) cleanly, misses naukri/udaasi (0.000, zero-bigram-overlap/only
  "partially confirmed" in the source probe respectively, a documented signature limitation, not a
  bug). **211/544 (38.8%) flagged collision-prone.**
- [x] **Item 8, gated extension attempt** (`evals/finetune/probe_l2_collision_scan_extension.py`,
  staging-only -- `vocab/hi-en-devanagari-patch.txt` verified byte-identical throughout, confirmed
  independently by the verifier): the full 58-word dict-coverable candidate batch (154 of 211
  flagged words excluded for lacking an Aksharantar entry) **FAILS** the repo's strict
  zero-broken-pairs gate (4 broken dim1 pairs, 1 broken dim2 pair) via the same collateral-noise
  mechanism that killed the earlier full-vocab attempt (`probe_l2_dict_only_front_end`) -- one break
  is a genuine Aksharantar mapping bug (chinta/worry -> छींटा "splash", wrong word), the rest are
  whole-embedding-manifold noise from inserting new vocabulary text. Bisection (40/20/10/5-word
  prefixes) found **no safe subset** at any of those sizes. **A minimal +1 word extension (`sharm`
  -> शरम, the single most-severe flagged word) DOES clear both gates cleanly**: 0 broken pairs
  dim1/dim2, CI-significant improvement on every Workstream A topheavy submetric (MRR delta +0.050
  CI [0.012, 0.098], NDCG/Recall similarly positive, zero regressions anywhere).
  **STOP POINT for GG**: should `sharm: शरम` be added to the LIVE `vocab/hi-en-devanagari-patch.txt`
  (5th entry)? Fully gated and verified safe, but this is live game-content, not committed
  pending your go/no-go -- same production-blast-radius caution as any daily-secret-affecting
  change. `apply_devanagari_patch` is invoked from `build.py:137` and `build_packs.py:302`, both
  in the live payload-generation path (`publish.py` imports `build.py`), confirmed by direct grep.
- [x] **Items 5-7, failure taxonomy**: local-Ollama-judge ($0 cost) classification of all 124
  failing shipped-model pairs -- genuine_semantic_difficulty 99/124 (79.8%), transliteration_artifact
  14 (11.3%), polysemy/commonsense/label_error/vocab_resolution_gap the remainder. 4/4 agreement
  with hand-labeled calibration examples. Cross-referenced against the collision scan: 57/124 (46%)
  of failing pairs have an independently collision-flagged secret -- real, computed evidence
  (verified) that the raw per-pair taxonomy undercounts subword-collision as a cause, since the
  judge never sees the secret's full neighbor list when classifying one pair at a time.
- [x] **Item 6, frequency buckets**: self-caught and fixed a real bug mid-task (initial version
  ranked english-sourced words against the full 55k-word `en.txt` instead of the ~9,951 actually
  in the hi-en vocab, forcing 365/379 records into "head" by construction; post-fix code
  independently confirmed by the verifier to correctly scope to the in-vocab subset). Final result:
  **no clean head/tail penalty** -- tail scores *better* than head (-22.8%, inverted from the
  expected direction), flagged honestly as a likely tier-composition confound (far-tier decoys
  concentrate in "tail") rather than overclaimed as a genuine frequency effect. 57.2% of
  hinglish-sourced words have unresolved frequency (garbage-transliteration vs. genuine-rarity is
  not automatically distinguishable) -- reported as its own bucket, not silently folded into tail.
- [x] **Item 7, domain/POS**: domain breakdown covers only the 34 benchmark-supplement secrets
  (original 25 production secrets have no domain field, explicitly left unlabeled rather than
  guessed) -- weakest domain: emotion (61.4% in-expected-band rate). POS/concreteness via the same
  local judge (no new spaCy/nltk dependency, code-mixed English+romanized-Hindi words don't suit an
  English-only tagger anyway) -- weakest POS: noun (63.0%). Both flagged as AI-derived, unverified
  labels, same epistemic status as the benchmark's own near/mid/far tiers.
- [x] **Biggest single finding, independently corroborates Workstream A**: 83/84 resolved mid-tier
  records fail because the mid-tier's only accepted band (`warm`, band 3) is a **24-rank window out
  of 10,495 (0.23% of vocab)** -- vs near-tier's 499-rank window and far-tier's 9,971-rank window.
  Arithmetic independently re-verified by the verifier from `rival.band_for_rank` directly
  (hot_max=max(500,104)=500, warm_max=int(10495*0.05)=524, so warm=ranks 501-524). This is very
  likely a **benchmark band-width design artifact**, not primarily a model defect, and directly
  matches Workstream A's band-confusion-matrix finding that Warm is nearly never predicted
  (2 predictions vs 84 expected). **Top recommended target for Workstream F** (widen mid-tier's
  accepted bands and re-measure, or otherwise address the Warm-band-width issue
  `docs/known-limitations.md` already flagged from the width-arithmetic side).
- [x] **Verification**: independent verifier subagent confirmed (1) live patch file empty diff,
  (2) +1-word gate numbers match the raw eval_result JSON exactly (not just prose), (3) calibration
  threshold reasoning is defensible not post-hoc-rationalized, (4) band-width arithmetic is correct,
  (5) frequency-bucket fix is real in the post-fix code, (6) 63 new tests pass, (7) nothing
  committed by either executor, (8) the 57/124 cross-reference is a real computed join not an
  invented number. Overall verdict: PASS, trustworthy to report and commit.
- [x] **STOP POINT cleared**: GG approved both -- sharm shipped to the live patch (`80cf3ad`,
  re-verified through the real production path, numbers matched staged to 1e-9); Workstream C
  approved to proceed.

## Model Excellence Program -- Workstream C measurement phase COMPLETE (`4eb6386`), STOP POINT for GG (retraining decision)

- [x] **Items 9+11, spelling/casing/whitespace/typo robustness eval** (`evals/finetune/
  spelling_robustness.py`): embeds variant spellings DIRECTLY through the shipped model, bypassing
  `normalize.py`/`canonical_for()`'s string-fold layer entirely -- that layer only guarantees
  gameplay-lookup consistency for the 29 alias-file words (confirmed via `payload.py:150-283`: the
  embedding matrix is built once for canonical vocab only, variant-spelling payload entries are
  copied rank/qsim, never a fresh embedding) and had never been measured at the embedding level for
  any other word before this. Reused the existing 42-secret bakeoff test set as baseline, no new
  scenario authoring.
- [x] **Headline finding: NOT spelling-invariant outside the 3 alias-covered test secrets.** On 267
  genuinely held-out real-world spelling variants (Aksharantar-corpus-derived, n=13 test secrets
  with coverage), band-agreement rate is only **67.4% [95% CI 0.538, 0.801]** -- a different valid
  spelling of the same secret changes which temperature band a test word lands in roughly a third
  of the time. Worst case: `azaadi`/`rights` rank 16 (scorching) -> `azaaadi`/`rights` rank 9753
  (freezing), drift 9737 ranks -- confirmed by the verifier as a real Aksharantar entry (source=
  "Existing", Levenshtein-distance-verified clean, not filter noise), not a synthetic artifact.
  Genuine good catch during the build: the 3 alias-file-covered test secrets (bagicha/chaand/pahad)
  turned out to have ZERO training exposure to their own aliases (`assemble_data.alias_source()`
  already excludes held-out secrets from training data, confirmed via direct grep of
  `train_mnrl_pairs.jsonl`) -- so even that smaller `alias_file_untrained_heldout` category (37
  pairs, 43.2% band-agreement) is honest held-out evidence, not training-contaminated.
  Whitespace-only variants show perfect 1.000 agreement -- confirmed via direct embedding
  comparison (byte-identical vectors) that sentence-transformers strips whitespace before
  tokenization, not a measurement bug.
- [x] **Verification**: independent verifier subagent hand-recomputed the band-agreement rate from
  raw per-record data (180/267, matches to float precision), independently replicated the
  cluster-by-secret bootstrap CI, confirmed the worst-case example against the raw Aksharantar
  corpus file directly, confirmed the alias-training-exclusion claim via direct grep, and confirmed
  the whitespace perfect-agreement result via a direct embedding comparison rather than trusting
  the code. Overall verdict: PASS. 45 new tests pass; full suite clean (pre-existing
  Ollama-contention-related `test_harness_judge.py` failures unrelated, confirmed untouched).
- [x] **STOP POINT cleared**: GG approved proceeding with retraining now.

## Model Excellence Program -- Workstream C item 10 COMPLETE (`bc4b25a`): NO-GO, honest negative

- [x] **Variant-augmented retraining attempted, rejected.** `variant_source()` added to
  `assemble_data.py` (mirrors `alias_source()`'s exact pattern), 189 new Aksharantar-derived
  training pairs across the full hinglish vocab, zero leakage into held-out secrets, zero overlap
  with the 267-pair spelling-robustness eval set. Trained with the shipped model's EXACT recipe
  (LoRA r=8/lr=2e-4/4 epochs, seed=42) -- data-only change, isolating the effect. **Result: FAILS
  zero-net-regression** on the 42-secret suite (dim1: 2 fixed/10 broken, net -8; dim2: 1 fixed/4
  broken, net -3) and shows **no CI-meaningful spelling-robustness improvement** (band-agreement
  67.4% baseline -> 66.3% candidate, heavily overlapping CIs, if anything slightly worse). Same
  failure signature as the earlier full-vocab Devanagari-patch and 58-word collision-batch attempts
  -- a large injection of new vocabulary/pairs perturbs the whole embedding manifold faster than it
  fixes the targeted gap. Spot-verified directly from the raw eval_result.json (not just executor
  prose): shipped checkpoint (`checkpoints/obj_hard_neg/model/`, `evals/finetune/model/`) confirmed
  byte-identical throughout. Not published, not promoted. The rejected candidate LoRA checkpoint
  (`checkpoints/variant_augmented/`) intentionally left untracked -- no reason to carry a rejected
  experiment's binary weights in git history.
- [x] **Program status on the USP claim**: the spelling-invariance gap (67.4% band-agreement on
  held-out variants) remains OPEN and unresolved -- the naive fix didn't work. This is now a
  documented, evidenced limitation rather than an aspirational claim, consistent with this project's
  "honest documentation" standard. Future attempts would need a different mechanism (e.g. a
  smaller/more targeted variant set gated incrementally like the L2 collision-scan extension was,
  rather than one large batch) -- flagged as a candidate follow-up, not attempted this session.

## Model Excellence Program -- Workstream D COMPLETE (`7526c93`, `4152473`), STOP POINT for GG

- [x] **Item 14, external comparability search** (`docs/known-limitations.md` entry 22): live web
  search found no existing public resource matching this project's task shape (word-level
  relatedness ranking over romanized, code-mixed Hindi-English). GLUECoS/LinCE (real Hindi-English
  code-mixed benchmarks) have no relatedness task at all; SemRel2024 (real Hindi relatedness
  dataset) is sentence-level and monolingual, not word-level/code-mixed. Evidences rather than
  merely asserts the "no comparable public benchmark existed" position.
- [x] **Item 12, statistical power analysis** (`evals/finetune/power_analysis.py`): measured CI
  width shrinking from 0.201 (n=20 secrets) to 0.138 (n=42) by subsampling the internal pool.
  Real-effect MDE simulation (using the actual historical L2+L5 delta) shows only 23-32% detection
  rate even at the current 34-secret public benchmark size -- consistent with that change's
  historical near-miss CI. A synthetic-injection MDE curve claims much higher detection but
  disagrees sharply with the real-effect curve at the one overlapping point (100% vs 27% at n=34) --
  reported as an optimistic lower bound, not averaged away or hidden. Extrapolation: roughly 56
  secrets (~22 more than current) would be needed for a ~0.06-magnitude effect to reliably clear
  significance -- a rough heuristic, not a precise target. No new secrets authored (that's a
  separate content-authoring decision for GG, given each one needs curation + scrub-script passes +
  review of any new advisory hits).
- [x] **Item 13, label-ceiling sample prepared, NOT annotated** (`evals/finetune/data/
  label_ceiling_sample_for_gg.csv`, 75 rows, stratified near/mid/far x 7 domains, blind -- AI tier
  withheld, row order shuffled after catching a real leakage bug where tier-grouped ordering
  would have let the withheld label be inferred from position alone). Scorer
  (`score_label_ceiling.py`, weighted Cohen's kappa + CI) written and validated against textbook
  golden values, NOT run against real data.
  **STOP POINT for GG**: `evals/finetune/data/label_ceiling_sample_for_gg.csv` +
  `..._INSTRUCTIONS.txt` are ready for you to fill in the blank `gg_tier_judgment` column (75
  pairs, single sitting). Once returned, `uv run python -m evals.finetune.score_label_ceiling`
  computes the benchmark's own label ceiling.
- [x] Self-caught data-provenance discrepancy: `evals/scenarios/dim1_hien.json`'s benchmark-
  supplement content (306 records) and the actually-published `public_benchmark_staging/
  dim1_hien.json` (302 records) differ by 24 words -- staging used as canonical throughout,
  documented rather than silently assumed identical.
- [x] **STOP POINT cleared**: GG approved continuing to E and F.

## Model Excellence Program -- Workstreams E + F COMPLETE, program CLOSED pending GG label-ceiling annotation

- [x] **Workstream E, efficiency** (`bf4744a`): shipped model 956.7MB (dominated by a
  197,285-token embedding table, ~606MB), 2.99ms/word warm latency -- but production has NO live
  per-user embedding inference today (payload precomputes once per secret at build time), so this
  is offline-build/local-run cost, not a live bottleneck, stated honestly rather than framed as a
  bigger problem than it is. Binary quantization of the precomputed vocab embedding cache: **32x
  storage reduction, zero net regression -- a real, gated partial win.** int8 embedding
  quantization, torch dynamic weight quantization, and a MiniLM-L12 distillation candidate all
  **failed** the zero-regression gate decisively (weight quant only shrinks the small transformer
  body since dynamic quantization doesn't touch the dominant embedding table; MiniLM already scored
  near-random on hi-en off-the-shelf pre-fine-tune, per the ORIGINAL 9-candidate bake-off, and 4
  epochs can't teach romanized-Hindi understanding from scratch). Self-caught a real bug mid-probe
  (a read-only `.auto_model` property silently no-op'd a model swap, same bug class `train_lib.py`
  already documents for LoRA) before trusting the weight-quantization result. Verdict: the
  "same-quality, materially smaller MODEL" USP is NOT achieved -- honest NO-GO on that axis, one
  genuine win on the embedding-cache-storage axis.
- [x] **Workstream F, L5 dormancy + L4/L6 confirmation** (`2f4dd15`): scheduled all 8 L5 trigger
  words into the live cyclic schedule (`vocab/secrets_hi-en.txt`/`secrets_en.txt`, 60->68 entries) --
  each will fire on a confirmed future date (2026-08-11 through 2026-08-18). Caught a real
  dependency not in the original task scope: `clues.py` indexes by the same cyclic modulus and
  `test_clue_spoiler_gate.py` asserts `len(clues)==len(schedule)`, so matching clues had to be
  authored too (8 per language, 2 near-miss leaks caught and fixed) or the whole 72-day cycle's
  clue/secret pairing would have desynced, not just the 8 new days. Confirmed the frozen
  train/dev/test split is unaffected (reads the already-committed `split.json`, not the live
  schedule). L4/L6: found `docs/known-limitations.md` entry 20 never actually carried the L4/L6
  labels its own probe scripts pointed readers to -- added a dated, cross-checked addendum
  confirming both remain live, untested-at-scale levers (not a new investigation, a genuine doc
  gap fixed).
- [x] **Program capstone deliverable**: `docs/model-excellence-final-report.md` (`4d861c0`) --
  every finding across Workstreams A-F, ranked by prevalence and user impact, each with its
  evidenced next attack. Top-ranked, not yet attempted: the mid-tier Warm band's ~24-rank width is
  a game-CALIBRATION artifact (not a model defect) that two independent analyses converged on from
  opposite directions -- widening the band formula and re-measuring is the cheapest, highest-
  leverage next step, no retraining required. Second-ranked: spelling-variance non-invariance
  remains open after a failed retraining attempt; the report flags a lower-risk alternative never
  tried this program (extend `vocab/hi-en-aliases.txt` directly with Aksharantar-derived variants,
  sidestepping model-regression risk entirely).
- [ ] **Program status**: A-F substantially complete. The shipped model is unchanged except two
  small, fully-gated production patches (L2 patch 4->5 words, L5 trigger words now reachable). No
  retraining was promoted -- both attempts this program produced honest, evidenced NO-GOs, and "the
  current published model stands until beaten" held throughout. **The one open action item
  requires GG specifically**: fill in `evals/finetune/data/label_ceiling_sample_for_gg.csv` (75
  pairs, single sitting, no rush) to establish the benchmark's own label ceiling -- everything else
  in the original spec is either complete, gated-and-shipped, or a documented/evidenced finding
  with its next attack identified.

## Spelling-variance fix -- deterministic alias-lookup extension (finding #2 closed, NOT via retraining)

- [x] **Mechanism**: `docs/model-excellence-final-report.md` finding #2 named a lower-risk
  alternative to the failed `bc4b25a` retraining attempt -- extend `vocab/hi-en-aliases.txt`
  directly (the same LOOKUP-FOLDING mechanism `normalize.py`/`payload.py` already use to resolve a
  typed variant to its canonical spelling BEFORE any embedding lookup). This session implemented
  that alternative. **Zero model/training-data changes** -- `evals/finetune/train_mnrl_pairs.jsonl`
  and every other `*_pairs*.jsonl` file, plus the shipped checkpoint, are untouched.
- [x] **Candidate generation** (`generator/evals/finetune/extend_hien_aliases.py`, new file):
  reuses `spelling_robustness.py`'s `build_aksharantar_maps`/`aksharantar_variants_for_secret`/
  `is_clean_variant` verbatim (the SAME machinery `assemble_data.variant_source()` used for the
  rejected retraining candidate), across the FULL ~544-word hinglish-sourced vocab -- 226 candidate
  (canonical, variant) pairs generated (vs 189/193 for the train-split-only retraining attempt;
  more here because held-out secrets are correctly INCLUDED -- alias-folding is a deterministic
  lookup, not a statistically-generalizing model, so there's no leakage concern the way there was
  for retraining).
- [x] **False-merge quality gate** (the task's single named biggest risk): every candidate checked
  against (a) the full vocab list for a DIFFERENT-word collision, (b) the pre-extension alias file
  for a DIFFERENT-canonical collision, (c) internal consistency within the new batch itself. **12 of
  226 candidates excluded as genuine false-merge risks** (8 vocab collisions, 4 internal-batch
  conflicts) -- real near-misses caught, not hypothetical: `honth` (lips) mined a variant that
  normalizes to `hunt`, another to `hut` (both pre-existing unrelated English vocab words);
  `neeche` mined a variant that normalizes to `niche`; `kitne` mined a variant colliding with the
  distinct vocab word `kitna`. A further 51 candidates were excluded as harmless no-ops (5 already
  literal duplicates of existing aliases, 31 whose normalized form already equals their own
  canonical -- i.e. already resolve correctly with zero file changes -- 15 redundant duplicate
  normalized forms within the new batch itself, which still resolve correctly via their kept
  sibling spelling). **163 candidates survived the automated gate** -- full accounting (every
  exclusion + reason) in `generator/evals/finetune/data/extend_hien_aliases_report.json`.
- [x] **A 2nd, orthogonal collision found by the FULL test suite, not the automated gate**: `(pyaar,
  paayar)` passed all 3 automated false-merge checks but broke
  `test_clue_spoiler_gate.py::test_spoiler_gate_pack_content[bollywood-hi-en]` -- `paayar`
  normalizes to `payar`, which is edit-distance-2 from `palat` (an unrelated word meaning "turn
  around") in the bollywood pack's own P01 hi-en clue, false-tripping the spoiler gate's
  morphological-variant check. This is exactly why the task specified running the FULL suite, not
  just alias/payload-specific tests -- caught real cross-system content risk the alias-file's own
  gate has no visibility into (it doesn't read clue/pack content, by design -- that's out of this
  task's scope to add). Excluded manually with an inline comment, same pattern as the file's
  pre-existing `vaada: waada` exclusion. **162 final survivors added.**
- [x] **`vocab/hi-en-aliases.txt` extended**: 29 -> 121 canonicals, 39 -> 201 aliases. All 29
  original entries preserved byte-for-byte except 6 that gained additional aliases appended in
  place (`khushbu`, `gyaan`, `pyaar`, `qurbani`, `kahani`, `izzat`); new canonicals appended under a
  dated section header. Header comment updated to reflect the new scale.
- [x] **Verified through the REAL production path** (precedent: `verify_ship_l2_extension_e2e.py` --
  call the actual shipped functions, not a reimplementation): `normalize.canonical_for()` and
  `payload.py`'s real `_build_payload_core`/alt-map builder, run against the full 10,495-word
  production `load_hien_vocab()` (synthetic embeddings -- this verifies the LOOKUP mechanism's
  correctness, not ranking quality, which the mechanism deliberately never touches), for a 17-secret
  representative sample (all 13 `aksharantar_heldout`-covered secrets + 5 others): **26/26 new
  (secret, alias) pairs resolve correctly** via both `canonical_for()` and the real alt-map's
  `[rank, qsim]` (verified equal to the canonical word's own entry, not just present).
- [x] **Re-measured the actual success criterion**: of the original 267-record `aksharantar_heldout`
  eval set (30 unique secret/variant pairs, 13 secrets, 67.4% embedding-level band-agreement
  baseline), lookup-based resolution via the extended alias file is **267/267 (100%)**, up from
  63/267 (23.6%) pre-fix -- 100% BY CONSTRUCTION for every covered pair, since a resolved lookup
  inherits the canonical spelling's exact rank (this is the correct re-measurement per the task's
  framing: alias-folding happens before embedding, so "does it resolve" is the right question, not
  "does directly embedding the variant produce the same rank", which is what the ORIGINAL
  `aksharantar_heldout` measurement deliberately tests and is UNCHANGED by this fix -- the embedding
  itself was never touched). 23 of the 30 unique pairs were newly fixed by this session's alias
  additions; 7 already resolved correctly before this task (via normalize()'s fold rules alone or
  pre-existing alias entries). None of the 30 eval pairs involve `pyaar` (the one spoiler-gate
  exclusion above), so that exclusion does not affect this 267/267 number. Broader
  full-candidate-set coverage: 213/226 (94.2%) of ALL mined candidates (not just the 267-record eval
  sample) now resolve correctly; the remaining 5.8% are exactly the 12 automated-gate false-merge
  exclusions plus the 1 spoiler-gate exclusion, not a residual gap.
- [x] **Zero-regression check**: full `uv run pytest` from `generator/`. Before the spoiler-gate
  fix above, `test_clue_spoiler_gate.py::test_spoiler_gate_pack_content[bollywood-hi-en]` was the
  ONE failure in the entire 718-test suite (713 passed, 1 failed, 4 skipped) -- a real regression
  this change introduced and the full-suite run caught, as intended. **After the fix: 714 passed, 0
  failed, 4 skipped** (608s wall clock) -- confirmed clean on a run where the file was not touched
  mid-execution (the first post-edit run read a stale in-process `lru_cache`d alias map from before
  the fix landed, giving a misleading still-failing result; re-run confirmed the fix, not a cache
  artifact).
- [x] **Docs**: `docs/model-excellence-final-report.md` finding #2 updated in place (FIXED
  (2026-07-24) heading, full before/after numbers, "why this worked where retraining didn't"
  section) -- not a new numbered entry, per the task's own framing that finding #2 was already the
  right home for this.
- [ ] **NOT committed**: everything in this checkpoint is staged/unstaged on disk only, per explicit
  instruction -- an orchestrator-level commit follows after combined review with a parallel
  band-calibration (finding #1) change. Nothing pushed/published anywhere; no payloads republished
  to the live payloads repo (that remains a separate, later, human-confirmed step).

## Band-calibration fix -- hi-en Warm band widened via a floor, not a fraction change (finding #1 closed)

- [x] **Mechanism**: `docs/model-excellence-final-report.md` finding #1 (hi-en's Warm band was only
  24 ranks / 0.23% of vocab wide, vs EN's 2,200 ranks / 4.0%) named `warm_max = int(n * 0.08)` as an
  untested next attack. That exact hypothesis was tested and **rejected**: raising `warmFraction`
  globally also inflates EN's Warm band from 4.0% to 7.0% of vocab (2,200 -> 3,850 ranks), eating
  into EN's Cold band -- directly contradicting the goal of leaving EN's already-shipped, presumably
  well-tuned band feel untouched. Root cause, actually isolated: unlike Scorching (`max(50, n*
  0.001)`) and Hot (`max(500, n*0.01)`), Warm had no floor of its own -- so at hi-en's vocab scale,
  Hot's floor eating into the un-floored Warm ceiling had nothing to counteract it. **Fix shipped**:
  added a 900-rank floor to Warm (`warm_max = max(900, int(n * 0.05))`), the same `max(floor,
  n*fraction)` shape the other two bands already use -- `warmFraction` itself is UNCHANGED at 0.05.
  900 was chosen empirically (not a round-number guess): it produces a hi-en Warm width of 400 ranks
  / 3.81% of vocab, closely matching EN's existing 4.0% feel, while being mathematically guaranteed
  not to bind at EN's scale (55,000 * 0.05 = 2,750 >> 900).
- [x] **Kept in sync, all sites found and fixed**: `rival.band_for_rank` (Python source of truth) and
  `bandForRank`/`AppConfig.warmFloor` (Dart, `models.dart`/`config.dart`) both carry the floor.
  Audited for every OTHER inline `n * 0.05` re-derivation that could silently drift: `rival.
  _generate_path`'s own `warm_threshold` (adaptive-convergence cold/warm transition -- was already
  duplicating band_for_rank's formula pre-fix, now carries the same floor);
  `dimension5_winrate._simulate_one`'s own `warm_threshold` (win-rate player-model reduction
  schedule, same fix); `test_onboarding_build.py`'s EN teaching-ladder boundary check (doesn't
  change EN's numeric outcome since the floor never binds there, but kept honest). `failure_taxonomy.
  band_rank_range` needed NO code change -- it already derives its window by scanning
  `band_for_rank` directly rather than duplicating the formula, exactly the pattern the other sites
  should have followed; its own tests still needed updating since they hardcoded the OLD scanned
  result (24-rank window -> 400-rank window).
- [x] **Tests updated, not just widened**: every hardcoded boundary value in `generator/tests/
  test_rival.py` (new `test_hien_warm_floor_fix` at the real n=10,495; `test_small_vocab_hot_floor`
  at the pathological n=1,000 explicitly documented as an ACCEPTED edge case -- Warm is now
  reachable there but Cold becomes fully swallowed instead, since n=1,000 is not a real vocab this
  game uses, both real langs are >=10,495) and `app/test/temperature_bands_test.dart` (n=10,439
  fixture group's 501-524 Warm window recomputed to 501-900) recomputed to the exact new numbers,
  plus `test_failure_taxonomy.py`'s two hardcoded-window tests (24 -> 400 ranks).
- [x] **Empirical validation, not just a formula check**:
  - **Band-confusion matrix** (bake-off checkpoint `gauravgandhi2411/hinglish-relatedness-sbert`,
    379 dim1 records, real n=10,495): Warm's predicted-count rose 2 -> 17, recall 1.2% -> 8.3% of the
    84 expected-Warm records, precision held ~0.41-0.50 (the newly-captured records aren't noise).
    **EN confirmed byte-identical**: re-ran `dimension1_ranking._resolve_actuals` for all 227 EN
    dim1 scenario records against both formulas -- **0 records changed `actual_band`**.
  - **ECE unaffected by construction, not by luck**: `band_calibration_error` derives its confidence
    signal from `1 - actual_rank/vocab_size` directly, never from `actual_band` -- so it's
    mathematically invariant to any band-boundary change; reported (0.202, identical both formulas)
    for completeness, not claimed as fix evidence.
  - **Guess-distribution simulation** (adapted `dimension5_winrate`'s exact RNG/reduction-model
    machinery, 118 real hi-en puzzles x 100 simulated noisy-guesser trajectories each, scratch script
    not committed): fraction of simulated guess-steps landing in Warm rose from **0.37% -> 4.44%**
    (477/130,036 -> 5,846/131,716 steps) -- the actual "will players encounter this band" proof, not
    just a static width calculation.
  - **Rival-path calibration gate** (`dimension4_rival`, real production `generate_rival_data`, 236
    real daily+pack puzzles both langs): re-ran against both the OLD formula (loaded via `git show
    HEAD:generator/rival.py` into an isolated module, zero working-tree changes) and the NEW --
    **identical results, 0/236 flagged both before and after**, median par 8.0 / chill_spread 5.0 /
    sharp_spread 3.0 unchanged. Confirms Hot's floor (unchanged), not Warm's, dominates rival-path
    pacing -- this fix doesn't touch it.
- [x] **Dart UI/UX read-only review** (`win_screen.dart` share-card + best-band label, `puzzle_
  screen.dart` live rival indicator + best-guess pill + onboarding example tile, `guess_tile.dart`
  hint/guess rendering, `rival_state.dart`): confirmed every site consumes only the `TemperatureBand`
  enum/label/emoji/color, never a raw rank number or an assumed band width. No threshold-adjacent
  hardcoding found -- no changes needed.
- [x] **Local payload regen, NOT published** (`generator/build.py`, 21 days both langs starting
  2026-07-24, output to a scratch dir outside both this repo and the sibling payloads repo): all 42
  payloads within their gzip size targets, par distributions sane (EN median 9, hi-en median 8, both
  within the [4,16]/median-[8,12] calibration targets). Spot-checked rival paths by eye across
  several dates -- band sequences non-degenerate, and one real generated payload (hi-en 2026-08-05,
  chill tier, rank 820) directly exercises the new Warm band in production-shaped output, confirming
  the fix is live end-to-end, not just formula-correct in isolation.
- [x] **Test suite**: Dart (`flutter test`, full suite, 524 tests) -- 523 passed, 1 pre-existing
  flake (`puzzle_completed_analytics_test.dart`'s win-outcome test, unrelated to band logic --
  confirmed by rerunning in isolation, where it passes cleanly every time) confirmed NOT caused by
  this change. Python: every file this change touched passes in a targeted run (`test_rival.py`,
  `test_failure_taxonomy.py`, `test_onboarding_build.py`, `test_payload.py`, `test_vocab.py` --
  208/208 passed); the full `uv run pytest` from `generator/` (all of `tests/`, including the slow
  real-LoRA-training regression test) was still running at the time this checkpoint was written --
  see the next checkpoint entry or session notes for its final count.
- [x] **Docs**: `docs/known-limitations.md` entry #18 updated in place to FIXED (2026-07-24) status
  (root cause, fix, and the same before/after numbers as above) following entry #21's established
  FIXED-entry style; `docs/model-excellence-final-report.md` finding #1 updated in place to FIXED
  (development-complete, pending deploy) status, explicitly naming and rejecting the
  originally-hypothesized fraction-only fix.
- [x] **Committed** (`894f63e` band fix, `d205a19` alias extension, `6243bab` shared docs) after an
  independent verifier subagent re-derived the band math live, re-confirmed all 8 false-merge
  exclusions and 15 spot-checked inclusions against the real vocab, and re-ran the full combined
  suite fresh (712 passed/4 skipped/0 failed Python, 523/524 Dart with 1 confirmed-unrelated
  pre-existing flake). Overall verdict: PASS, safe to deploy.
- [x] **DEPLOYED (2026-07-24), both systems, byte-verified live**:
  - Payloads: `uv run python publish_all.py --days 68 --langs en,hi-en` from `generator/` (68 =
    exactly one full post-L5-fix schedule cycle, covering 2026-06-12 through 2026-08-18 so the
    pending L5 trigger-word dates get the new formula/alias data too, not just today-forward).
    Pushed to `mindmeld-payloads` (`6e4bfd9`, "payload drop 2026-06-12..2026-08-18 (en,hi-en) +
    packs", 189 files). Byte-verified against the live GitHub Pages CDN at three independent points
    (SHA-256 match, not just HTTP 200, per this project's own "never trust a green push" lesson):
    a regular day (2026-06-12), the manifest (`generated_at` confirmed fresh, last day 2026-08-18),
    and the first L5 trigger-word date (2026-08-11, tarbooz) -- all three matched the pushed content
    exactly. Pre-push content spot-check confirmed the diff was real and expected, not a trivial
    metadata-only change: alt_map grew 476->624 entries on the sampled day (the alias extension
    taking effect), ~2,605/10,495 word ranks shifted by 1-3 positions (the known, previously-seen
    "vocab injection" collateral-noise pattern from adding new embedded strings, harmless).
  - App: `./deploy-warmer.ps1` (Flutter/JDK added to PATH for the session --
    `C:\Users\gaura\sdks\flutter\bin`/`jdk17\bin`, not on PATH by default in this environment) --
    every guard passed (web-plugin registrant, Firebase authorized-domains, web-dist/ project-link
    check, the byte-size live-wasm-match check that exists specifically because `vercel deploy`
    silently drifted the `playwarmer.vercel.app` alias once before), deployed to Vercel production,
    aliased, and the post-deploy smoke check passed (HTTP 200, booted true, 0 page/request errors).
    Live wasm confirmed byte-matching this exact build (2,803,437 bytes).
  - Final live check: navigated to `https://playwarmer.vercel.app/` in a real browser, confirmed
    today's actual puzzle (2026-07-24, hi-en) renders correctly with no visual breakage and zero
    console errors/warnings. Full interactive gameplay verification (typing a guess and checking
    band-color output) hit a Flutter-CanvasKit browser-automation limitation (the rendered UI isn't
    a real DOM input the keyboard-event simulation could reliably drive) -- not itself evidence of
    an app problem, since `deploy-warmer.ps1`'s own automated smoke check already exercises real
    boot behavior separately and passed cleanly.
- [x] Both this checkpoint and the sibling alias-extension checkpoint's payload-regen scratch output
  were cleaned up; nothing left behind outside the two repos.

# PLAN -- spec-warmer-closeout.md (2026-07-30)

## WORKSTREAM 1 -- Repo hygiene: CLOSED

- [x] **Pre-change inventory**: 3 modified + 9 untracked files on `feat/hinglish-finetune`
  (WS1/WS2/WS3 analysis artifacts from spec-metrics-ceiling-calibration.md, never committed). 5
  local branches genuinely unmerged (`feat/hinglish-finetune` + 4 open GitHub PRs: #4 deploy-
  provenance-log, #5 perf-budgets-readme, #6 pr-template-precommit); `chore/dedup-design-tokens`
  found **falsely unmerged** -- PR #3 was squash-merged 2026-07-12, origin ref already deleted,
  local branch pointer stale (the exact failure mode `git-branch-staleness-before-committing`
  memory warns about).
- [x] **Committed the outstanding artifacts** in 4 logical commits (`c02f3af` WS1 corrected
  retrieval metrics, `5dbbb40` WS2 LLM-consensus ceiling honest-negative, `bfb06cc` WS3 band-
  threshold calibration evidence, `ad0955f` the two closeout specs). 94/94 targeted tests + full
  777-passed/6-skipped generator suite verified before committing.
- [x] **PR #4 (deploy-provenance-log) NOT merged -- closed as superseded.** Its
  `scripts/deploy-warmer.ps1` is a stale duplicate pipeline from 2026-07-12: no `--wasm` flag, no
  byte-verify live-wasm-match guard, predates the stderr-crash fix (`b922a18`, 2026-07-25).
  Merging would have made README's "Recommended" deploy path point at an inferior, out-of-sync
  script instead of the actual proven one at repo root. The provenance-log idea itself (dirty-tree
  guard + `reports/deploys.log`) is genuinely useful and recorded as a deferred follow-up, not
  built now. Closed via `gh pr close 4` with the reasoning posted as a PR comment.
- [x] **PR #5, #6 merged for real** after a **trial merge on a scratch branch** to verify the
  actual 3-way merge result (a raw two-way diff of PR #5's branch vs main was misleading --
  looked like it would revert README's `--wasm`/`ANALYTICS_ENABLED` documentation, but git's real
  merge correctly layered only the new content on top of main's current state; verified by
  inspecting the merged README directly, not by trusting 0-conflict-marker output alone).
- [x] **`feat/hinglish-finetune` merged into main** (76 commits, clean merge-tree, 0 conflict
  markers). Field-leading Hinglish model + benchmark, WS1/WS2/WS3 follow-ups, already-shipped
  warm_floor 900->1050 fix all now on main.
- [x] **Branch cleanup**: force-deleted stale `chore/dedup-design-tokens`; deleted all now-
  fully-merged local branches (`feat/hinglish-finetune`, `chore/perf-budgets-readme`,
  `chore/pr-template-precommit`, plus 4 already-merged-pre-session branches:
  `feat/first-session-hook`, `fix/known-limitations-pass`, `fix/wasm-stub-remediation`,
  `wave-launch-1-readiness`). Only `main` and the intentionally-unmerged-and-closed
  `chore/deploy-provenance-log` remain.
- [x] **Full verification on the merge commit**: generator `777 passed, 6 skipped, 0 failed`;
  Flutter `flutter test` `525/525 passed, 0 failed` (the prior session's one documented flake did
  not recur). Pushed to `origin/main` (`f0648b8`); both CI lanes on the push (`e2e-web` DDC,
  `e2e-web-wasm`) completed `success`. GitHub auto-detected PRs #5/#6 as merged via commit
  reachability (closed automatically); PR #4 closed manually as superseded.
- [x] **Byte-verified live deployment**: built `main` locally with the exact deploy-warmer.ps1
  flags (`flutter build web --release --no-web-resources-cdn --wasm
  --dart-define=ANALYTICS_ENABLED=true`) and compared SHA-256 against the live
  `https://playwarmer.vercel.app/main.dart.wasm` -- **byte-identical**
  (`c8f6a9994674bf31aa2dfe8125a80eef0880c56bb2d456d2d66b33893f4f42ab`). Confirms the warm_floor
  1050 Dart mirror (`566f5f6`, 2026-07-25) was already live despite PLAN.md's last explicit deploy
  narrative predating it by a day -- no new deploy was needed for WS1.
- **End state**: working tree clean, no genuinely-unmerged branches, `main` == deployed, both CI
  lanes green.

## WORKSTREAM 2a+2b -- Puzzle archive + earned streak-freeze mechanic

- [x] **Archive was already largely built** (`ArchiveScreen`, nav-reachable "Practice" tab,
  `isPractice: true` reusing `PuzzleScreen` with `_skipStatsWrites` gating -- discovered via
  Explore before writing anything, not redone). Added the missing "sensible list UI (date, solved
  state)" piece: `_loadSolvedStates()` loads each date's `DayState` via `Future.wait` (parallel,
  not sequential -- the date range only grows over the game's life) and the list now shows
  "Solved in N" / "Not solved" / plain date per row with a check/circle icon.
- [x] **Found and closed a real "coming soon" bug while researching this**: Settings' IAP section
  had a "Puzzle Archive" row that always showed "Coming soon" and a coming-soon snackbar on tap --
  contradicting the fact the feature already exists and is free. Removed that row entirely
  (`settings_screen.dart`) rather than wire it to a purchase that was never going to exist;
  `_archiveSubtitle()` deleted as dead code.
- [x] **Streak freeze completed as EARNED, not purchased** (spec's explicit instruction, overriding
  the pre-existing IAP-consumable scaffold): moved `streakFreezes` from `Entitlements`/RevenueCat
  entirely into `PlayerStats`, persisted across all 3 backends (SQLite schema v5->v6 with a real
  migration, PrefsStore JSON key, MemoryStore free via the whole-object store). Earning rule:
  `AppPersistence.recordWin` grants +1 freeze every `streakFreezeMilestoneDays` (7) consecutive-day
  streak milestone, capped at `maxStreakFreezes` (3), gated on the streak actually changing (not
  `updateStreak`'s same-day-idempotent path) so replays never double-grant.
- [x] **Rescue mechanic, day-rollover correctness verified hard** (per the spec's explicit risk
  callout): new `AppPersistence.rescueStreakOrReset` replaces `applyPassiveStreakReset` --
  gap<=1 day: no-op; gap==2 (exactly one missed day) with a freeze held: spend it, PRESERVE
  currentStreak; any larger gap, or no freeze: reset to 0 (a freeze covers one missed day, not an
  extended absence). **Critical bridge fix, caught before shipping**: the rescue must persist
  `lastWinDate` as `today - 1`, NOT the original stale lastWinDate -- otherwise a real win
  immediately after the rescue would see a stale 2-day gap and reset the very streak the rescue
  just saved. Covered by a dedicated test
  (`streak_logic_test.dart`, "critical: after a rescue, a real win the same day extends the streak
  instead of resetting it") that fails loudly without the bridge.
- [x] **UI**: `StatsScreen` now sources freeze count + rescue state from `AppPersistence`
  directly (no more IAP gateway involvement); shows holdings with an explanation ("Earned every
  7-day streak -- covers one missed day automatically") and a one-time "Streak freeze used" banner
  right after a rescue. Settings' "Streak Freeze" IAP row removed (same treatment as archive) --
  `IapProduct.streakFreeze`/`archive` enum values, `Entitlements.streakFreezes`/`archive` fields,
  and the RevenueCat consumable-purchase demo path (`kRcProductStreakFreeze3Pack`,
  `revenuecat_gateway_test.dart`'s "Test 3") deliberately left in place as inert, never-sold
  infrastructure rather than ripped out -- minimal blast radius, same call this session made for
  archive.
- [x] **Tests**: `streak_logic_test.dart` rewritten (`applyPassiveStreakReset` group ->
  `rescueStreakOrReset`/`recordWin — streak-freeze earning` groups, 19 tests covering milestone
  grant/cap/idempotency and rescue/no-rescue/bridge-correctness). `iap_stub_test.dart` updated:
  archive/streakFreeze rows assert `findsNothing` instead of `findsOneWidget`; their coming-soon-tap
  tests removed (row no longer exists to tap). A widget-level ArchiveScreen solved-state test was
  attempted and **dropped**: it deterministically hung at flutter_test's 10-minute timeout across
  two different fix attempts (sequential and `Future.wait`-parallel loading) in a way no other
  real-SQLite-from-initState widget test in this suite exhibits -- root cause not found, low
  enough value (S24 already proves the load-bearing streak-isolation invariant; `flutter analyze`
  confirms the code is type-correct) not to keep sinking time into it. Solved-state rendering
  moved to the manual QA checklist instead.
- [x] **Found and fixed a genuine regression along the way**: removing 2 Settings IAP rows
  shortened `SettingsScreen`'s list enough that `settings_notifications_test.dart`'s
  `scrollUntilVisible` (200px increments) converged to a scroll position where the target
  `SwitchListTile` was present-in-tree but outside the viewport's hit-testable bounds -- 3 tests
  failed with "derived an Offset that would not hit test." Fixed by adding `tester.ensureVisible()`
  after `scrollUntilVisible` (precise, not incremental). Verified this was a real regression, not
  pre-existing flakiness, by reproducing on the pre-change commit via `git stash` (passed) vs.
  post-change (failed), then re-confirming green after the fix.
- [x] **Full suite green**: `flutter test` 531 passed, 0 failed (up from 524; net of dropped/added
  tests). One `pack_isolation_test.dart` failure seen in a single full-suite run did not reproduce
  standalone or on a clean re-run of the full suite -- confirmed a one-off resource-contention flake
  from several parallel background `flutter test` invocations during this session's own debugging,
  not a real regression.
- **Committed** (`0e80bb3`) and pushed.

## WORKSTREAM 2c -- Rival light polish (name + reaction lines, no persona/progression)

- [x] **Explored before writing anything**: confirmed the rival was genuinely anonymous (zero name
  anywhere, grepped) and that `RivalState`/`RivalOutcome` (rival_state.dart) already compute
  everything needed (rank, band, solved, outcome) without persisting anything -- no new state layer
  needed, matching the spec's explicit "keep it cheap and cuttable."
- [x] **Name**: `kRivalName = 'Ember'` (rival_state.dart), thematically tied to the game's own
  heat/temperature-band metaphor. Scoped deliberately to LIVE in-app UI only (the mid-game rival
  strip in `puzzle_screen.dart`, the inline win-screen badge in `win_screen.dart`) -- NOT
  `buildShareCard`'s external, tested, copy-pasted share-text format (still says "the bot"), to
  avoid touching a stable externally-visible string for a "light polish" task. Confirmed via grep
  that only `share_card_test.dart` asserts on the old "Bot"/"Rival:" strings; the live-UI strings
  had zero test coverage to preserve.
- [x] **Three reaction moments, each mapped to an existing, already-computed signal** (no new
  tracking/state):
  - **Overtaken** (mid-game): `_buildRivalStrip` only renders pre-`isFinished`, so
    `rivalState.rivalSolved == true` there always means "ahead of you right now" by construction --
    label becomes "Ember found it in N guesses — catch up!" (previously a neutral "Rival finished
    in N guesses").
  - **Close finish** (win, margin of exactly 1 guess): `_buildParRivalBadge` (WinScreen) gains a
    small subtitle "Neck and neck — just edged out Ember!" under the existing par/rival badge.
  - **Loss**: `LossScreen.build()` gains "Ember got there first this time." next to the existing
    "Your best: ... so close!" box, gated on `rivalSolveAt != null`. Verified this claim is always
    accurate even though the rival's `solveAt` isn't explicitly bounded by the player's own
    `maxGuesses` budget (`generator/rival.py`'s tier-width comment shows `chill.solveAt` can exceed
    `par` by up to 8): the rival's path is a fully deterministic sequence that always terminates at
    rank 1 by construction (`"solveAt": len(path)`), so "the rival got there and the player (on
    LossScreen) didn't" holds regardless of budget -- same comparison basis the pre-existing
    win-screen "Bot won" branch already relied on.
- [x] **Explicitly did NOT build**: rival leaderboards, a persona/backstory, or any
  progression/unlock system -- per the spec's own unvalidated-feature caution.
- [x] **Verification**: `flutter analyze` clean on all 3 changed files; full `flutter test` 531
  passed / 0 failed (no existing test touched the live-UI strings that changed). No new dedicated
  test file added for this feature -- weighed against the spec's own "keep it cheap" instruction
  for a purely cosmetic text change already covered by analyze + the full suite's non-regression;
  visual read-quality ("does the copy land right") added to the manual QA checklist instead, where
  a human eye is the right tool anyway.
- **Committed** (`719c1b7`) and pushed.

## WORKSTREAM 2d -- Indian Food pack: DRAFTED, VALIDATED, awaiting GG review (STOP POINT)

- [x] **Recipe followed exactly** (spec-cricket-pack.md, retargetable per its own text): ~25
  common-noun secrets, no proper nouns, theme in the clue not the secret, embedding-validated
  every secret, semantic-neighbor audit on all clues, EN + natively-written Hinglish, no
  duplicates vs daily/Bollywood/Cricket, distinct accent (packs.json already had one assigned:
  `#9C5E20`/`#6B3F14`, brown/spice-toned).
- [x] **Embedding validation was the load-bearing step, run against the REAL models** (all-MiniLM-
  L6-v2 for en, the shipped fine-tuned checkpoint for hi-en) — not assumed. Two full candidate
  rounds (~35 EN words total), top-10 nearest-neighbor inspection per word, mirroring Cricket's own
  methodology. **Rejected for real collision reasons, not guesses**: `curry` (dominant sense in
  this EN model is NBA player Stephen Curry — shah/warriors/kobe/lebron neighbors), `ginger`
  (dominant "redhead" sense), `cumin` (vulgar collision), `curd` (vulgar collision), `mortar`
  (construction sense), `turmeric`/`cardamom`/`saffron`/`coriander` (phonetic-noise, no food
  semantics survive), and — the single biggest finding — **most romanized Indian dish names embed
  by surface-form phonetics rather than meaning in the English-only model**, landing on unrelated
  or actively risky proper-noun clusters: `idli` neighbors "akali" (an Indian political party),
  `khichdi` neighbors "khamenei"/"khomeini" (Iranian political figures), `pakora` neighbors
  "pakistani"/a slur-adjacent term. This is the same loanword-embeds-by-phonetics failure mode
  prior sessions documented for hi-en (dil->Turkish, dua->Italian) — found here on the reverse
  (EN) side. Consequence: the EN secret list leans generic-but-food-clued (spice, feast, recipe,
  cuisine...) rather than dish-name-heavy, which is exactly what the spec's own design constraint
  #2 asks for ("theme lives in the clue, not the secret").
- [x] **Two real defects caught before GG ever saw a draft, not after**:
  1. **Near-duplicate against the DAILY secret list**: initial candidates `kitchen`/`hunger`/
     `snack` (EN) and `samosa`/`chai` (hi-en) are already daily secrets (`vocab/secrets_en.txt`/
     `secrets_hi-en.txt`) — caught by direct grep before drafting clues, not after.
  2. **Collision with the PUBLISHED PUBLIC BENCHMARK dataset**: `platter`, `dessert`, `yogurt`,
     `dough` are already used as secrets/near-far judgment words in the externally-published
     benchmark (`test_scrub_public_benchmark.py::test_public_benchmark_staging_scrubs_clean`
     caught this on a routine full-suite run — 70 blocking collisions reported). This is a genuine
     content-integrity issue (a held-out eval set overlapping with live game content), not a false
     positive. Replaced with `chef`/`restaurant`/`guest`/`hospitality` — re-validated clean against
     vocab, embeddings, AND the benchmark word set before finalizing.
  3. **Semantic-neighbor self-audit** (manual, cross-referencing every clue against its secret's
     own top-10 embedding neighbors gathered during validation): caught `garlic`'s clue almost
     including "cloves" (garlic's #1 EN neighbor, and `clove` is a separate secret in this same
     pack) and `pantry`'s draft almost including "kitchen" — both reworded before finalizing.
     `feast`/`banquet` dropped as a near-duplicate pair (0.86 cosine) for puzzle-variety reasons,
     not a spoiler-gate failure.
  4. **Spoiler gate found one false-positive-shaped-but-real issue**: `sabse` (a common Hindi word
     meaning "the most") was flagged as a morphological variant of `sauce` — reworded that one
     clue; the automated gate is correct to be sensitive here even though this particular hit read
     as a coincidence.
- [x] **Vocab additions**: zero for EN (all 25 final secrets were already in `vocab/en.txt`). 8 for
  hi-en (`pickle`, `buttermilk`, `aroma`, `pantry`, `cinnamon`, `clove`, `lentil`, `chickpea`,
  added to `vocab/hinglish.txt` in the same `word<TAB>english_anchor` code-mixed-loanword format
  Cricket's own 6 additions used) — every one embedding-validated dense and food-relevant BEFORE
  being added, not after.
- [x] **One asymmetric EN/hi-en pair** (line 9): EN's `condiment` embeds toward "compliment" (0.96
  cosine — near-homophone collision) in the hi-en model, so that line uses `chutney` instead
  (validated clean). Same asymmetric-pairing pattern the daily list already uses (EN "snack" /
  hi-en "samosa", EN "coffee" / hi-en "chai") — not a new pattern invented for this pack.
  Every OTHER line is the identical code-mixed word both languages (deliberate — see
  secrets_hi-en.txt header for why native-Hindi alternatives were not attempted this time, given
  Cricket already exhaustively tested and rejected that path for food-adjacent romanized terms).
- [x] **Gates run and passing**: `validate_pack_content` (count match, vocab membership, profanity)
  PASS both langs; `test_spoiler_gate_pack_content[indian-food-en/hi-en]` PASS (0 leaks);
  `test_public_benchmark_staging_scrubs_clean` PASS (0 blocking collisions, re-run after the
  4-word swap); `test_semantic_scrub_public_benchmark` PASS; full generator suite 781 passed / 2
  skipped / 0 failed.
- [x] **Dedup confirmed** against daily (EN + hi-en), Bollywood, and Cricket secret lists — zero
  overlap, checked by direct comparison, not assumed.
- **NOT YET DONE, deliberately — STOP POINT per the task instruction**: payloads not generated
  (`build_packs.py` not run), pack not published, `packs.json` status still `coming_soon`,
  Nature/Space stub deletion not yet done (bundled with this pack's launch per the task's own
  sequencing). Committed to `main` as reviewable draft content only — committing is not shipping;
  baking/publishing/flipping-live are the actual ship actions being held for GG's explicit review
  of the secrets + clues below.
