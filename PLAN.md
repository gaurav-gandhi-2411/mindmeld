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
