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
