# Warmer — Semantic Daily Word Game

A daily word-guessing game: players guess a secret word and an embedding model scores how
semantically close each guess is (rank + temperature feedback). English + Hinglish editions.
All ML is offline — payloads are precomputed, so marginal cost per DAU is ~$0.

The Firebase project ID (`mindmeld-c4bba`) and the payload CDN path (`mindmeld-payloads`) are
unchanged internal infrastructure — only user-facing branding was renamed.

Phase 1 build: playable Flutter app (Android-first) + Python payload generator. Ads and IAP
are **stubs behind config flags** (`ads_enabled=false`, `iap_enabled=false`) — no SDK
dependencies. See [spec.md](spec.md) for full scope.

## Quick start — generator

```powershell
cd generator
uv sync
uv run python build.py --days 14 --langs en,hi-en --out ..\payloads
```

First run downloads two sentence-transformers models (~90 MB en, ~470 MB multilingual) and
embeds both vocabs (cached to `generator/.model-cache/`, so subsequent builds take seconds).
Output: `payloads/{lang}/{yyyy-mm-dd}.json.gz` + `payloads/manifest.json`.

```powershell
uv run pytest            # 160 unit tests + Hinglish eval gate
uv run python evals/run_evals.py   # eval fixtures standalone
```

## Payload format

Gzipped JSON per day per language. Anti-cheat design: the words map is keyed by
`sha1(word + salt)[:12]`, so the secret never appears in plaintext at a guessable key; the
reveal field `s` is XOR-obfuscated and decoded only on win/give-up. Similarities are
quantized to uint16 (round-trip error < 1e-4). Hint words exclude morphological variants of
the secret. Gzip is written with `mtime=0` so identical content produces identical bytes.

## Payload hosting

