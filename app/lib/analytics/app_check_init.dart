/// Firebase App Check activation for the web build — MONITOR mode only.
///
/// ## Scope
///
/// [ensureAppCheckActivated] activates App Check with the reCAPTCHA v3
/// provider on web ONLY (a deliberate no-op on native). Native (Android/iOS)
/// App Check wiring — Play Integrity fingerprint registration, App Attest
/// entitlements — is separate, unscoped work; this file carries zero native
/// blast radius.
///
/// ## Monitor vs. enforce
///
/// The Flutter SDK has no client-side "monitor mode" flag. `.activate()`
/// always just starts attaching App Check tokens to outgoing requests —
/// whether the backend actually REJECTS unverified requests (enforce) or
/// merely logs them (monitor / "metrics only") is a per-product toggle in
/// the Firebase Console (Project Settings -> App Check -> each product's
/// enforcement state), not something this client code controls or can
/// control. Enforcement must stay OFF for every product until a human
/// reviews the request-metrics breakdown (Verified/Outdated/Unknown-origin/
/// Malicious) for some period.
///
/// ## Idempotency
///
/// Mirrors [SocialService]'s `_applyFirestoreWebSettings` guard pattern (see
/// social_service.dart): both of Firebase's two independent init call sites
/// (main.dart's eager path, gated on analyticsEnabled; social_service.dart's
/// lazy path, triggered by the first explicit social/notification action)
/// call this helper right after Firebase becomes ready, and either one may
/// win the race — [_appCheckActivated] guards activation to exactly one
/// call, ever, regardless of which path gets there first.
library;

import 'package:firebase_app_check/firebase_app_check.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/foundation.dart' show debugPrint, kIsWeb, visibleForTesting;

/// Build-time reCAPTCHA v3 site key.
///
/// Empty default (mirrors [AppConfig.revenueCatApiKey]'s pattern for a
/// build-time-injected secret, see core/config.dart) keeps App Check
/// inactive until a production web deploy supplies the real key via
/// `--dart-define=APP_CHECK_RECAPTCHA_SITE_KEY=<key>`. The key must first be
/// created manually in the reCAPTCHA admin console and registered in the
/// Firebase Console (App Check -> Apps) — there is no real value to
/// hardcode a default to.
const String appCheckRecaptchaSiteKey = String.fromEnvironment(
  'APP_CHECK_RECAPTCHA_SITE_KEY',
);

/// Guards [ensureAppCheckActivated] to exactly one call, ever.
bool _appCheckActivated = false;

/// Pure decision predicate for whether App Check activation should proceed,
/// given the current Firebase readiness and site key — extracted so the
/// guard logic is unit-testable without a real Firebase app or a web target
/// (kIsWeb is a compile-time constant that is always false under `flutter
/// test`'s dart-vm runner, so [ensureAppCheckActivated] itself cannot
/// exercise its Firebase/site-key branches in a plain unit test).
@visibleForTesting
bool shouldActivateAppCheck({required bool firebaseReady, required String siteKey}) {
  return firebaseReady && siteKey.isNotEmpty;
}

/// Activates Firebase App Check (reCAPTCHA v3, web only) exactly once,
/// immediately after Firebase becomes ready. Safe — and required — to call
/// from BOTH of Firebase's independent init call sites; see this file's doc
/// comment for why.
///
/// No-ops (after a [debugPrint]) if:
///   - not running on web (native App Check is out of scope here),
///   - Firebase hasn't actually been initialised yet ([Firebase.apps] is
///     empty — defensive; callers are expected to call this only after
///     `Firebase.initializeApp()` resolves), or
///   - [appCheckRecaptchaSiteKey] is empty (real key not yet created).
///
/// Never throws — an App Check activation failure (offline, misconfigured
/// site key) must not block app startup or any social/notification action.
Future<void> ensureAppCheckActivated() async {
  if (!kIsWeb) return;
  if (_appCheckActivated) return;
  if (!shouldActivateAppCheck(
    firebaseReady: Firebase.apps.isNotEmpty,
    siteKey: appCheckRecaptchaSiteKey,
  )) {
    if (appCheckRecaptchaSiteKey.isEmpty) {
      debugPrint('AppCheck: skipped — APP_CHECK_RECAPTCHA_SITE_KEY not set.');
    }
    return;
  }
  _appCheckActivated = true;
  try {
    await FirebaseAppCheck.instance.activate(
      webProvider: ReCaptchaV3Provider(appCheckRecaptchaSiteKey),
    );
    debugPrint('AppCheck: activated (monitor-only until console enforcement is turned on).');
  } catch (e) {
    _appCheckActivated = false; // allow a later call site to retry
    debugPrint('AppCheck: activate() FAILED: $e');
  }
}
