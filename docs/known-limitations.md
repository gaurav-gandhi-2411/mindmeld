# Known Limitations — Warmer

Supersedes `docs/accepted-risks.md` (folded in below, entries 1–8; the `.gitignore`
hardening item from that ledger shipped and is dropped here — it's resolved, not a
limitation). Written as part of the 2026-07-12 known-limitations pass. Each entry
states what it is, why it's accepted as-is, what fixing it would actually require,
and the condition under which we'd revisit. These are conscious trade-offs with
stated reasoning, not blind spots — see PLAN.md for the session-by-session history
behind each one.

## Product / gameplay

### 1. Hinglish semantic ranking quality is well below English

Measured via the applied-AI eval harness (`generator/evals/harness/`, full production
vocab + 60-day schedule): hi-en Spearman correlation **0.639** vs EN **0.837**;
hi-en band-accuracy 67.8% vs EN 74.9% (`generator/evals/reports/baseline_report.md`,
regenerated after the 2026-07 Hinglish-fix pass — see PLAN.md's "Hinglish semantic
engine fix" section for the full 9-candidate bake-off). This was a categorical fix
from a genuinely broken starting point (Spearman **-0.003**, i.e. no correlation at
all, cross-language pass rate 5.1%) to a working-but-imperfect state (cross-language
pass rate 54.2%), by swapping the hi-en embedding model to
`l3cube-pune/indic-sentence-bert-nli`.

Residual worst-diverging pairs (a player who guesses the literal English translation
of a Hinglish secret still gets muted temperature signal), worst-first:
`titli`←butterfly, `khamoshi`←silence, `rasoi`←kitchen, `samunder`←ocean,
`bachpan`←childhood. (Full residual list of 10 in the baseline report also includes
khidki←window, tyohar←festival, razaai←blanket, parchhain←shadow, pul←bridge, all
progressively less severe.)

**Why accepted:** every off-the-shelf multilingual/code-mixed embedding model tested
(9 candidates) underperforms EN parity on romanized Hindi. Closing the gap needs a
Warmer-specific fine-tune on Hinglish similarity pairs — a real ML project (data
collection, fine-tuning, eval-gated bake-off against the current champion), not a
config change or a bug fix.

**Revisit if:** Hinglish becomes a primary (not secondary) language for the player
base, or a suitable pre-trained checkpoint closer to EN parity ships publicly.

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

## Documentation hygiene (not a product limitation, noted for completeness)

### 16. Eval baseline report predates the maxGuesses tuning fix

`generator/evals/reports/baseline_report.md`/`.json` were regenerated as part of
this pass (`uv run python -m evals.harness.report`, full re-run including the
Ollama-backed dimension 3 judge, ~40 minutes) to pick up the maxGuesses-tuning fix's
dimension 5 numbers — the previously-committed report still showed the pre-fix
median win-rate (93.0%, 10.5% in-band) instead of the post-fix numbers reported in
PLAN.md's security-hardening section (82.0%, 63.6% in-band). See the regenerated
report for current numbers across all 5 dimensions as of this commit.
