/// Firebase web configuration — PLACEHOLDER values.
///
/// ## How to fill in real values
///
/// 1. Go to the Firebase Console: https://console.firebase.google.com/
/// 2. Select (or create) the Mindmeld project.
/// 3. Project Settings → Your apps → Add app → Web.
/// 4. Register the app (e.g. "Mindmeld Web").
/// 5. Copy the config object that Firebase shows you.
/// 6. Replace EVERY 'PLACEHOLDER' value below with the real value.
///
/// DO NOT commit real Firebase credentials to a public repository.
/// Consider using environment substitution or Secret Manager for production.
///
/// ## Usage in main.dart
///
/// ```dart
/// if (kIsWeb && AppConfig.analyticsEnabled) {
///   await Firebase.initializeApp(options: firebaseWebOptions);
/// }
/// ```
///
/// On native platforms Firebase reads from google-services.json (Android) or
/// GoogleService-Info.plist (iOS) automatically — no [FirebaseOptions] needed.
library;

import 'package:firebase_core/firebase_core.dart';

/// Web [FirebaseOptions] — replace PLACEHOLDER values before deploying with
/// analyticsEnabled=true on web.
const FirebaseOptions firebaseWebOptions = FirebaseOptions(
  // From Firebase Console → Project Settings → Web app → SDK setup and config.
  apiKey: "AIzaSyAprUaMs4noRgYb3ydsBXJceAwY1bGcqFc",
  authDomain: "warmer-prod-260813.firebaseapp.com",
  projectId: "warmer-prod-260813",
  storageBucket: "warmer-prod-260813.firebasestorage.app",
  messagingSenderId: "419573145963",
  appId: "1:419573145963:web:330a4484ecc801a61dac2e"
  // measurementId intentionally omitted: Google Analytics isn't linked on the
  // new project yet (Console-only step, not available via CLI/API). Core
  // Auth/Firestore/FCM are unaffected; link Analytics later if needed.
);
