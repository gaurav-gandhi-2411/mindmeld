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

import 'dart:convert';
import 'dart:js_interop';
import 'dart:typed_data';

import 'package:web/web.dart' as web;

/// Returns true if the Web Share API is available in this browser.
bool webShareAvailable() {
  try {
    return web.window.navigator.canShare(web.ShareData());
  } catch (_) {
    return false;
  }
}

/// Invoke the Web Share API with [title], [text], and [url].
Future<bool> shareViaWebApi({
  required String title,
  required String text,
  required String url,
}) async {
  try {
    final data = web.ShareData(title: title, text: text, url: url);
    await web.window.navigator.share(data).toDart;
    return true;
  } catch (_) {
    return false;
  }
}

/// Download a PNG image by triggering a browser download.
Future<void> shareOrDownloadPng(Uint8List pngBytes) async {
  try {
    final base64Data = base64Encode(pngBytes);
    final dataUrl = 'data:image/png;base64,$base64Data';
    final anchor =
        web.window.document.createElement('a') as web.HTMLAnchorElement;
    anchor.href = dataUrl;
    anchor.download = 'mindmeld.png';
    web.window.document.body?.appendChild(anchor);
    anchor.click();
    web.window.document.body?.removeChild(anchor);
  } catch (_) {}
}
