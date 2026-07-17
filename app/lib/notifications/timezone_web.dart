/// Web-only helper to read the browser's IANA timezone name via
/// `Intl.DateTimeFormat().resolvedOptions().timeZone`, using modern
/// `dart:js_interop` (not `dart:js`/`dart:html`).
///
/// Imported via conditional import (see [currentTimezone] call sites in
/// notification_service.dart):
///   import 'timezone_stub.dart'
///     if (dart.library.js_interop) 'timezone_web.dart';
library;

import 'dart:js_interop';

@JS('Intl.DateTimeFormat')
extension type _JSIntlDateTimeFormat._(JSObject _) implements JSObject {
  external factory _JSIntlDateTimeFormat();
  external _JSResolvedOptions resolvedOptions();
}

extension type _JSResolvedOptions._(JSObject _) implements JSObject {
  external String? get timeZone;
}

/// Returns the browser's IANA timezone name (e.g. "Asia/Kolkata"), or null on
/// any failure (unsupported/old browser, JS exception). Stored on the user's
/// profile doc for later per-timezone send bucketing (out of scope this phase
/// — see spec-phase6b.md).
String? currentTimezone() {
  try {
    return _JSIntlDateTimeFormat().resolvedOptions().timeZone;
  } catch (_) {
    return null;
  }
}
