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
  apiKey: "AIzaSyC999pJZXIAHE_kPQDNryTlcgekhoj92bk",
  authDomain: "mindmeld-c4bba.firebaseapp.com",
  projectId: "mindmeld-c4bba",
  storageBucket: "mindmeld-c4bba.firebasestorage.app",
  messagingSenderId: "376728425568",
  appId: "1:376728425568:web:3b309894293175630e9f05",
  measurementId: "G-RERQZ48NPX" // Analytics stream measurement ID (G-XXXXXXXX).
);
