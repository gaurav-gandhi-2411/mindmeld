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
