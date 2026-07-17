/// Web-only helper for the `/join/{code}` deep link.
///
/// Imported via conditional import (see [extractJoinCode]/[clearJoinPath]
/// call sites in main.dart):
///   import 'deep_link_stub.dart'
///     if (dart.library.js_interop) 'deep_link_web.dart';
///
/// Uses package:web + a `dart.library.js_interop` condition (not dart:html /
/// `dart.library.html`) so it is selected under BOTH web targets — JS and
/// --wasm. See reset_web.dart for the incident writeup: the html-keyed
/// conditional silently stubbed this out on every wasm production build,
/// killing /join/{code} links on live.
library;

import 'package:web/web.dart' as web;

/// Returns the join code from a `/join/{code}` path, or null if the current
/// URL isn't a join deep link.
String? extractJoinCode() {
  final path = Uri.parse(web.window.location.href).path;
  final match = RegExp(r'^/join/([A-Za-z0-9]+)/?$').firstMatch(path);
  return match?.group(1);
}

/// Reset the URL to `/` without reloading, once the join link has been
/// handled (mirrors [stripResetParam] in reset_web.dart).
void clearJoinPath() {
  web.window.history.replaceState(null, '', '/');
}
