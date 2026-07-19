# Known Limitations — Warmer

Supersedes `docs/accepted-risks.md` (folded in below, entries 1–8; the `.gitignore`
hardening item from that ledger shipped and is dropped here — it's resolved, not a
limitation). Written as part of the 2026-07-12 known-limitations pass. Each entry
states what it is, why it's accepted as-is, what fixing it would actually require,
and the condition under which we'd revisit. These are conscious trade-offs with
stated reasoning, not blind spots — see PLAN.md for the session-by-session history
behind each one.

## Product / gameplay

### 1. Hinglish semantic ranking quality — SHIPPED fine-tune, near EN parity (2026-07-18)

**Current state** (`generator/evals/reports/baseline_report.md`, regenerated after the
v3 fine-tune shipped): hi-en Spearman correlation **0.800** vs EN **0.837** — up from
0.639 at the last off-the-shelf baseline, and from the original broken starting point
of -0.003. hi-en band-accuracy 73.1% vs EN 74.9%; near-tier split translation 100%
(n=20, was 85.0%) / associate 86.7% (n=30, was 56.7%); dim2 cross-language pass rate
**78.0%** (was 54.2%). The 5 previously-worst-diverging pairs (titli, khamoshi, rasoi,
samunder, bachpan) are no longer in the top-10 divergent list at all except khamoshi
(now 8.4th percentile, was 78.8th) and rasoi (now 1.7th percentile, was 61.1th) — both
now solidly in-band rather than near the bottom of the vocab.

Note on this number vs the fine-tune's own reported result: 0.800 is the FULL
25-secret production scenario set, which — unlike every prior off-the-shelf baseline —
now includes secrets the model was directly fine-tuned on (33 train + 11 dev of the
60-secret schedule), so it is not a fair apples-to-apples generalization number against
the old 0.639 off-the-shelf figure. The honest, held-out generalization claim is
**0.4350 -> 0.7044** (paired-CI-significant, [+0.130,+0.412]) — see below and
`ship_decision_report_v3.md`. Both numbers are real; they answer different questions
("how good is production today" vs "does this generalize to secrets never trained on").

**Why accepted:** every off-the-shelf multilingual/code-mixed embedding model tested
(9 candidates) underperforms EN parity on romanized Hindi. Closing the gap needs a
Warmer-specific fine-tune on Hinglish similarity pairs — a real ML project (data
collection, fine-tuning, eval-gated bake-off against the current champion), not a
config change or a bug fix.

**Fine-tune attempted 2026-07-17 (v1), did not ship** (`reports/spec-hinglish-finetune.md`,
`generator/evals/finetune/data/ship_decision_report.md`): SBERT contrastive fine-tune of
`l3cube-pune/indic-sentence-bert-nli` on 543 MNRL / 705 graded Hinglish pairs (dim1
triplets, local-LLM-augmented triplets, cross-lingual pairs, alias variants — frozen
train/dev/test split, held-out secrets never trained on, verified by assertion). Result:
held-out TEST Spearman **regressed** (0.435 -> 0.376 on the restricted 8-secret test
subset) and broke 5 previously-correct dim1 pairs while fixing 3 — a net regression,
failing the "zero net regression" ship gate. Dev-set metrics improved substantially
(0.781 -> 0.838) without matching test improvement — the classic small-data-fine-tune
overfitting signature the spec's risk section explicitly anticipated. One genuine partial
win: 2 of the 5 residual-weak pairs below (`rasoi`, `bachpan`) fixed on the held-out
residual-pair check — but this didn't clear the other gates, so v1 was **not shipped**.
Hypothesized root cause: insufficient training-data volume (543/705 pairs is small
relative to a ~110M-parameter BERT-base model).

