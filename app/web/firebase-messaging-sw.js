// firebase-messaging-sw.js
//
// FCM Web background-message handler. See scripts/make_web_sw.py's
// _copy_firebase_messaging_sw() docstring and spec-phase6b.md's
// "Service worker integration (PRIME technical risk)" section for the full
// rationale; summary below.
//
// Why this is a SEPARATE service worker from flutter_service_worker.js:
// firebase_messaging_web's getToken() (called from Dart) has no supported
// way to point at a custom-named SW — the underlying Firebase JS SDK always
// registers a SW literally named "firebase-messaging-sw.js" at the site
// root, scoped to "/firebase-cloud-messaging-push-scope" (a synthetic path
// nobody ever navigates to). That registration only happens LAZILY — the
// first time a user opts in to notifications (win/loss screen) and
// getToken() is called — and NEVER during initial page load/boot. It
// therefore never competes with flutter_service_worker.js (scope "/",
// registered eagerly on every cold visit and gating app boot per
// SW_REGISTRATION_TIMEOUT_MILLIS in make_web_sw.py) for control of real
// page/asset traffic. This file carries ZERO caching logic by design — that
// stays exclusively in flutter_service_worker.js.
//
// Firebase JS SDK version 11.9.1 is pinned to match the version
// firebase_core_web already loads at runtime for the rest of this app (see
// `supportedFirebaseJsSdkVersion` in firebase_core_web's
// firebase_sdk_version.dart, resolved via app/pubspec.lock at the time this
// file was written). Keeping both in step avoids loading two different
// Firebase JS SDK majors/minors into the same origin.
importScripts('https://www.gstatic.com/firebasejs/11.9.1/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/11.9.1/firebase-messaging-compat.js');

// Templated by scripts/make_web_sw.py's _copy_firebase_messaging_sw() from
// the single source of truth, app/lib/analytics/firebase_web_options.dart.
// Do NOT hand-edit the object below — edit that Dart file instead and rerun
// the build. The placeholder marker is replaced with real config values
// (never committed here) so this SW's Firebase config can never drift from
// the Dart app's config.
const firebaseConfig = __FIREBASE_CONFIG__;

firebase.initializeApp(firebaseConfig);
const messaging = firebase.messaging();

// Show a system notification for a background (app not focused) FCM
// message. The deep link is stashed in the notification's `data.link` so
// `notificationclick` below can read it — the original payload is not
// available in the notificationclick event.
messaging.onBackgroundMessage((payload) => {
  const title = payload.notification?.title || 'Warmer';
  const body = payload.notification?.body || "Today's puzzle is live.";
  const link = payload.fcmOptions?.link || payload.data?.link || '/';

  self.registration.showNotification(title, {
    body,
    icon: '/icons/Icon-192.png',
    data: { link },
  });
});

// Tapping the system notification opens (or focuses) the deep link that was
// stashed on it above. Falls back to "/" if absent.
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const link = event.notification.data?.link || '/';
  event.waitUntil(clients.openWindow(link));
});
