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

### 23. FIXED SAME-SESSION (2026-07-30) — eager-boot SQLite query storm caused a real production boot hang

Incident record. Deploying the archive/streak-freeze/rival feature set caused
production to serve a genuine blank white screen: `ArchiveScreen` is mounted
eagerly at app boot (`IndexedStack` builds every tab regardless of the
selected index), and its `_loadSolvedStates()` fired one SQLite query per
available date (dozens, via `Future.wait`) **unconditionally in `initState`**
— racing Firebase/Analytics initialization on the same boot frame. The
post-deploy smoke check (`firebase-tests/smoke_check.js`) caught it
immediately (`app did not boot within 30000ms`, zero page/request errors —
a silent hang, not a crash); confirmed visually via `cold_repro_reload.js`
(a real blank screenshot after 17.5s).

**Caught and fixed within the same deploy session, before real users were
meaningfully exposed:** rolled back to the prior known-good deployment first
(production must not stay broken while debugging — `vercel rollback` itself
doesn't support this project's custom-alias deploy flow, worked around by
re-running the same `vercel alias set` step `deploy-warmer.ps1` uses), then
root-caused by reproducing the exact `--wasm` production build locally
(`python -m http.server` + `smoke_check.js` against `localhost` hung
identically — confirmed, not guessed). Fixed with an `active` flag on
`ArchiveScreen` (`main.dart` passes `active: _navIndex == 1`) deferring the
query batch until the player actually opens the Practice tab. Verified the
SAME local build boots cleanly with the fix applied BEFORE redeploying.

**Why this slipped through**: `flutter test`/`flutter analyze` run on the
native VM target and gave zero signal — the failure was specific to the real
`--wasm` boot sequence under real eager-widget-tree concurrency, a gap no
unit/widget test in this suite covers. Also newly understood while fixing
this: `StatsScreen`'s existing `active` flag (the precedent `ArchiveScreen`
was modeled on) only gates *re*-loads on tab-switch, not its own initial
boot-time load either — it just does one cheap query, so it never surfaced
this failure mode, but the same eager-boot-load pattern exists there too.

**Residual, not yet closed**: no automated pre-deploy check runs the actual
production `--wasm` build's smoke test before promoting to production —
today's catch relied on the POST-deploy smoke check plus a human (session)
noticing and stopping to investigate rather than declaring the deploy done.
Revisit: add a pre-promotion local-wasm-boot check to `deploy-warmer.ps1`
itself (build → serve locally → smoke-check → only then promote), so a
future regression of this class fails before touching production at all,
not after. Not built under this session's own time pressure — recorded here
so it isn't forgotten instead.

### 18. FIXED (2026-07-24) — hi-en Warm band was structurally ~24 ranks wide
(coarser gradient than EN)

The temperature bands are computed as `max(floor, n × fraction)` of vocab size
(`bandForRank` in `app/lib/core/models.dart` / `band_for_rank` in
`generator/rival.py`, constants in `core/config.dart`): Scorching ≤ max(50,
0.1%·n), Hot ≤ max(500, 1%·n), Warm ≤ 5%·n (no floor, pre-fix). For the hi-en
vocab (n = 10,495) the Hot floor of 500 nearly swallowed the un-floored Warm
ceiling of `int(n×0.05) = 524`, leaving Warm only 24 ranks wide (0.23% of
vocab) — so Hinglish play effectively had a 4-band gradient
(Scorching/Hot/Cold/Freezing) where EN (n = 55,000, Warm = 2,200 ranks / 4.0%
of vocab) had all five. Found while authoring the first-session onboarding
puzzle: the hi-en pre-seeded example guess had to target **Hot** as its "mid"
teaching band because Warm was not reliably targetable at this vocab size.

**Root cause, isolated**: unlike Scorching and Hot, Warm's ceiling had no
floor of its own (`warm_max = int(n × 0.05)`, vs. Hot's
`max(500, int(n × 0.01))`) — so at small vocab sizes, Hot's floor eating into
the un-floored Warm ceiling had nothing to counteract it.

