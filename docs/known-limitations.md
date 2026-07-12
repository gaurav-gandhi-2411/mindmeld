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

### 14. Flutter-web cold-boot latency (CanvasKit)

Lighthouse baseline against the live production site
(`reports/performance-baseline-2026-07-12.md`, raw artifacts
`reports/lighthouse-playwarmer-baseline.report.{html,json}`, this commit):
**LCP 2864ms, FCP 934ms, TBT 221ms, CLS 0, Speed Index 2797ms, total page weight
2,838 KB (of which `canvaskit.wasm` alone is 1,613 KB), Lighthouse performance
score 0.69/1.0**. Caveat already noted in that report: Lighthouse's Lantern
network simulation throws `LanternError: NO_LCP` against this canvas-rendered
(not DOM-rendered) app — there's no traditional "largest contentful DOM element"
to key off, so treat the LCP number as directionally useful, not precise. The
dominant payload cost is Flutter web's CanvasKit renderer — a fixed cost of the
Flutter-web rendering strategy, not something this app's own code drives down
further without a renderer change.

**Why accepted:** CanvasKit gives pixel-perfect cross-browser rendering parity
(matches the identical native look on Android/iOS), which matters for a
visually-branded word game. The alternative (`html` renderer) trades that fidelity
for a smaller bundle and was not evaluated as part of this pass.

**Budgets (rule 15e, ratified this pass)** — previously proposed-but-unratified in
`reports/performance-baseline-2026-07-12.md`): initial own-domain JS bundle
(`main.dart.js` + `flutter_bootstrap.js`) ≤ 1000 KB (current ~932 KB combined;
third-party CanvasKit/RevenueCat CDN assets tracked separately, not counted
against this budget); LCP ≤ 2500ms (current 2864ms — a near-term target, subject
to the Lantern caveat above); TBT ≤ 200ms (current 221ms); CLS ≤ 0.1 (current 0).

**Revisit if:** a future Lighthouse re-run regresses past these budgets, or the
`html` renderer's visual fidelity gap closes enough to reconsider.

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
