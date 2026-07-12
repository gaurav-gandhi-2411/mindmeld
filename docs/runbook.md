# Runbook — Warmer (playwarmer.vercel.app)

Operational reference for deploy, rollback, and the recurring gotchas this project has
actually hit in production. Written as part of the launch-1 wave (`/launch-check` gate 7).
Cross-references `docs/known-limitations.md` (accepted trade-offs) and PLAN.md (full
session-by-session history) rather than duplicating them.

## Deploy

Canonical flow: `./deploy-warmer.ps1` (repo root) — build (`--wasm`,
`--dart-define=ANALYTICS_ENABLED=true`) → guard scripts (web-plugin registrant, Firebase
Auth authorized domains) → generate service worker → **guard: verify `web-dist/` is linked
to the real `playwarmer` Vercel project, not a stray one (see Gotcha 1 below)** → stage into
`web-dist/` → `vercel deploy --prod` → post-deploy smoke check (`firebase-tests/smoke_check.js`).
Mirrors README.md's "Web / PWA" section exactly — keep both in sync if either changes.

A deploy is not "done" until the smoke check passes (200, Flutter engine actually booted,
zero pageerror/requestfailed). If it fails: check `vercel inspect <url>` / build logs first;
re-deploy or roll back (below) before doing anything else.

## Rollback

```powershell
npx vercel ls playwarmer              # find the deployment URL to roll back to
npx vercel rollback <url> --yes        # promote it back to production
node firebase-tests/smoke_check.js https://playwarmer.vercel.app/   # verify
```

**Live-verified this wave** (2026-07-12, real production rollback, not simulated): deployed
a real change (the `--wasm` + analytics-enabled build) as a new production deployment,
rolled back to the prior deployment (confirmed via `flutter_bootstrap.js` referencing only
`main.dart.js`, no `.wasm` — i.e. genuinely serving the OLD build, not just returning 200),
smoke-checked clean, then rolled forward back to the new deployment (confirmed
`main.dart.wasm` present again), smoke-checked clean again. `vercel rollback` promotes an
existing deployment back to production in seconds — no rebuild needed, since Vercel keeps
prior deployments addressable by URL indefinitely (until manually removed).

**To roll forward again after a rollback**: same command, pointing at the deployment you
want restored (`vercel rollback <newer-url> --yes`) — "rollback" is really "promote," it
works in either direction.

## Gotchas

### 1. `vercel deploy --prod` from an unlinked directory silently deploys the WRONG project