**Fixed**: added a 900-rank floor to Warm, the same `max(floor, n × fraction)`
shape Scorching and Hot already use — `warm_max = max(900, int(n × 0.05))` in
both `rival.band_for_rank` (Python) and `bandForRank` (Dart,
`AppConfig.warmFloor`). 900 was chosen empirically (not the initially
hypothesized "just raise `warmFraction` to 0.08" — that alternative was
rejected because it also inflates EN's Warm band from 4.0% to 7.0%, eating
into EN's Cold band, contradicting the goal of leaving EN untouched) to give
hi-en a ~400-rank / 3.8% Warm band — matching EN's existing proportional feel
— while the floor mathematically cannot bind for EN (55,000 × 0.05 = 2,750 ≫
900), leaving EN's band boundaries byte-for-byte unchanged (verified: 0 of 227
EN bake-off scenario records changed `actual_band` under the new formula).
Every other duplicated `n × 0.05` re-derivation in the codebase
(`rival._generate_path`'s adaptive-convergence threshold,
`dimension5_winrate._simulate_one`'s player-model threshold,
`test_onboarding_build.py`'s teaching-ladder boundary check) was updated to
carry the same floor so none of them silently drift out of sync with the real
scoring boundary.

**Verified impact**: hi-en's band-confusion matrix (bake-off checkpoint
`gauravgandhi2411/hinglish-relatedness-sbert`, 379 dim1 records) shows Warm's
predicted count rising from 2 to 17 records and recall rising from 1.2% to
8.3% of expected-Warm records (precision holds at ~0.41-0.50, i.e. the newly
captured records aren't noise); a 118-puzzle × 100-simulated-guesser
win-rate-model rerun shows the fraction of simulated guesses landing in Warm
rising from 0.37% to 4.44%; `dimension4_rival`'s rival-path calibration gates
(par ∈ [4,16], chill/sharp spreads) are unaffected (0 flagged puzzles, both
before and after, across 236 real daily+pack puzzles, both langs) since Hot's
floor — not Warm's — dominates path pacing. `docs/model-excellence-final-
report.md` finding #1 and `PLAN.md` carry the full before/after numbers.

**Revisit:** together with the Hinglish fine-tune (entry 1's revisit
condition) — re-derive band fractions/floors from the improved model's rank
distributions if a future embedding upgrade changes hi-en's neighborhood
structure enough to warrant it.

### 20. CHARACTERIZED BOUNDARY, NOT CLOSED — subword-collision + associative-
commonsense relatedness on a handful of words; one lever proven dead, four
live attacks triaged for a future resume (2026-07-19)

**Status: this is a triaged attack list, not an accepted-and-parked
limitation.** The Hinglish accuracy push is closing cleanly at its current
field-leading state (see entry 1) because the one lever tested came back
negative — not because the residual is believed unfixable. Anyone resuming
this work should start from the live-attacks list below, not from scratch.

**What the residual actually is**: the public 34-secret benchmark
(`gauravgandhi2411/hinglish-relatedness-benchmark`, v1.1) localized a
weakness to the emotion/nature domains specifically — `junoon`, `registan`,
and partially `jheel`/`udaasi` — after two labeling artifacts in the
benchmark itself (2 degenerate self-identical loanword pairs, 1 ambiguous
EN gloss) were found, fixed, and did NOT explain it. Root-caused via direct
nearest-neighbor inspection: these words' own embeddings are dominated by
unrelated English words sharing a coincidental subword fragment (`junoon`
neighbors `afternoon`/`noon`/`june`; `registan` neighbors `register`/
`registry`/`registration`) — correctly, conventionally spelled romanizations
(no better spelling exists in vocab), not a transliteration error and not a
benchmark-editable defect. This is best characterized as a mix of subword-
tokenization collision (mechanical: the base tokenizer fragments short/rare
romanized tokens into pieces that happen to match common English morphemes)
and associative/world-knowledge relatedness (a handful of these words need
cultural/associative context a distributional embedding doesn't get for
free from co-occurrence alone) — both plausible, not cleanly separated by
the evidence gathered so far.

**LEVER 1 — PROVEN DEAD**: more same-style contrastive hard negatives at
the current LoRA capacity (r=8, 0.12% trainable params). Probed before any
GCP-scale mining commitment (per spec-hinglish-research-release.md's own
risk section: "don't spend GCP credits scaling data that a cheap probe
shows won't move the metric"). Found 9 other short/rare hi-en words with
the identical collision signature, no-leakage-verified; discovered they
ALREADY had one round of mined hard negatives in the shipped model's own
training data and still failed (so "add a hard negative" was already tried
and insufficient); built a SECOND, hand-precision-targeted round (each
word's actual current top confusion, not a rank-band sample); fine-tuned;
evaluated on the frozen benchmark. **Result: no clean win** — full-34 dim1
delta +0.0037 (not sig.), dim2 delta -0.0606 (not sig., CI upper bound at
exactly zero — directionally negative), target words moved inconsistently
with zero pass/fail flips, 2 unrelated secrets newly regressed. Full
detail: `generator/evals/finetune/probe_subword_collision.py`,
`generator/evals/finetune/data/probe_subword_collision.eval_result.json`.
**Do not re-run this exact lever** — it has already been tested with
precision targeting and failed.

**LIVE ATTACKS — untested, triaged roughly cheapest/most-promising first**:
1. **Higher LoRA capacity** (r=16/32, or unfreeze more target modules) —
   the current r=8 config was chosen for the ORIGINAL data-volume regime
   (1741 pairs); it was never re-swept at higher rank against a residual
   this specific. Cheapest lever to test — no new data needed, one sweep.
2. **Iterative multi-round hard-negative mining at real scale** — the dead
   lever above tested 9 words with one hand-picked negative each; a proper
   iterative loop (mine → train → re-mine against the NEW model's current
   confusions → repeat, dozens-to-hundreds of words) is a materially
   different experiment, not a bigger version of the same one.
3. **Retrieval-time reranking (non-fine-tuning mitigation)** — if a small,
   fixed set of words are structurally hard for this embedding approach, a
   cheap lexicon/lookup override at query time for known-hard words may be
   more reliable than chasing them through training data.
4. **A base model with better romanized-Hindi tokenization** — the
   collision mechanism is a tokenizer artifact of `l3cube-pune/indic-
   sentence-bert-nli`'s subword vocabulary specifically; a base model
   trained with more romanized-Hindi-aware tokenization might not have
   this failure mode at all. Requires a fresh base-model bake-off (last
   one, `phase1_benchmark_report.md`, found no newer base beats l3cube
   OVERALL — but wasn't testing FOR this specific failure class).
5. **Real player-guess data, post-launch** — the standing, license-free,
   genuinely in-domain signal no external corpus or synthetic mining can
   match (flagged repeatedly across this project's history, e.g.
   `spec-hinglish-benchmark.md`'s Phase 2a note). Not actionable pre-launch,
   but the eventual strongest lever.

**Revisit:** any of the 5 live attacks, tested on the same cheap-probe
pattern (small, targeted, frozen-benchmark-measured, CI-checked) before a
GCP-scale commitment to any of them.

**UPDATE (2026-07-23) — L4/L5/L6 status since this entry was written**:
attack #3 above (retrieval-time reranking, non-fine-tuning) was subsequently
implemented as **L5** (`spec-residual-attack.md`) and SHIPPED to production
combined with the narrow L2 Devanagari patch (`payload.py`'s
`_build_payload_core`; PLAN.md's 2026-07-23 ship decision — see entry 1's
production-wrapper note). **L4 (knowledge distillation)** and **L6
(commonsense-shaped training data)** were both since probed at small scale
(`generator/evals/finetune/probe_lever_l4_distillation.py` /
`probe_lever_l6_commonsense_data.py`, result JSONs alongside): L4 shows a
bounded, zero-net-regression result on the 5 (of 8) curated candidates whose
teacher-verified property survived calibration — the large rank gains
observed are on TRAINED words only (not generalization evidence, per the
probe's own overfitting caveat), and its GCP checkpoint was lost with the
deleted VM, so reproducing/scaling it needs a retrain. L6 is genuinely
inconclusive on its held-out generalization check (5/8 words' related-word
rank improved, 3/8 regressed, n=8 too small to call). **Both L4 and L6
remain live, untested-at-scale levers, not closed** — full detail:
`PLAN.md`'s "L4/L6 status for future resume" section.

### 21. FIXED (2026-07-19) — LoRA training's `load_best_model_at_end` was
silently loading the LAST epoch, not the tracked-best one

`train_lib.py`'s `SentenceTransformerTrainingArguments(load_best_model_at_end=
True, metric_for_best_model="eval_dev_spearman_cosine")` did not actually load
the best-tracked checkpoint for `method="lora"` runs — verified directly
(reloaded a saved LoRA checkpoint and recomputed its dev Spearman): the saved
model's dev score exactly matched the LAST epoch's value, not the highest one
in the run's own dev curve.

**Root cause, isolated**: `transformers.Trainer._load_best_model()` branches
on `_is_peft_model(self.model)` — but for `SentenceTransformerTrainer`,
`self.model` is the OUTER `SentenceTransformer` container, never the nested
`PeftModel` (which lives at `model[0].auto_model`). `_is_peft_model` therefore
always returns `False` for a LoRA run, so the Trainer's checkpoint-loading
logic falls through to its non-PEFT branch, which looks for a full
`model.safetensors`/`pytorch_model.bin` in the checkpoint directory — but a
LoRA checkpoint only ever contains `adapter_model.safetensors`. The load
silently no-ops rather than raising.

**Fixed**: `train_lib._load_best_lora_checkpoint()` explicitly restores the
best checkpoint's adapter weights via `peft.set_peft_model_state_dict` right
after `trainer.train()` returns (bypassing the Trainer's broken PEFT
auto-detection entirely), then verifies the reload by recomputing the dev
score and asserting it matches the trainer's own tracked-best value — raises
loudly, not silently, if the checkpoint file is missing or the reload doesn't
reproduce the expected score. Regression test:
`tests/test_train_lib_lora_best_checkpoint.py` — runs a real (small, 2-epoch)
LoRA training loop and asserts the saved model's actual dev score matches the
tracked best, not merely whatever the last epoch produced; a mock-only test
would not have caught the original bug, since it's a real interaction between
`SentenceTransformerTrainer`, PEFT, and the transformers `Trainer`'s
checkpoint I/O.

**Checked impact on the shipped model**: `obj_hard_neg`'s own dev curve shows
claimed-best epoch 3 (0.8367) vs actual epoch 4 (0.8353), Δ0.0014 — immaterial,
and moot regardless: this project's TEST numbers are always computed fresh
against whatever model artifact was actually saved (never the abstract
"tracked best" value), and dev is never reported as a result by design (see
entry 1) — so **no previously-shipped or previously-reported number changed**;
this fix only protects FUTURE training runs, which is why it was worth doing
immediately despite being found as a side effect of the entry-20 probe.

### 22. No suitable external public benchmark exists for this project's specific
task shape (romanized code-mixed word-relatedness) -- searched, documented, none found

spec-model-excellence.md Workstream D item 14 asks for a search of existing public
code-mixed or Hindi semantic-similarity resources, to establish external
comparability or, failing that, to evidence the "no public benchmark existed" claim
this project's own published benchmark (`gauravgandhi2411/hinglish-relatedness-benchmark`)
implicitly makes. This entry documents a live web search (2026-07-24) distinct from
and extending entry 20's/`ship_decision_report_v2.md`'s earlier licensing search --
that one covered candidate *training-data* sources (Hindi WordSim-353, Multi-SimLex
Hindi, IndoWordNet, IndicCorp, HingCorpus, Aksharantar); this one specifically targets
existing *evaluation benchmarks* for the code-switched/romanized-Hindi NLP space,
ground that search never covered.

Checked, with findings:
- **GLUECoS** (Khanuja et al. 2020, Microsoft Research) -- a real, actively-cited
  Hindi-English code-mixed evaluation benchmark. Task mismatch, not a licence issue:
  its six tasks are Language ID, POS tagging, NER, Sentiment Analysis, QA, and NLI --
  no semantic similarity/relatedness task of any kind.
- **LinCE** (Aguilar et al. 2020) -- similar code-switching benchmark suite
  (LID/NER/POS across 4 language pairs including Hindi-English). Same mismatch: no
  relatedness/similarity task.
- **SemRel2024** (Ousidhoum et al., ACL Findings 2024) -- does cover Hindi semantic
  *relatedness*, native-speaker-annotated. Two-dimensional mismatch on inspection: (1)
  it is **sentence-pair** relatedness, not word-level (this project's task is ranking
  ~10,495 individual words by relatedness to a secret word); (2) it is monolingual
  Hindi, not romanized/code-mixed Hinglish (script/code-mixing status not confirmed
  via the dataset card itself, but the task framing and annotation methodology --
  paid native-speaker sentence comparison -- match a standard monolingual STR setup,
  not this project's code-switched, single-word regime).
- **IIIT-Hyderabad Indian-language word-similarity sets** (~100-200 pairs across 7
  Indian languages, WordSim-353-style) -- word-level, closer in shape, but
  monolingual (Devanagari) and in the same IndoWordNet-adjacent
  research-only-licence family entry 20/`ship_decision_report_v2.md` already ruled
  out for training-data use; not re-verified for eval-only use (a looser bar than
  training/commercial redistribution) but not pursued further given the shape
  mismatch (monolingual, not romanized code-mixed) already disqualifies it as an
  external comparability point for THIS benchmark's specific claim.
- **HinglishEval** (Srivastava & Singh 2022) -- a real Hinglish-specific resource,
  but evaluates generated-text *quality* (fluency/appropriateness of code-mixed
  text), not word or sentence relatedness -- unrelated task.

**Conclusion**: no existing public resource matches this project's specific task
shape (word-level relatedness ranking over romanized, code-mixed Hindi-English text).
This is a genuine gap, not merely an unsearched one -- the closest resource by task
type (GLUECoS/LinCE) lacks a relatedness task entirely; the closest by task
(SemRel2024) lacks both the word-level grain and the romanized/code-mixed property.
This evidences, rather than merely asserts, this project's benchmark's "no directly
comparable public dataset existed" position. Re-check periodically -- this is an
active research area (e.g. arXiv:2606.30790 "Indi-RomCoM", 2026, and
arXiv:2503.21670 "COMI-LINGUA", 2025, both post-date this project's original 2026-07
training-data search and show the space is still moving) and a suitable resource
could emerge later.

## Deferred roadmap (spec-warmer-closeout.md WORKSTREAM 5 — explicitly NOT built this pass)

Post-launch candidates, triaged and recorded so they're a considered list rather than
forgotten ideas or silently dropped. None of these are launch blockers; all need real
usage data or nontrivial new infrastructure this closeout deliberately didn't build.

### R1. Any-word guessing (on-device quantised embedding model)

Currently guesses are scored against a fixed, precomputed vocab (the payload's `words`
map) — a player typing a word outside that vocab gets an out-of-vocab rejection, not a
real semantic score. True any-word guessing needs a browser-runnable quantised
embedding model (WASM/ONNX-Runtime-Web or similar) to embed arbitrary player input
client-side. Heavy (model download size, inference latency budget, a second
model-quality bar beyond the existing server-precomputed one) — better scoped after
real usage shows how often players actually hit the out-of-vocab wall, rather than
building speculatively.

### R2. Post-game semantic map

A visual (e.g. force-directed or UMAP-style) map of the player's guesses in embedding
space, shown after a win/loss, so players can SEE why a guess was hot/cold relative to
others. Genuine engagement enhancement, not a launch blocker — needs its own design
pass (what's spoiler-safe to show, rendering approach for a CanvasKit app) before
scoping further.

### R3. LLM content pipeline

Clue/secret authoring for packs is currently a manual, human-reviewed process (see
every pack's own spec.md-style content doc and GG-review stop points). An LLM-assisted
drafting pipeline (candidate generation + automated embedding/spoiler/semantic-neighbor
pre-screening, still human-reviewed before baking) could speed up future pack
authoring, but isn't needed until pack cadence itself demands it — premature to build
ahead of a proven need.

### R4. Further Hinglish model gains (L4 distillation / L6 commonsense data)

Both remaining levers identified in prior model-excellence work
(`docs/model-excellence-final-report.md`) are **data-hungry**: L4 (knowledge
distillation from a larger teacher) needs a strong teacher + compute budget beyond
this project's $0-cost-path default; L6 (commonsense training data) needs volume no
synthetic-generation pass has matched. The standing best source for either is **real
player guess data** (which words players actually try, which ones the model
under/over-ranks in practice) — doesn't exist yet at any real N since the game hasn't
had real traffic. Revisit once usage data accumulates; building either lever ahead of
that data would be guessing at what to fix.

### R5. Pre-promotion local-wasm-boot check in the deploy script

Carried forward from known-limitations entry 23 (today's boot-hang incident): no
automated check currently runs the actual production `--wasm` build's smoke test
BEFORE promoting to production — today's catch relied on the POST-deploy smoke check
plus a human noticing and stopping to investigate. Add a pre-promotion local-build +
serve + smoke-check step to `deploy-warmer.ps1` itself, so this failure class is
caught before touching production, not after. Small, concrete, and worth doing soon —
listed here rather than built under this session's own time pressure.

## Documentation hygiene (not a product limitation, noted for completeness)

### 16. Eval baseline report predates the maxGuesses tuning fix

`generator/evals/reports/baseline_report.md`/`.json` were regenerated as part of
this pass (`uv run python -m evals.harness.report`, full re-run including the
Ollama-backed dimension 3 judge, ~40 minutes) to pick up the maxGuesses-tuning fix's
dimension 5 numbers — the previously-committed report still showed the pre-fix
median win-rate (93.0%, 10.5% in-band) instead of the post-fix numbers reported in
PLAN.md's security-hardening section (82.0%, 63.6% in-band). See the regenerated
report for current numbers across all 5 dimensions as of this commit.
