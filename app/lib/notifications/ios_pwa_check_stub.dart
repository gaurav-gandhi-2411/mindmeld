/// Stub for non-web platforms: iOS-PWA detection is web-only. Native push is
/// out of scope for phase 6b, so this always reports "installed" (no nudge).
///
/// Imported via conditional import (see [isIosPwaNotInstalled] call sites in
/// notification_service.dart):
///   import 'ios_pwa_check_stub.dart'
///     if (dart.library.js_interop) 'ios_pwa_check_web.dart';
library;

/// Always false on native — the "Add to Home Screen" nudge is a web-only
/// concept this phase.
bool isIosPwaNotInstalled() => false;
