# Firebase Setup

## IMPORTANT: Replace the placeholder google-services.json

The file at `android/app/google-services.json` is a **placeholder** that satisfies
Gradle plugin validation during CI and local builds **without a real Firebase project**.
It contains dummy values and will NOT connect to any Firebase backend.

Before releasing to production, replace it with the real file:

1. Go to the [Firebase Console](https://console.firebase.google.com/).
2. Create a project named `mindmeld` (or use an existing one).
3. Add an Android app with package name `dev.gaurav.mindmeld`.
4. Download `google-services.json` and place it at `android/app/google-services.json`.
5. In Firebase Console > Crashlytics, click **Enable Crashlytics**.
6. In Firebase Console > Analytics, verify the app is reporting events.

## Enabling analytics in a build

```
flutter build apk --release --dart-define=MONETIZED=true
```

Or individually:

```
flutter build apk --release --dart-define=ANALYTICS_ENABLED=true
```

When `analyticsEnabled=false` (the default), zero Firebase SDK calls are made.
`Firebase.initializeApp()` is never called, and Crashlytics error hooks are not wired.
This keeps cold-start clean and lets the app run with the placeholder json.

## Web app setup

Firebase Analytics supports web. For a monetised web build:

1. In Firebase Console, go to **Project Settings → Your apps → Add app → Web**.
2. Register the web app (e.g. "Mindmeld Web").
3. Copy the **SDK setup and config** values that Firebase shows you.
4. Open `app/lib/analytics/firebase_web_options.dart` and replace every
   `'PLACEHOLDER'` with the real value from step 3:
   - `apiKey`
   - `appId`
   - `messagingSenderId`
   - `projectId`
   - `authDomain`
   - `storageBucket`
   - `measurementId` (the `G-XXXXXXXX` Analytics stream ID)

On web, `Firebase.initializeApp()` requires explicit `FirebaseOptions` because
there is no `google-services.json`. `main.dart` passes `firebaseWebOptions` when
`kIsWeb && analyticsEnabled`.

**Do not commit real Firebase credentials to a public repository.** Use environment
variable substitution or Secret Manager for CI/CD web deployments.

A default web build (no `--dart-define=ANALYTICS_ENABLED=true`) never touches
Firebase — the placeholder values are never read.

## Firebase Auth: authorized domains (required for every deploy domain)

Firebase Auth rejects sign-in attempts (including anonymous sign-in) from any
origin not in the project's **Authorized domains** list — Firebase Console →
Authentication → Settings → Authorized domains. Only `localhost` and the
default `<project-id>.firebaseapp.com` / `<project-id>.web.app` domains are
added automatically. **A custom domain (e.g. a Vercel production domain) is
never added for you** and must be added manually — or via:

### Automated guard (run on every deploy)

`scripts/check_authorized_domains.py` calls the same Identity Toolkit Admin
API endpoint below to read the *live* authorized-domains list and fails loudly
(non-zero exit, remediation command printed) if a required production domain
is missing. It's wired into the README's canonical deploy flow, right after
`check_web_plugin_registrant.py` — so a new deploy domain can no longer go
live without this being caught before `vercel deploy --prod`. Run it manually
with:

```bash
uv run python scripts/check_authorized_domains.py \
  --project-id mindmeld-c4bba \
  --domain playmindmeld.vercel.app
```

When adding a new production domain, add it to both this command's `--domain`
flags (in the README deploy block) and the project's authorized domains
(via the console or the `curl` below) — one without the other means either a
false failure or a silent gap.

```bash
gcloud auth login   # once, if not already authenticated
TOKEN=$(gcloud auth print-access-token)
curl -X PATCH \
  -H "Authorization: Bearer $TOKEN" \
  -H "x-goog-user-project: <project-id>" \
  -H "Content-Type: application/json" \
  "https://identitytoolkit.googleapis.com/admin/v2/projects/<project-id>/config?updateMask=authorizedDomains" \
  -d '{"authorizedDomains": ["localhost", "<project-id>.firebaseapp.com", "<project-id>.web.app", "<your-domain>"]}'
```

### Incident note (2026-07-07)

Creating a social group hung/failed live on `playmindmeld.vercel.app`:
`FirebaseAuth.instance.signInAnonymously()` threw
`[firebase_auth/channel-error] "...FirebaseAuthHostApi.signInAnonymously"`.
That error *looks* like a web-plugin-registration failure (a Pigeon platform
channel with no responder — normally means `FirebaseAuthWeb` never became
the active platform instance), and cost significant diagnosis time chasing
transport settings, App Check, service-worker interception, and package
version alignment — all correctly ruled out — before finding the real cause:
`playmindmeld.vercel.app` was simply never in `authorizedDomains`. It worked
flawlessly on `localhost` (auto-authorized) in both release and profile
builds, which was the tell — a registration or transport bug would have
failed on localhost too. Confirmed via
`GET https://identitytoolkit.googleapis.com/admin/v2/projects/<id>/config`,
fixed via the `PATCH` above, verified with a live headless reproduction.

**Lesson: if `signInAnonymously()` (or any `firebase_auth` call) fails ONLY on
a deployed custom domain and works on `localhost`, check authorized domains
before anything else.**
