/// Web share helper — used when compiling for web (dart:html is available).
///
/// Imported via conditional import in [win_screen.dart]:
///   import 'share_stub.dart'
///     if (dart.library.html) 'share_web.dart';
///
/// Uses the Web Share API (navigator.share / navigator.canShare) via
/// package:web. On desktop browsers where navigator.share is unavailable,
/// [webShareAvailable] returns false so the caller falls back to the
/// clipboard+dialog path.
library;

import 'dart:js_interop';

import 'package:web/web.dart' show ShareData, window;

/// Returns true if the Web Share API is available in this browser.
///
/// Uses [Navigator.canShare] which is the spec-approved capability check.
/// Desktop Chrome and most desktop browsers do not expose navigator.share;
/// mobile browsers (Chrome Android, Safari iOS) typically do.
bool webShareAvailable() {
  // canShare() returns false if the API is unsupported, which avoids the
  // share() tear-off restriction that affects external interop members.
  try {
    // Passing an empty ShareData checks API availability without specifying
    // actual data — any exception means the API is not supported.
    return window.navigator.canShare(ShareData());
  } catch (_) {
    return false;
  }
}

/// Invoke the Web Share API with [title], [text], and [url].
///
/// Returns true if the share sheet was successfully invoked, false if the API
/// is unavailable or the share was cancelled/rejected.
Future<bool> shareViaWebApi({
  required String title,
  required String text,
  required String url,
}) async {
  try {
    final data = ShareData(title: title, text: text, url: url);
    await window.navigator.share(data).toDart;
    return true;
  } catch (_) {
    // navigator.share throws DOMException on cancellation or if unsupported.
    return false;
  }
}
