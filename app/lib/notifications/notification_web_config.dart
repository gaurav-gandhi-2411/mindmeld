/// FCM Web Push VAPID key — PLACEHOLDER value.
///
/// ## How to fill in the real value
///
/// 1. Go to the Firebase Console: https://console.firebase.google.com/
/// 2. Select the Mindmeld project.
/// 3. Project Settings → Cloud Messaging → Web configuration → Web Push
///    certificates → generate key pair.
/// 4. Copy the "Key pair" value shown there.
/// 5. Replace the PLACEHOLDER value below with the real key.
///
/// This value is sent to the browser (not a server secret), but keep it
/// accurate — a stale/placeholder key makes [FirebaseMessaging.getToken]
/// fail on web.
///
/// ## Usage
///
/// [NotificationService.optIn] checks this value against `'PLACEHOLDER'` and
/// skips [FirebaseMessaging.getToken] gracefully (returns
/// `OptInResult.offlineOrError`, logs via `debugPrint`) when it hasn't been
/// replaced yet — mirrors how main.dart checks
/// `firebaseWebOptions.apiKey != 'PLACEHOLDER'` before initialising Firebase
/// on web (see analytics/firebase_web_options.dart).
library;

/// Web Push VAPID public key — replace PLACEHOLDER before relying on real
/// push delivery. See file doc comment for where to get the real value.
const String notificationVapidKey = 'BJgVsKF15CiDdvkxWuYe2BeOXIXUX0ejf5Oft6r8J2XOo_vyPrQWs48w5bQYX9WG4POyasj50hXjoxWhwOPI34c';
