# Clean-break migration: mindmeld-c4bba → warmer-prod-260813

**Status (corrected 2026-11-01): data + frontend cutover complete (2026-08-14); two gaps found.**
The live app (`playwarmer.vercel.app`) points at `warmer-prod-260813` (verified from the deployed
bundle). Firestore data and Auth users were imported. Corrections to the earlier "complete" status:
- `mindmeld-c4bba` is NOT deleted: it is ACTIVE with billing disabled (it was undeleted after the
  2026-08 GCP teardown sweep, see the global 55b rule). Decommission is tracked in
  `docs/spec-phase-b.md` P5.
- `firestore.rules` was never deployed to `warmer-prod-260813` (no rules release existed on
  2026-11-01), so client Firestore access was denied. Step 1a below was missing from this runbook.

This file is kept as reference for the pattern — the bootstrap-gap section below in particular
applies to any future clean-worktree build of this app, not just this one migration.

Target billing account: `01285B-91E4CB-70AD7E`. This is the highest-touch migration of the five
but, per the 2026-08-13 investigation, carries no unresolved data risk — the SCRYPT signer key
needed to migrate passwords without forcing resets was confirmed retrievable from the Firebase
console (it is deliberately NOT stored in this file; it was redacted 2026-11-01). Confirmed via live checks: no Secret Manager, no Cloud Functions, no Cloud Storage buckets
in use on the old project — this is a pure Firestore + Auth + Hosting + FCM app, which keeps the
migration surface small.

## 0. Prerequisites (once quota clears)

```
gcloud projects create warmer-prod-260813 --name="Warmer"
gcloud billing projects link warmer-prod-260813 --billing-account=01285B-91E4CB-70AD7E
firebase projects:addfirebase warmer-prod-260813
```
Grant Owner via Console. In Firebase Console (new project): enable Authentication (Email/Password
+ Anonymous, matching old project's `signIn.anonymous.enabled: true`), enable Firestore (region
**must** be `asia-south1` to match the old project — Firestore location is immutable per-project,
so get this right on first create), enable Cloud Messaging.

## 1. Firestore export/import (standard GCP mechanic, low risk — but see the note below)

**Capture-before-unlink means LOCAL DISK, not a bucket the same project owns.** Learned the hard
way on 2026-08-13: exporting to `gs://mindmeld-c4bba-migration-export` (a bucket owned by
`mindmeld-c4bba` itself) and then unlinking billing left the export completely stranded — a
billing-disabled project cannot serve ANY GCS request against its own buckets, including a direct
cross-project `firestore import` pointed at it. This is a hard infrastructure block, not a
permissions issue; no workaround exists short of briefly relinking the project (which costs a slot
at cap). Do the local-disk hop BEFORE unlinking, every time:
```
gcloud firestore export gs://mindmeld-c4bba-migration-export --project=mindmeld-c4bba
gcloud storage cp -r gs://mindmeld-c4bba-migration-export/<export-folder> ./firestore-export-local/
```
Verify the local copy (file count, byte sizes, AND actual readable content — grep the raw export
files for known real values, don't just trust a byte count) before unlinking anything. Only then:
```
gcloud storage buckets create gs://warmer-prod-260813-migration-import \
  --project=warmer-prod-260813 --location=asia-south1
gcloud storage cp -r ./firestore-export-local/<export-folder> \
  gs://warmer-prod-260813-migration-import/<export-folder>
gcloud firestore import gs://warmer-prod-260813-migration-import/<export-folder> \
  --project=warmer-prod-260813
```
Note: Firestore's import command requires the `.overall_export_metadata` file's basename to match
its containing GCS folder name exactly — if re-uploading under a renamed folder, keep them in sync
or the import fails with a confusing `NOT_FOUND`.

Verify by querying specific known documents directly (e.g. a known UID's user doc, a known game
result) via the Firestore REST API against the new project — not just document counts, and not
just that the import command exits 0.

## 1a. Deploy Firestore security rules to the new project (was missing — added 2026-11-01)

A new Firestore database has no rules release, which denies every client read/write: the app
loads, but social features and notification sign-up fail silently. Run the emulator suite first
(`firebase-tests/`), then:
```
firebase deploy --only firestore:rules --project warmer-prod-260813
```
Verify via the Rules API that a `cloud.firestore` release exists and its ruleset matches the
repo's `firestore.rules`, and that an unauthenticated write is denied.

## 2. Firebase Auth export/import — SCRYPT params confirmed live, 2026-08-13

```
firebase auth:export accounts.json --project mindmeld-c4bba --format=JSON
firebase auth:import accounts.json --project warmer-prod-260813 \
  --hash-algo=SCRYPT \
  --hash-key="<REDACTED: read from Firebase console > Authentication > Users > ⋮ > Password hash parameters>" \
  --salt-separator="Bw==" \
  --rounds=8 \
  --mem-cost=14
```
These four values (`hash-key`, `salt-separator`, `rounds`, `mem-cost`) must match the OLD
project's `hashConfig` exactly. Read them from the Firebase console (Authentication > Users >
⋮ > Password hash parameters) at the moment you run the import, and never write the signer key
into a file, commit, or chat transcript. `accounts.json` contains password hashes —
delete it after a successful import, don't leave it sitting in the repo or scratchpad.

