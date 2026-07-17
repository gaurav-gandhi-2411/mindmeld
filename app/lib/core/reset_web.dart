/// Web-only helpers for the ?reset=1 developer hook.
///
/// Uses package:web (not dart:html) so this implementation compiles under
/// BOTH web targets — JS (DDC/dart2js) and WebAssembly (--wasm). The
/// conditional import in main.dart keys on `dart.library.js_interop` for the
/// same reason: `dart.library.html` is FALSE under --wasm, which made every
/// production build since the launch-1 wasm adoption silently select the
/// no-op stub — ?reset=1 and ?notif=1 were dead on live while every DDC-run
/// test kept passing. Found live during the first-session-hook wave's
/// cold-profile verification.
library;

import 'package:web/web.dart' as web;

/// Returns true if the current URL has ?reset=1.
bool hasResetParam() {
  final params = Uri.parse(web.window.location.href).queryParameters;
  return params['reset'] == '1';
}

/// Remove ?reset=1 from the URL without reloading the page.
void stripResetParam() {
  final current = Uri.parse(web.window.location.href);
  final cleaned = current.replace(queryParameters: {
    for (final e in current.queryParameters.entries)
      if (e.key != 'reset') e.key: e.value,
  });
  web.window.history.replaceState(null, '', cleaned.toString());
}

/// Returns true if the current URL has ?notif=1 — set on the click-action
/// URL of a delivered daily notification (phase 6b), so a real click-through
/// can be tracked via [AnalyticsEvent.notificationOpened].
bool hasNotifOpenParam() {
  final params = Uri.parse(web.window.location.href).queryParameters;
  return params['notif'] == '1';
}

/// Remove ?notif=1 from the URL without reloading the page (mirrors
/// [stripResetParam]).
void stripNotifOpenParam() {
  final current = Uri.parse(web.window.location.href);
  final cleaned = current.replace(queryParameters: {
    for (final e in current.queryParameters.entries)
      if (e.key != 'notif') e.key: e.value,
  });
  web.window.history.replaceState(null, '', cleaned.toString());
}