Payloads are published to the sibling repo
[mindmeld-payloads](https://github.com/gaurav-gandhi-2411/mindmeld-payloads), served via
GitHub Pages at `https://gaurav-gandhi-2411.github.io/mindmeld-payloads`. Any static host
works — the base URL lives in `app/lib/core/config.dart` (`payloadBaseUrl`).

```powershell
cd generator
uv run publish --days 30                        # build + commit + push (live)
uv run publish --days 30 --dry-run             # read-only: print what would happen
uv run publish --days 30 --langs en            # English only
uv run publish --days 30 --payloads-repo C:\other\path\mindmeld-payloads
```

The `publish` command:
1. Runs the build internally (no subprocess) into a temp directory.
2. Copies `en/`, `hi-en/`, and `manifest.json` into the payloads repo (overwrite; preserves
   `README.md`, `.nojekyll`, and any other unrelated files).
3. `git add -A` → commit (`chore: payload drop <first>..<last> (<langs>) [skip ci]`) →
   `git push origin main`. Skips commit/push if nothing changed.

The app bundles 7 days of payloads as assets (`app/assets/payloads/`) and falls back to them
on any fetch failure.

## Quick start — app

Requires Flutter ≥ 3.44 and an Android SDK.

```powershell
cd app
flutter pub get
flutter test --concurrency=1      # widget/unit tests
flutter build apk --debug
flutter test integration_test/app_test.dart -d <device>   # full guess→win loop, en + hi-en
```

## Web / PWA

Play in the browser: **https://playwarmer.vercel.app/**
(installable PWA; hosted on Vercel). The old `/play/` path on GitHub Pages now serves a
redirect to the Vercel URL.

Scripted as `./deploy-warmer.ps1` (repo root) — mirrors the commands below exactly;
keep both in sync if either changes. Also used by `docs/runbook.md`'s deploy/
rollback procedure.

```powershell
# Build and deploy to Vercel (canonical production flow):
cd app
# --wasm: adopted 2026-07-12 (launch-1 wave) after measuring a real Lighthouse
# improvement (TBT 221ms->13.5ms, LCP 2864ms->2635ms, -417KB) — see
# reports/renderer-decision-2026-07-12.md for the full before/after evidence.
# --dart-define=ANALYTICS_ENABLED=true: without this, Firebase Analytics never
# initializes and the PM header's D1-retention/completion-rate success metrics
# have zero data — see docs/known-limitations.md.
flutter build web --release --no-web-resources-cdn --wasm --dart-define=ANALYTICS_ENABLED=true
# Guard: fails loudly if a Firebase web plugin (auth/firestore/analytics/core)
# didn't register — see scripts/check_web_plugin_registrant.py docstring for why.
cd ..
uv run python scripts\check_web_plugin_registrant.py --project-dir app
# Guard: fails loudly if the deploy domain isn't in Firebase Auth's authorized
# domains — see scripts/check_authorized_domains.py docstring and the
# "Authorized domains" section in docs/firebase-setup.md.
uv run python scripts\check_authorized_domains.py --project-id mindmeld-c4bba --domain playwarmer.vercel.app
# Flutter ≥ 3.35 no longer ships a caching SW; generate one and patch the bootstrap.
# This also copies the tracked app/web/vercel.json (rewrites + Cache-Control
# headers) into the build dir — web-dist/ is gitignored deploy staging only,
# never the source of truth for vercel.json. It also copies+templates the
# tracked app/web/firebase-messaging-sw.js (FCM background messaging) with
# the real Firebase web config values.
uv run python scripts\make_web_sw.py --build-dir app\build\web
Copy-Item app\build\web\* web-dist\ -Recurse -Force

# Guard: local pre-promotion boot check (required — see the 2026-07-30 incident
# in docs/known-limitations.md entry 23). Serves the exact freshly-staged
# web-dist/ locally and requires a clean boot BEFORE anything is uploaded to
# Vercel, let alone promoted — reuses smoke_check.js's own boot detection
# against a local URL instead of production, so there's one implementation.
uv run python -m http.server 8322 --directory web-dist
# (in a second terminal, or after backgrounding the server above)
node firebase-tests\smoke_check.js http://localhost:8322/

cd web-dist
npx vercel deploy --prod --yes
cd ..

# Post-deploy smoke check (required — see the 2026-07-12 incident below):
# fails loudly (non-zero exit) unless the live URL returns 200 AND the
# Flutter engine actually booted. A deploy is NOT done until this passes —
# if it fails, check `vercel inspect`/build logs and re-deploy or roll back
# before doing anything else.
node firebase-tests\smoke_check.js https://playwarmer.vercel.app/

# Publish payloads (unchanged — Pages repo, /play/ is now redirect-only):
cd generator
uv run publish --days 30
```

**Uptime monitoring.** The hourly `Payload monitor` workflow in
[mindmeld-payloads](https://github.com/gaurav-gandhi-2411/mindmeld-payloads/blob/main/.github/workflows/monitor.yml)
checks that the UTC yesterday/today/tomorrow payloads for both languages return 200 and
decode, that the live app serves its shell, and warns when fewer than 14 future days are
published. It keeps one `payload-alert` issue (edited in place, auto-closed on recovery).
It replaced this repo's 15-minute `uptime-check.yml` (now disabled), which never tested
today's date and missed the 2026-08-19 outage when the payload schedule ran out. The
original motivation still holds: on 2026-07-12 the `playwarmer` Vercel project was deleted
and both production domains 404'd before anyone noticed. **You will only receive the alert if
GitHub email notifications for "Issues" are enabled on your account**
(github.com → Settings → Notifications) — verify this once; a check that
alerts nobody is a check that "logs," not one that "alerts."

**Deploying to a new/changed domain?** Firebase Auth only allows sign-in from
domains in the project's *Authorized domains* list (Authentication → Settings
→ Authorized domains in the Firebase console; `localhost` and the default
`*.firebaseapp.com`/`*.web.app` domains are the only ones added automatically —
a custom domain like `playwarmer.vercel.app` is NOT added for you). Forgetting
this step makes `signInAnonymously()` fail with a `[firebase_auth/channel-error]`
that looks like a plugin-registration bug but isn't — see the 2026-07-07 incident
note in `docs/firebase-setup.md`. `scripts/check_authorized_domains.py` (wired
into the deploy flow above) checks this automatically and fails loudly instead
of letting it happen silently again — add any new domain to the `--domain`
flags in the README deploy block when it's added to the project.

Payloads remain on GitHub Pages (`https://gaurav-gandhi-2411.github.io/mindmeld-payloads/`).
The Vercel app fetches them from there; CORS is confirmed open on the Pages origin.

Web specifics: storage tries WASM sqlite (`sqflite_common_ffi_web`, IndexedDB) and falls
back to a `shared_preferences`-backed store on older browsers so the app never fails to
render; ads/IAP are force-disabled on web (`*EnabledEffective` getters); share uses the Web
Share API with clipboard fallback. Rewarded web ads via Google's Ad Placement API are a
Phase 4 item (`docs/web-monetization.md`).

### Performance budgets (playwarmer.vercel.app)

Per-product numeric performance budgets (rule 15e). Re-measured 2026-07-30 against the live,
`--wasm`-primary production build — the 2026-07-12 baseline this section previously cited
(`reports/performance-baseline-2026-07-12.md`) predates WASM adoption and no longer describes
what's actually served; kept for historical reference only, not as the current budget basis.

| Budget | Value | Measured (2026-07-30, live) |
|---|---|---|
| Initial download (own-domain: `main.dart.wasm` + `flutter_bootstrap.js`) | ≤ 3000 KB | ~2745 KB (2,803,451 + 10,248 bytes, uncompressed — `content-encoding` absent on the wasm response) |
| FCP | ≤ 1800 ms | 992 ms |
| TBT | ≤ 200 ms | 26 ms (`reports/lighthouse-playwarmer-launch1-verified.report.json`, latest reliable reading) |
| CLS | ≤ 0.1 | 0 |

**LCP is intentionally not budgeted.** Confirmed empirically (2026-07-30, live
`PerformanceObserver`/`performance.getEntriesByType('largest-contentful-paint')` against
production): zero LCP entries ever fire on this page. This isn't a measurement gap — a
CanvasKit-rendered app has no traditional "largest contentful DOM element" for the Paint Timing
API to key off (matches Lighthouse's own `NO_LCP` Lantern error on this app, previously
documented here). FCP is the tracked load-speed proxy instead. CanvasKit/RevenueCat CDN assets
(~1.6 MB, gstatic/jsdelivr, likely cross-site cached) are
tracked separately, not counted against the own-domain bundle budget.

## Results (honest numbers)

- **Payload sizes (gzipped):** en 774–778 KB/day (target < 1.5 MB); hi-en 153–154 KB/day
  (target < 400 KB). Measured over the published 2026-10-31..11-30 files
  (`mindmeld-payloads` @ `35cd2d2`).
- **Vocab (the payload's `n`):** en 54,878 words (wordfreq-derived, blocklist-filtered,
  capped per spec); hi-en 10,509 (curated romanized Hinglish seeds + top English words).
  Dates published before 2026-08-19 carry en 55,000 / hi-en 10,495, before the expanded
  blocklist.
- **Hinglish model:** hi-en uses
  [`gauravgandhi2411/hinglish-relatedness-sbert`](https://huggingface.co/gauravgandhi2411/hinglish-relatedness-sbert),
  fine-tuned from `l3cube-pune/indic-sentence-bert-nli`. Like-for-like held-out result
  (dim1 Spearman, 8 held-out secrets / 73 scenarios, same test set for both): base
  **0.435 → fine-tuned 0.704**, paired-CI [+0.130, +0.412]
  (`generator/evals/finetune/data/ship_decision_report_v3.md`). The first model shipped,
  `paraphrase-multilingual-MiniLM-L12-v2`, scored ~random on romanized Hinglish (it
  clusters by script, not meaning) and was replaced; its old figures are not comparable to
  the held-out number above. See `docs/known-limitations.md` for the residual gaps.
- **Tests:** generator 160/160; app 94/94 widget/unit; 2/2 emulator integration tests
  (full guess→feedback→win loop in both languages, bundled payloads).

## Repo layout

```
generator/   Python: vocab build, embeddings, payload emit, eval fixtures (uv project)
  vocab/     en.txt (generated), hinglish.txt (curated seed), profanity lists, secret schedules
  evals/     Hinglish ordering fixtures + runner (pytest-gated)
app/         Flutter: lib/core (config, codec, client, persistence), lib/features, lib/stubs
payloads/    generated output (gitignored except samples/)
```

## Developer reset hook

Browse to `https://playwarmer.vercel.app/?reset=1` to wipe all local
state (today's puzzle for both languages, streaks, stats, hints,
onboarding flag) and reload as a first-time user.

**Web only.** The `?reset=1` parameter is stripped from the URL after the
reset so normal navigation is not affected. In a normal session the
parameter is never present, so the hook cannot fire accidentally.

Useful for:
- Testing the onboarding flow end-to-end
- Simulating a first-time user on a device that has prior play history
- Verifying that win/loss screens survive app reopen

## Licence

Code: MIT (`LICENSE`). Models and word lists keep their own licences — notably
`generator/vocab/en.txt` is derived from wordfreq data and is CC-BY-SA-4.0. See
`THIRD_PARTY.md`.

## LLM usage

Built with Claude Code orchestrating executor/verifier subagents; architecture decisions,
spec, and curation reviewed by hand. Phase 2 (AdMob/RevenueCat, accounts, Devanagari
edition) is out of scope here — see spec.md.