**Retry attempted 2026-07-18 (v2) with expanded real/corpus data, did not ship, and
regressed FURTHER than v1** (`spec-hinglish-data-expansion.md`,
`generator/evals/finetune/data/ship_decision_report_v2.md`): a licensing-gated search
across 5 candidate real-data sources (Hindi WordSim-353, Multi-SimLex Hindi, Hindi
WordNet/IndoWordNet, IndicCorp, HingCorpus, Aksharantar) found that 3 were unusable
(WordSim-353/Multi-SimLex Hindi don't verifiably exist for Hindi; IndoWordNet's data is
license-gated to research use) and 2 were non-commercial (IndicCorp v1, HingCorpus).
Only IndicCorp v2 (CC0) and Aksharantar (CC-BY/CC0) were commercial-clean. Mined 2,718
candidate relatedness pairs from real IndicCorp v2 Hindi corpus co-occurrence (PMI),
quality-filtered via an isolated LLM judge (`pmi_quality_filter.py`, same pattern as
`homograph_audit.py`) down to 326 (later 325 after dropping one platform-context-noise
pair, `gaana`/`views`) trustworthy pairs — expanding the training set to 756 MNRL / 1028
graded pairs (+39%/+46% over v1). Same frozen split, same method/hyperparameters as v1
(held constant deliberately, so the delta is attributable to data alone). Result:
**held-out TEST Spearman regressed further, to 0.324** (worse than v1's 0.376); dim1_test
net regression -3 (worse than v1's -2); dim2_test net regression -2 with 0 pairs fixed
(worse than v1's net 0 with 2 fixed); residual-weak dim2 pass-rate dropped to 0/5 (worse
than v1's 2/5 — v1 had actually pushed `rasoi` and `bachpan` into the Hot band, v2 does
not). **More training data made every held-out metric worse, not better — this falsifies
the v1 hypothesis that data volume was the bottleneck.** Off-the-shelf
`l3cube-pune/indic-sentence-bert-nli` remains in production, unchanged. Plausible
(unconfirmed — no ablation run) mechanisms: the new PMI-mined source is a noisier
co-occurrence-based signal than curated/judged pairs and may dilute a small clean signal;
dev Spearman kept climbing every epoch with no early-stop trigger (0.780 -> 0.816), the
same dev/test decoupling overfitting signature as v1, now steeper. The commercial-data
well is now genuinely exhausted at reasonable engineering effort — the honest ceiling is
that real-data-at-scale, gated to what's actually available and licensable, still doesn't
clear the bar with this method. Both recipes are fully reproducible (seed 42, committed
data, checkpoints gitignored).

**v3 diagnostic sweep 2026-07-18 — SHIPPED** (`spec-hinglish-diagnostic-sweep.md`,
`generator/evals/finetune/data/ship_decision_report_v3.md`): v1/v2 both varied data
while holding the training METHOD fixed (full-parameter fine-tune); this session held
data at v2's set and swept the METHOD instead — confirming the OPTIMIZATION axis
flagged above as v2's most-promising untested lever actually WAS the fault. 13
capacity-control configs (full-finetune LR sweep, frozen layers, LoRA r=8/16/32,
head-only): every full/frozen config stayed within noise of baseline; every LoRA
config beat it, three CI-significantly (paired bootstrap vs the correct held-out
baseline — 0.639 was never a held-out number, only 0.4350 is; see report). Winner
(LoRA r=8, lr=2e-4, 4 epochs) plus mined hard negatives: held-out dim1_test Spearman
**0.4350 -> 0.7044** (paired-CI [+0.130,+0.412]), dim2_test pass-rate **0.375 ->
0.8125** (paired-CI [+0.188,+0.688]), regression floor net +7 on both dimensions
(dim2 strictly zero-broken), residual-weakest pairs (titli/khamoshi/rasoi/samunder/
bachpan) dim2 pass-rate **0.0 -> 0.8** (beats v1's best partial result 2x over).
Learning curve at 25/50/100% data is monotonically rising — once capacity is
controlled, more data helps, confirming both v1/v2's "not a data problem" finding
AND this session's "it was a method problem" finding were each partially right.

**Shipped 2026-07-18**: checkpoint published publicly to
[`gauravgandhi2411/hinglish-relatedness-sbert`](https://huggingface.co/gauravgandhi2411/hinglish-relatedness-sbert)
(CC-BY-4.0, full attribution + honest limitations in the model card; auto-generated
training-sample leak scrubbed before publish — see model card / `publish_to_hf.py`),
loaded with zero runtime auth since it's public. `config.MODELS["hi-en"]` flipped;
`baseline_report.md` regenerated (full-set hi-en Spearman 0.639 -> **0.800**, EN is
0.837 — see top of this entry); all hi-en daily + Bollywood + Cricket pack payloads
regenerated and deployed to the payloads GitHub Pages site, byte-verified (all 111
`.gz` files confirmed byte-identical between the git commit and the live served
content). Live spot-check results below.

**Revisit if:** the live spot-check below surfaces a live/metric mismatch (would
need investigation, not a revert by default given the scriptable-gate strength); or
Hinglish becomes a primary (not secondary) language for the player base; or real
player-guess data accumulates post-launch (still a genuine secondary lever per the
v3 learning curve, even after the method fix).

### 2. LLM-judge solvability score is not gate-worthy; spoiler-safety is

Dimension 3 of the eval harness (local Ollama `qwen3:8b` judge) calibrates at
**96.9%** agreement for spoiler-safety detection vs only **62.5%** for solvability
(`generator/evals/harness/dimension3_judge.py`, `test_harness_judge.py`;
`generator/evals/reports/baseline_report.md`, this commit — LLM-judge calibration
has run-to-run variance, e.g. an earlier run measured 65.6%/71.8% on the same
golden set; both runs land well above/below their respective gates, so the
conclusion is unchanged). The raw "~72% of clues score below the solvability gate"
headline number is **not** a real solvability crisis — manual spot-check of the
lowest-scored real clues found all of them legitimate, evocative,
previously-human-approved clues (e.g. `music`: "It reaches places in your mind
that words alone cannot"). The judge's confirmed failure mode is under-rating
deliberately indirect clues, which is this game's house style by design.

**Why accepted:** spoiler-safety is gated in CI (`spoiler_agreement >= 0.85`);
solvability is only soft-gated (`>= 0.55`) and never used as a hard per-clue reject,
specifically because of this calibration gap.

**Revisit if:** a future prompt-engineering pass or judge-model swap closes the
solvability calibration gap enough to trust an absolute per-clue threshold (would
need re-calibration against the same 32-case golden set, or a relative/comparative
solvability check instead of an absolute score).

### 3. Themed packs are online-only (no offline bundling)

Pack payloads (`packs/{packId}/{lang}/{NNN}.json.gz`) are fetched from the CDN at
play time; only the daily puzzle has a bundled offline fallback
(`app/assets/payloads/{en,hi-en}/`).

**Why accepted:** bundling all packs (currently Bollywood + Cricket live, 2 more
stubbed) would grow the web bundle for a feature most sessions don't touch on their
first visit. Keeps the initial web payload lean.

**Revisit if:** offline/airplane-mode play becomes a stated product requirement, or
pack catalog growth makes the CDN round-trip a measured friction point (no such
signal today — no offline-access complaints logged).

### 4. iOS web push requires an installed PWA

Web push notifications only work on iOS Safari once the user has added the app to
their home screen (`firebase_messaging`'s web path). This is an Apple platform
constraint (Safari does not support the Push API for ordinary browser tabs), not a
Warmer-specific gap.

**Why accepted:** no workaround exists short of a native iOS app (App Store
distribution, APNs integration) — out of scope for a solo web-first launch.

**Revisit if:** a native iOS build is ever pursued (see item 9 below — the Android
side has its own pre-release gaps too).

## Security / trust

### 5. Self-reported leaderboard scores (client trust)

`groups/{groupId}/days/{date}/results/{uid}` documents (`outcome`, `guessesUsed`,
`par`, `scoreVsPar`) are written directly by the client with no server-side
recomputation. Firestore rules bound the values to sane ranges (1–200 guesses, ±200
score) and enforce create-only (no revising a score after seeing the leaderboard),
but a technically determined player could still report a fabricated win for
themselves.

**Why accepted:** the trust boundary is a friend group, not strangers — the
"victim" of a faked score is the cheater's own friends, who can already see it's
implausible. Closing this requires a Cloud Function to validate/write results
server-side (verifying the guess sequence against the day's real payload) — real
infrastructure work (and a Blaze-plan cost) with no scoped ticket yet.

**Revisit if:** groups stop being friend-only (e.g. public/global leaderboards
ship), or abuse reports actually surface.

### 6. Soft payload anti-cheat (extractable secret)

The daily/pack secret is embedded in the payload as a hash-keyed, XOR-obfuscated
field (`s`) — enough to stop a casual "view source" spoiler, not enough to stop a
determined user with a debugger from deriving the secret before playing.

**Why accepted:** this is a casual single-player-against-a-model word game, not a
competitive integrity-critical system. The "cost" of cheating is spoiling your own
puzzle for yourself; no stakes large enough to justify real DRM-grade obfuscation.

**Revisit if:** the game ever ships a stakes-bearing competitive mode (money, ranked
ladders).

### 7. `npm audit` — 5 moderate transitive findings, deferred

`firebase-tests/` (dev/test tooling, not shipped code) has 5 moderate-severity
transitive advisories via `firebase-tools` → `@google-cloud/pubsub`/`gaxios`
(GHSA-8988-4f7v-96qf, GHSA-w5hq-g745-h8pq).

**Why accepted:** the only available fix (`npm audit fix --force`) downgrades
`firebase-tools` from `^15.22.4` to `14.23.0` — a regression, not a forward patch.
Below the critical/high bar; this package never runs against production traffic
(local emulator + puppeteer only).

**Revisit if:** `firebase-tools` ships a patch release that clears these without a
downgrade.

### 8. `pip-audit` — torch CVE-2025-3000, no fix available, deferred

`torch` (a `sentence-transformers` dependency in `generator/`) has
GHSA-rrmf-rvhw-rf47 (memory corruption via `torch.jit.script` on
attacker-controlled input). GitHub's own severity rating is LOW; OSV lists no fixed
version.

**Why accepted:** the generator only calls `sentence-transformers` to embed a fixed,
curated internal vocabulary — it never calls `torch.jit.script` on
untrusted/attacker-controlled input. The vulnerable code path isn't reachable.

**Revisit if:** a fixed torch release ships, or the generator ever scripts a model
against user-supplied text.

### 9. Flutter Firebase SDK family — one major version behind

`firebase_core`/`firebase_auth`/`cloud_firestore`/`firebase_analytics`/
`firebase_crashlytics`/`firebase_messaging` are all one major version behind current
stable. No specific CVE evidence for the pinned versions — routine JS-SDK
modularization churn, not an unpatched exploit.

**Why accepted:** all six packages must move as a coordinated set (shared
underlying Firebase JS SDK generation) — a live-tested major bump is a dedicated
regression-testing task, not a drive-by dependency patch.

**Revisit:** schedule a coordinated major-version bump + full regression pass as its
own tracked work, not blocking launch.

### 10. Homoglyph/Unicode normalization — best-effort, not exhaustive

`app/lib/social/name_sanitizer.dart` strips control/zero-width/bidi-override
characters unconditionally and folds a small hand-written Cyrillic/Greek→Latin
confusables map before blocklist matching. It does **not** implement full Unicode
NFC/NFKC normalization or the complete TR39 confusables table.

**Why accepted:** no unicode-normalization package was already a dependency, and
pulling one in for exhaustive confusables coverage is disproportionate to the
realistic threat (impersonating a handful of reserved words) vs. the risk of a
legitimate non-Latin-script display name getting mangled by an over-aggressive
normalizer.

**Revisit if:** real abuse reports show homoglyph evasion beyond the reserved-word
impersonation case already covered.

### 11. App Check — monitor mode, not enforced

`firebase_app_check` is wired into both Firebase init call sites (web-only,
`ReCaptchaV3Provider`) but every product (Firestore etc.) is left on default
"Unenforced / Metrics only". A reCAPTCHA v3 site key still needs to be created and
registered — **manual action needed from GG**: create a site key at
https://www.google.com/recaptcha/admin for `playwarmer.vercel.app` +
`playmindmeld.vercel.app` + `localhost`, register it (and its secret) in Firebase
Console → App Check, then pass it at build time via
`--dart-define=APP_CHECK_RECAPTCHA_SITE_KEY`.

**Why accepted:** flipping enforcement on before real traffic has validated the
integration risks locking out legitimate players on a misconfiguration. Metrics-only
mode is the standard safe rollout path.

**Revisit:** once the site key is registered and metrics-only mode has run against
real traffic long enough to confirm no false-positive blocks, flip Firestore (and
any other App Check-guarded product) to Enforced.

### 11a. Unbounded group/code document creation by a scripted client

Found during the launch-1 wave's STRIDE pass (`docs/stride-launch-1.md`): a scripted
anonymous-auth client can mint unlimited `groups/{groupId}` + `codes/{code}` documents
(one fresh `signInAnonymously()` per iteration) — `firestore.rules` has no per-uid cap on
group/code creation.

**Why accepted:** impact is Firestore storage/cost growth and junk-group clutter, not a
confidentiality or integrity breach — group documents carry no sensitive/puzzle content,
and cross-group data leakage is already prevented (see entry 11's default-deny + the
membership-gated `list` rules). No evidence of active abuse.

**Revisit if:** App Check enforcement (entry 11, pending the reCAPTCHA site-key
registration) doesn't sufficiently curb this once flipped from monitor to enforced, or
real abuse/cost-spike evidence surfaces — a Cloud Function-based per-uid creation
throttle would be the fix, real infra work not scoped here.

### 12. Data-deletion result-doc cleanup needs a one-time Firestore index

`SocialService.deleteMyData()`'s collection-group query over `results.uid` requires
a one-time Firestore console composite index on first production use. Until it
exists, this specific step fails (caught/logged; the rest of the deletion —
profile doc, group membership, local cache — still completes).

**Why accepted, not a code fix:** Firestore collection-group indexes are a
console/infra step, not something a rules/client change can provision.

**Action needed (GG, manual):** create the index the first time `deleteMyData()`
triggers the "index required" error — the error message includes a direct console
link to create the exact index needed.

### 13. Privacy policy contact address — still a placeholder

`docs/privacy-policy.md` still has `PLACEHOLDER_EMAIL` in the contact/deletion
sections.

**Action needed (GG, before public launch):** replace with a real, monitored
contact address.

## Performance

### 14. Flutter-web cold-boot latency, and analytics' real perf cost (updated launch-1 wave)

Original baseline (`reports/performance-baseline-2026-07-12.md`, pre-wave):
LCP 2864ms, TBT 221ms, total weight 2,838 KB, score 0.69. Launch-1 wave adopted
`--wasm` (see `reports/renderer-decision-2026-07-12.md`) and enabled Firebase
Analytics in production for the first time (see entry above on D1-retention
instrumentation) — both landed together, so the full before/after story has
three data points, all Lighthouse 13.4.0/desktop-preset, same caveat as before
(`LanternError: NO_LCP` against this canvas-rendered app — treat LCP as
directional, not precise):

| state | LCP | TBT | total weight | score | artifact |
|---|---|---|---|---|---|
| baseline (JS, no analytics) | 2864ms | 221ms | 2838 KB | 0.69 | `lighthouse-playwarmer-baseline.report.{html,json}` |
| `--wasm` only, sandbox (no analytics) | 2635ms | 13.5ms | 2421 KB | 0.79 | `lighthouse-wasm-experiment.report.{html,json}` |
| `--wasm` + analytics, production (uncertain provenance — see below) | 3173ms | 90.5ms | 2990 KB | 0.73 | `lighthouse-playwarmer-launch1-final.report.{html,json}` |
| **`--wasm` + analytics + deferred-init, production (verified, authoritative)** | **3082ms** | **26ms** | **2990 KB** | **0.76** | `lighthouse-playwarmer-launch1-verified.report.{html,json}` |

**Deployment incident discovered mid-wave, affecting the third row above:**
while capturing screenshots for the design-reviewer gate, a shipped UI fix
wasn't appearing on production despite a successful deploy. Root-caused to two
compounding issues: (1) `vercel.json` had a `Cache-Control` rule for
`main.dart.js` but none for `main.dart.wasm`/`.mjs` (new files this wave never
added), and (2) more seriously, `vercel deploy --prod` had silently stopped
updating the `playwarmer.vercel.app` alias partway through the wave — it kept
aliasing to a longer auto-generated `*-gaurav-gandhi-2411s-projects.vercel.app`
form instead, with zero errors, so every prior smoke check/Lighthouse run/
screenshot kept "passing" while possibly checking stale content (they only
proved *some* build boots, not *this* one). Root cause of the alias drift
itself not fully determined. Fixed: `vercel.json` now has explicit cache rules
for the wasm/mjs files, and `deploy-warmer.ps1` now (a) explicitly runs
`vercel alias set` after every deploy instead of trusting automatic aliasing,
and (b) fetches the live `main.dart.wasm` and byte-compares it against the
local build, purging the CDN cache and re-checking once before failing loudly
on any mismatch — both steps verified working end-to-end. The third table row
above (measured before this was caught) has uncertain provenance as a result;
the fourth row was re-measured immediately after the fix, with the deploy
script's own new guard confirming byte-for-byte that production matched the
local build at measurement time — that row is the authoritative one.

**Root cause of the production regression vs. the sandbox measurement (measured,
not guessed):** enabling `ANALYTICS_ENABLED=true` doesn't load *just* Analytics
— `Firebase.initializeApp()` is a single shared call, and Flutter web's plugin
registrant eagerly loads the JS SDK for every registered Firebase plugin
(`firebase-app.js`, `firebase-firestore.js`, `firebase-auth.js`,
`firebase-analytics.js`, `firebase-messaging.js`, `firebase-app-check.js` — confirmed
via the Lighthouse network-requests audit, ~211KB combined), not just the one
product actually needed for the retention metric. Tried the obvious cheap fix
— deferred `main()`'s `await Firebase.initializeApp()` (and AdMob/UMP init) to
run *after* `runApp()` instead of blocking the first frame on it (see the
`perf: defer Firebase/AdMob init` commit) — real but small win (LCP
3240ms->3173ms, ~67ms). Confirmed via the same network-requests audit *why*
it's small: the browser fetches all these `<script>` resources in parallel at
HTML-parse time regardless of when the Dart code inside main.dart.wasm awaits
Firebase's init promise — reordering Dart-level awaits changes execution/
blocking order, not the underlying resource-fetch timing. A real fix would
need to stop loading Firestore/Auth/Messaging/AppCheck's JS eagerly when only
Analytics/Crashlytics are needed for the metric — that's a bigger, riskier
change (splitting one shared `Firebase.initializeApp()` call and its plugin
registration) than fits this wave's "paint and gates only" scope.

**Net honest result:** LCP is currently 3082ms (verified row above), over the
3000ms tracked ceiling by 82ms, directly because analytics instrumentation
(an explicit requirement of this wave — "measurement must exist before
launch, or the success metric is fiction") has a real, measured cost that the
cheap lever only partially offsets. This is a genuine tension between two of
this wave's own requirements, not an oversight — flagged here rather than
silently picking one side.

**Why CanvasKit is still accepted:** gives pixel-perfect cross-browser
rendering parity (matches the identical native look on Android/iOS), which
matters for a visually-branded word game. HTML renderer is not available on
this toolchain at all (Flutter 3.44.2; removed in 3.29) — see the renderer
decision doc.

**Budgets (rule 15e, ratified this pass):** initial own-domain JS bundle
(`main.dart.wasm` + `.mjs` + `flutter_bootstrap.js`) ≤ 1000 KB (current ~972 KB
combined; third-party CanvasKit/Firebase/RevenueCat CDN assets tracked
separately, not counted against this budget — still passing); LCP ≤ 2500ms
target / ≤ 3000ms tracked ceiling (current 3082ms, verified — **failing the
tracked ceiling** by 82ms, see above); TBT ≤ 200ms (current 26ms — passing);
CLS ≤ 0.1 (current 0).

**Revisit if:** a future pass has budget for splitting Firebase's eager
plugin-JS loading (load Analytics/Crashlytics eagerly, defer
Firestore/Auth/Messaging/AppCheck until first actual social-feature use,
mirroring `social_service.dart`'s existing lazy-init pattern) — the concrete,
scoped next lever, not attempted here. Also revisit the RevenueCat script
(187KB, pre-existing before this wave) loading unconditionally on web despite
IAP being force-disabled there (`iapEnabledEffective` always false on web) —
a second, independent bundle-size finding from this pass's network audit, not
yet investigated further.

## Native app release readiness (web-only launch; not currently player-visible)

### 15. Android release build still uses debug signing / scaffold applicationId

`app/android/app/build.gradle.kts` still has the Flutter-scaffold defaults:
`applicationId = "dev.gaurav.mindmeld"` and the release build type signed with the
debug keystore (`// TODO: Specify your own unique Application ID`, `// TODO: Add
your own signing config for the release build`).

**Why accepted:** Warmer's current launch is web-only (`playwarmer.vercel.app`); no
Android build has ever been distributed, so this affects zero real players today.

**Revisit if:** a native Android release (Play Store) is ever pursued — needs a
real applicationId decision and a release keystore before any distributable build.

## From the launch-1 design-reviewer sign-off (approved with suggestions, not blocking)

### 17. Win screen CTA density; unverified mobile/keyboard dimensions

Design-reviewer sign-off for the launch-1 aesthetic pass (`reports/screenshots/
wave-launch-1-readiness/`) was **approved with suggestions** — all 5 prior blocking
findings independently re-verified fixed (contrast recomputed from raw hex values,
not taken on faith). Non-blocking items logged here rather than fixed inline:

- **Win-screen CTA density**: the win screen stacks 5 distinct interactive asks
  (Copy & Share, Image, Challenge your group, notification opt-in Yes/Not-now,
  Back) in one view right after the celebratory moment. Not wrong on its own
  (Wordle/NYT-style result screens do this too), but approaching CTA fatigue.
  **Revisit if:** analytics (now actually collecting data — see entry above) show
  meaningful drop-off on this screen; a lighter-weight, collapsed-by-default
  treatment for the notification opt-in card would be the first thing to try.
- **Mobile breakpoint unverified**: all review screenshots were captured at a
  single ~900px desktop-ish viewport; no ~360px mobile-width capture exists to
  confirm no overflow/overlap there. **Revisit before/at next visual pass**:
  capture a narrow-viewport screenshot set and re-check.
- **Keyboard/focus-ring pass unverified**: `design_tokens.dart`'s
  `inputDecorationTheme.focusedBorder` does define a visible focus indicator
  (`tokens.accent`, 1.5px), a good sign, but actual tab-order and focus-ring
  rendering in the running app was not verified live. **Revisit**: a manual
  keyboard-only pass through the puzzle/settings/onboarding flows.
- **Possible tooltip artifact**: a floating "Friends" pill appeared above the nav
  bar in one captured screenshot, likely a `NavigationDestination` hover-tooltip
  render artifact from the automated capture tool rather than a real layout bug
  (unconfirmed either way — no live interaction was available in that review
  pass). **Revisit if**: this reproduces during a live manual pass — would need a
  real fix if so, not just a note.

### 19. REMEDIATED (2026-07-17) — `dart.library.html` conditionals silently stubbed web features on --wasm builds

Incident record, kept for the mechanism. `dart.library.html` is FALSE under
the `--wasm` compile target the canonical deploy has used since launch-1
(2026-07-12), so every `if (dart.library.html)` conditional import selected
the **stub** in production while every DDC-run test kept passing. Between
07-12 and 07-17, live production had: PrefsStore/localStorage persistence
instead of SQLite/IndexedDB, no-op share/download buttons, stub timezone in
notification writes, no iOS-PWA nudge, and (fixed mid-window) dead
`?reset=1`/`?notif=1`/`/join/{code}` handling.

**Remediation (wasm-stub-remediation wave, PR #10):** every site migrated to
package:web / `dart.library.js_interop`. The storage fix additionally needed
`sqflite_common_ffi_web` 0.4.5→1.1.2 — the old vendored worker COMPILED under
wasm but failed `WebAssembly.instantiate` at runtime — plus a one-time
PrefsStore→SQLite migration preserving fallback-era stats/streaks (day_state/
pack_progress not enumerable via StorageBackend; documented in
`persistence.dart` — worst case is a replayable-looking old puzzle, never a
lost streak).

**Why it can't recur:** (1) `test/wasm_stub_guard_test.dart` fails the suite
on any non-comment dart:html-era pattern in lib/; (2) the `e2e-web-wasm` CI
job runs the full integration suite via `flutter drive --wasm` AND probes the
production wasm artifact's storage backend at the IndexedDB level
(`firebase-tests/wasm_storage_check.js`). The test/prod compile-target gap
that hid this class is closed.

**Residual:** the PrefsStore fallback path in `persistence.dart` still exists
by design (real WASM-init failures on exotic browsers degrade gracefully);
`wasm_storage_check.js` distinguishes the two, so a silent regression to the
fallback now fails CI.

### 18. hi-en Warm band is structurally ~23 ranks wide (coarser gradient than EN)

The temperature bands are computed as `max(floor, n × fraction)` of vocab size
(`bandForRank` in `app/lib/core/models.dart`, constants in `core/config.dart`):
Scorching ≤ max(50, 0.1%·n), Hot ≤ max(500, 1%·n), Warm ≤ 5%·n. For the hi-en
vocab (n ≈ 10.5k) the Hot floor of 500 nearly swallows the Warm ceiling of
`0.05·n ≈ 523`, leaving Warm only ~23 ranks wide — so Hinglish play effectively
has a 4-band gradient (Scorching/Hot/Cold/Freezing) where EN (n = 55k) has all
five. Found while authoring the first-session onboarding puzzle: the hi-en
pre-seeded example guess targets **Hot** as its "mid" teaching band because Warm
is not reliably targetable at this vocab size.

**Why accepted:** the floors exist to keep bands meaningful under the current
model's neighborhood structure — hi-en similarity is noisy enough (entry 1) that
a proportional-only Hot band (~105 ranks) would misclassify genuinely-close
guesses as Warm. Narrowing the floors is a band-tuning exercise that only makes
sense on top of a better embedding model, not before it.

**Revisit:** together with the Hinglish fine-tune (entry 1's revisit condition) —
re-derive band fractions/floors from the improved model's rank distributions.

### 20. Subword-tokenization collision on short/rare romanized Hindi tokens —
probed with targeted training data, does not reliably move (2026-07-19)

The public 34-secret benchmark (`gauravgandhi2411/hinglish-relatedness-benchmark`,
v1.1) localized a residual weakness to the emotion/nature domains specifically —
`junoon`, `registan`, and partially `jheel`/`udaasi` — after two labeling
artifacts in the benchmark itself (2 degenerate self-identical loanword pairs, 1
ambiguous EN gloss) were found and fixed and did NOT explain it. Root-caused via
direct nearest-neighbor inspection: these words' own embeddings are dominated by
unrelated English words sharing a coincidental subword fragment (`junoon`
neighbors `afternoon`/`noon`/`june`; `registan` neighbors `register`/`registry`/
`registration`) — correctly, conventionally spelled romanizations (no better
spelling exists in vocab), not a transliteration error and not a benchmark-
editable defect.

**Probed before committing to GCP-scale data mining** (per spec-hinglish-
research-release.md's own risk section: "don't spend GCP credits scaling data
that a cheap probe shows won't move the metric"): found 9 other short/rare
hi-en words (no-leakage-verified against all 60 daily-schedule secrets + every
pack + the 34 benchmark secrets) with the same collision signature — and
discovered they ALREADY had one round of mined hard negatives in the shipped
model's own training data (`hard_negatives.py`'s rank-band-50-500 mining) and
still failed, meaning "add a hard negative" was already tried and insufficient.
Built a SECOND, more precisely-targeted round (the literal top confusion word
per candidate, not a rank-band sample), fine-tuned with the winning LoRA recipe
(r=8/alpha=16/lr=2e-4/4 epochs) via in-memory data injection (no benchmark or
training-file leakage), evaluated on the frozen public benchmark.

**Result: no clean win.** Full-34 dim1 Spearman delta +0.0037 [-0.026,+0.033],
not CI-significant. Dim2 pass-rate delta -0.0606 [-0.152, 0.000], not
CI-significant but the CI upper bound sits at exactly zero — a directionally
negative result, not a clean null. The 4 target secrets moved inconsistently
(registan/jheel modestly closer but still failing; junoon flat; udaasi got
worse) with zero pass/fail flips. Two previously-passing, unrelated secrets
(`bhanji`, `judwaa`) newly regressed — not a zero-regression outcome even
setting the weak headline numbers aside.

**Why accepted (for now):** a second, hand-precision-targeted round of hard
negatives on a proven-working recipe (0.12% trainable params) failing to move
9 independently-selected words showing the identical failure signature is
real evidence against "more of this same kind of data, same LoRA capacity"
scaling cleanly. Full detail: `generator/evals/finetune/probe_subword_collision.py`,
`generator/evals/finetune/data/probe_subword_collision.eval_result.json`.

**Revisit:** a materially different lever, not a bigger version of the same
one — candidates: iterative multi-round hard-negative mining at real scale
(dozens-to-hundreds of words, not 9), higher LoRA rank/capacity, or a
non-fine-tuning mitigation (retrieval-time reranking, subword-aware
tokenization, model ensembling). Test any of these on the same cheap-probe
pattern before GCP-scale commitment.

### 21. LoRA training's `load_best_model_at_end` silently loads the LAST
epoch, not the tracked-best one (found 2026-07-19, not yet fixed)

`train_lib.py`'s `SentenceTransformerTrainingArguments(load_best_model_at_end=
True, metric_for_best_model="eval_dev_spearman_cosine")` does not actually load
the best-tracked checkpoint for `method="lora"` runs — verified directly
(reloaded a saved LoRA checkpoint and recomputed its dev Spearman): the saved
model's dev score exactly matches the LAST epoch's value, not the highest one
in the run's own dev curve. Root cause not yet isolated (likely a state-dict
shape mismatch between the live PEFT-wrapped model the trainer holds in memory
and what gets restored from a saved checkpoint directory, similar in spirit to
the already-documented `auto_model` read-only-property gotcha in
`ship_decision_report_v3.md`'s "Gotchas discovered").

**Checked impact on the shipped model**: `obj_hard_neg`'s own dev curve shows
claimed-best epoch 3 (0.8367) vs actual epoch 4 (0.8353), Δ0.0014 — immaterial,
and moot regardless: this project's TEST numbers are always computed fresh
against whatever model artifact was actually saved (never the abstract
"tracked best" value), and dev is never reported as a result by design (see
entry 1) — so no previously-shipped or previously-reported number is affected.

**Why not fixed yet:** found as a side effect of the entry-20 probe, out of
that task's scope. Real risk going forward: any FUTURE LoRA sweep that picks
between epochs by trusting the trainer's "best" metric (rather than by
directly re-evaluating the saved artifact, as this project's ship decisions
already do) could silently ship a worse checkpoint than intended.

**Revisit:** before the next LoRA training sweep — either fix the root cause,
or at minimum add an assertion that reloads the saved checkpoint and confirms
its dev score matches the trainer's own claimed best before trusting it.

## Documentation hygiene (not a product limitation, noted for completeness)

### 16. Eval baseline report predates the maxGuesses tuning fix

`generator/evals/reports/baseline_report.md`/`.json` were regenerated as part of
this pass (`uv run python -m evals.harness.report`, full re-run including the
Ollama-backed dimension 3 judge, ~40 minutes) to pick up the maxGuesses-tuning fix's
dimension 5 numbers — the previously-committed report still showed the pre-fix
median win-rate (93.0%, 10.5% in-band) instead of the post-fix numbers reported in
PLAN.md's security-hardening section (82.0%, 63.6% in-band). See the regenerated
report for current numbers across all 5 dimensions as of this commit.
