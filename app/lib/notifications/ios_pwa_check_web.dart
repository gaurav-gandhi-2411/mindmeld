/// Web-only helper to detect "iOS Safari, not installed as a PWA" — the one
/// combination on which real web push cannot work (see spec-phase6b.md: web
/// push on iOS requires an installed PWA on iOS 16.4+).
///
/// Imported via conditional import (see [isIosPwaNotInstalled] call sites in
/// notification_service.dart):
///   import 'ios_pwa_check_stub.dart'
///     if (dart.library.html) 'ios_pwa_check_web.dart';
library;

import 'package:web/web.dart' as web;

/// True when the browser is iOS Safari/WebKit AND the app is not installed
/// as a standalone PWA. [NotificationService.optIn] must show the "Add to
/// Home Screen first" nudge instead of attempting `getToken()` in this case
/// — it fails silently on iOS 16.4+ otherwise.
bool isIosPwaNotInstalled() {
  try {
    final ua = web.window.navigator.userAgent;
    final isIos = ua.contains('iPhone') || ua.contains('iPad') || ua.contains('iPod');
    if (!isIos) return false;
    final standalone = web.window.matchMedia('(display-mode: standalone)').matches;
    return !standalone;
  } catch (_) {
    // Any interop failure (older browser, unavailable API) — never block
    // the opt-in flow on a detection error; treat as "not iOS" so the
    // caller proceeds to the normal getToken() path (which will itself
    // degrade gracefully on failure).
    return false;
  }
}
