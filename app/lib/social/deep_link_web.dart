/// Web-only helper for the `/join/{code}` deep link.
///
/// Imported via conditional import (see [extractJoinCode]/[clearJoinPath]
/// call sites in main.dart):
///   import 'deep_link_stub.dart'
///     if (dart.library.html) 'deep_link_web.dart';
library;

// ignore: avoid_web_libraries_in_flutter
import 'dart:html' as html;

/// Returns the join code from a `/join/{code}` path, or null if the current
/// URL isn't a join deep link.
String? extractJoinCode() {
  final path = Uri.parse(html.window.location.href).path;
  final match = RegExp(r'^/join/([A-Za-z0-9]+)/?$').firstMatch(path);
  return match?.group(1);
}

/// Reset the URL to `/` without reloading, once the join link has been
/// handled (mirrors [stripResetParam] in reset_web.dart).
void clearJoinPath() {
  html.window.history.replaceState(null, '', '/');
}