Verify: create a throwaway test account update or, better, have one real (consenting) account —
yourself — attempt a real login against the new project with the existing password. A parameter
mismatch fails silently at hash-comparison time (login just doesn't match), not at import time, so
import succeeding is not sufficient proof — only a real successful login proves the params were
right.

## 3. FCM reconfiguration (real but minor transition gap — not data loss)

New project = new Sender ID. Existing push-notification registrations on users' devices go stale
until each user's client re-registers, which happens automatically the next time they open the
app under the new Firebase config. No user action required, no data lost — just a silent gap in
push delivery for any user who doesn't reopen the app for a while after cutover. Consider a
one-time in-app banner/toast after cutover if zero silent gap matters for this product.

## 4. Frontend rebuild (Firebase web config is build-time-baked)

`playwarmer.vercel.app` bakes `apiKey`, `authDomain`, `projectId`, `storageBucket`,
`messagingSenderId`, `appId` from `app/lib/analytics/firebase_web_options.dart` — a Flutter/Dart
source file, not an env var, so this needs an actual rebuild, not a redeploy of an existing
artifact (unlike the Next.js/Vite frontends elsewhere in this migration, there's no way to reuse a
prior build and just flip a config value). Get the new config via:
```
firebase apps:create web "Warmer Web" --project warmer-prod-260813
firebase apps:sdkconfig WEB <app-id> --project warmer-prod-260813
```
`measurementId` (Analytics) won't be in that output unless Google Analytics is separately linked
to the project (Console-only step) — fine to leave unset, it doesn't gate Auth/Firestore/FCM.

Update the Dart file, then build and deploy via the repo's own `deploy-warmer.ps1` — **read the
bootstrap-gaps section below first**, all four of those will otherwise cost you a build cycle each
on a fresh checkout.

Add `playwarmer.vercel.app` (and `playmindmeld.vercel.app` if still live) to the new project's
`authorizedDomains` list in Firebase Auth settings — logins will fail with an unauthorized-domain
error otherwise, even with correct config. `deploy-warmer.ps1` has its own guard for this
(`scripts/check_authorized_domains.py`) — but make sure its `--project-id` argument points at the
new project, not whatever it was last pointed at.

## 4a. Bootstrap gaps on a fresh worktree/checkout — found the hard way, 2026-08-14

`deploy-warmer.ps1` assumes several pieces of local, gitignored state that a normal `git clone` or
a fresh `git worktree add` doesn't carry over. Each one costs a full build cycle (~80s+ for the
wasm compile alone) to discover if hit one at a time — check all four before running the script:

1. **`web-dist/.vercel/project.json` — the guard that checks for this runs BEFORE the step that
   creates the directory.** This is unsatisfiable on a truly fresh worktree by construction, not
   an edge case: `Invoke-Step "Guard: web-dist/ must already be linked..."` (checks
   `web-dist/.vercel/project.json`) runs before `Invoke-Step "Stage build into web-dist/"` (the
   step that actually does `New-Item -ItemType Directory` if `web-dist/` doesn't exist). Pre-empt
   it before running the script at all:
   ```powershell
   New-Item -ItemType Directory -Path web-dist -Force
   cd web-dist
   npx vercel link --yes --project=playwarmer
   cd ..
   ```
2. **`firebase-tests/node_modules` — needed by the post-deploy smoke check (`smoke_check.js`), the
   very LAST step in the script.** Not hit until everything else has already run, so a missing
   install here wastes the most work if caught late. Run `npm ci` in `firebase-tests/` before
   starting — not `npm install`, unless the lockfile itself has drifted (see the fsevents fix,
   `firebase-tests/package-lock.json`, PR #16) in which case `npm install` is the right call to
   regenerate it, followed by committing the result.
3. **Flutter version: 3.44.2, exactly — not "latest."** `flutter build web --wasm` with a newer
   Flutter (3.47.0 tested) crashes the dart2wasm compiler on `cloud_firestore_web-4.4.12`
   (`Null check operator used on a null value` in `Translator.translateStorageType`) — a real
   compiler incompatibility, not a config problem. `pubspec.lock` only pins a floor
   (`flutter: ">=3.44.0"`), but `.github/workflows/e2e-web.yml` pins the exact version that's
   proven to work (`flutter-version: '3.44.2'`) and its `e2e-web-wasm` job runs the identical
   `flutter build web --release --no-web-resources-cdn --wasm` command in CI — confirm that job is
   still green on `main` before trusting 3.44.2 is still current, don't just trust this note.
4. **PATH is session-scoped.** Installing Flutter doesn't help the current PowerShell window if it
   was already open — `flutter` needs to resolve on PATH in the *same* window `deploy-warmer.ps1`
   runs in. Open a fresh terminal after installing/switching Flutter versions, don't reuse one that
   predates the PATH change.

## 5. Verify before cutover

Real signup flow AND real login-with-existing-password flow against the new project, a real
Firestore read/write from an authenticated session, and a real push notification delivered to a
test device re-registered under the new config. Only then decommission `mindmeld-c4bba` — and
delete `accounts.json` and the two migration GCS buckets first (they contain password hash
material and full user data respectively).