**Recurred during this very wave.** `web-dist/.vercel/` is gitignored (staging dir only), so
the project link never survives a deleted `web-dist/` or a fresh clone. Running
`vercel deploy --prod` from a directory with no `.vercel/project.json` does **not error** —
it silently auto-creates and deploys to a brand-new project named after the directory
(this wave: got a stray "web-dist" project; a prior session got a stray "app" project the
same way — see PLAN.md's aesthetic-pass gotchas). The real `playwarmer` project is left
completely untouched, and every downstream guard/smoke-check still reports success because
they check the static `playwarmer.vercel.app` domain, which just keeps serving whatever it
was already serving.

**Fixed mechanically this wave**: `deploy-warmer.ps1` now has an explicit guard step that
reads `web-dist/.vercel/project.json` and throws loudly if it's missing or points at
anything other than `projectName: "playwarmer"`, before touching Vercel at all. One-time fix
if it trips: `cd web-dist && npx vercel link --yes --project=playwarmer`.

**Related trap**: the staging step that refreshes `web-dist/`'s contents must NOT wipe
`.vercel/` in the process — a bare `Remove-Item (Join-Path $webDist '*') -Recurse -Force`
deletes hidden directories too (verified empirically), silently undoing the link on every
single deploy. `deploy-warmer.ps1`'s staging step explicitly excludes `.vercel/` from the
wipe.

**Always sanity-check** `npx vercel ls playwarmer` after any deploy you didn't run through
`deploy-warmer.ps1` — confirm the deployment you expect actually shows up under the
`playwarmer` project, not a stray one.

### 2. Vercel deployment-protection (SSO gate) blocks anonymous access to non-custom-domain URLs

Any ad-hoc preview/sandbox Vercel project (or an aliased-but-unregistered `*.vercel.app`
name) 302-redirects anonymous visitors to `vercel.com/sso-api` — this affects automated
tools (Lighthouse, puppeteer, `curl`) hitting a URL before it's registered as a project
Domain. Symptom: a smoke check reports "did not boot" even though the app is fine — the
tool never actually reached the app, it hit Vercel's own login-gate HTML.

**Fix for the real production domain**: `vercel domains add <domain>` (not
`vercel alias set`) registers it as a first-class project Domain, which IS exempt from the
SSO gate — already done for `playwarmer.vercel.app` and `playmindmeld.vercel.app`.

**Fix for a throwaway sandbox project** (e.g. a one-off renderer/perf experiment): don't
fight the protection setting — generate a temporary protection-bypass share link instead
(the Vercel MCP tool `get_access_to_vercel_url` does this; 23-hour expiry). Confirmed
working this wave for both puppeteer and `curl` (cookie-based bypass — a single-URL fetch
like Lighthouse's initial navigation works fine since the redirect-then-cookie-then-load
happens within one page load).

**Delete throwaway sandbox projects when done** (`npx vercel remove <project> --yes`) —
don't leave stray experiment projects lying around in the account.

### 3. Firestore collection-group query needs a one-time console index

`SocialService.deleteMyData()`'s results-cleanup step needs a composite index created once
in the Firebase console on first production use — see `docs/known-limitations.md` entry 12
for the full detail and manual-action owner. Not a code/rules fix.

### 4. FCM / notifications

- Web push requires the PWA be installed to the home screen on iOS Safari (Apple platform
  constraint, not fixable app-side) — `docs/known-limitations.md` entry 4.
- `scripts/send_daily_notification.py` is the daily-notification sender, wired into
  `.github/workflows/daily-notification.yml` — check that workflow's run history first if
  notifications stop arriving before assuming an app-side bug.
- `app/web/firebase-messaging-sw.js` is templated at build time by
  `scripts/make_web_sw.py` with the real Firebase web config — if notifications silently
  fail after a deploy, confirm this templating step actually ran (it's part of
  `deploy-warmer.ps1`, not optional).

### 5. Payload repo sync (`mindmeld-payloads`)

Payloads publish to a **separate sibling repo** (`mindmeld-payloads`, GitHub Pages), not
this one — see README.md's "Payload hosting" section for the exact `uv run publish`
commands. Key trap already documented in PLAN.md: `build-packs.py` does NOT get invoked by
`publish` automatically — pack payloads and daily payloads are two separate build+publish
steps; running only `--packs <one-pack>` instead of `--packs all` silently drops every other
pack from the published manifest. Always verify the full manifest after any partial pack
publish.

### 6. Analytics is now enabled in production (launch-1 wave) — was silently off before

`AppConfig.analyticsEnabled` gates ALL Firebase Analytics (custom events + Firebase's own
automatic session/retention events) — every previous production deploy omitted
`--dart-define=ANALYTICS_ENABLED=true`, so **zero analytics data was ever collected before
this wave**, despite the app being fully wired for it (see `docs/known-limitations.md` and
PLAN.md's launch-1 entry for the full story). `deploy-warmer.ps1`/README now always pass
this flag — if a future manual deploy omits it, analytics silently goes dark again with no
error anywhere. If D1-retention/completion-rate numbers ever look suspiciously flat or
absent in the Firebase console, check this flag was actually set on the deployed build
before assuming a data or instrumentation bug.

### 7. Firebase console checks (where to look)

- **Auth**: `mindmeld-c4bba` project → Authentication → Users (anonymous identities) and
  Settings → Authorized domains (guarded automatically by
  `scripts/check_authorized_domains.py` on every deploy — should never actually need a
  manual check unless that guard is bypassed).
- **Firestore**: Data tab for spot-checking `users/`/`groups/`/`codes/`/`results/`
  collections; Rules tab should match the committed `firestore.rules` exactly (no
  console-only edits — if it doesn't match, someone hand-edited it in the console, which
  should never happen).
- **Analytics/GA4**: DebugView (real-time, useful right after a deploy to confirm events
  are actually arriving) and the standard retention/engagement reports (populate on a
  ~24-48h delay, not real-time).
- **App Check**: metrics-only mode today (see `docs/known-limitations.md` entry 11) — the
  Apps tab shows verified-vs-unverified request counts even in monitor mode, useful for
  confirming the reCAPTCHA site key (once registered) is actually being exercised before
  flipping to Enforced.
- **Crashlytics**: only receives data when `analyticsEnabled` is true (same gate as
  Analytics — see Gotcha 6).
