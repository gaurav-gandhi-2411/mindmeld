/// Stub share helper — used on native (dart:io) platforms.
///
/// Imported via conditional import in [win_screen.dart]:
///   import 'share_stub.dart'
///     if (dart.library.js_interop) 'share_web.dart';
///
/// On native platforms the Web Share API is not available; this stub always
/// returns false so the caller falls back to the clipboard+dialog path.
library;

import 'dart:typed_data';

/// Returns true if the Web Share API is available in this browser.
///
/// Always false on native platforms.
bool webShareAvailable() => false;

/// Attempt to share [text] via the Web Share API.
///
/// On native platforms this is never called (guarded by [webShareAvailable]).
/// Returns true if the share sheet was invoked, false if unavailable.
Future<bool> shareViaWebApi({
  required String title,
  required String text,
  required String url,
}) async =>
    false;

/// Download or share a PNG on native — not implemented on native.
Future<void> shareOrDownloadPng(Uint8List pngBytes) async {}
