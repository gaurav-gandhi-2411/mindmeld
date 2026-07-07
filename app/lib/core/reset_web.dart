/// Web-only helpers for the ?reset=1 developer hook.
library;

// ignore: avoid_web_libraries_in_flutter
import 'dart:html' as html;

/// Returns true if the current URL has ?reset=1.
bool hasResetParam() {
  final params = Uri.parse(html.window.location.href).queryParameters;
  return params['reset'] == '1';
}

/// Remove ?reset=1 from the URL without reloading the page.
void stripResetParam() {
  final current = Uri.parse(html.window.location.href);
  final cleaned = current.replace(queryParameters: {
    for (final e in current.queryParameters.entries)
      if (e.key != 'reset') e.key: e.value,
  });
  html.window.history.replaceState(null, '', cleaned.toString());
}

/// Returns true if the current URL has ?notif=1 — set on the click-action
/// URL of a delivered daily notification (phase 6b), so a real click-through
/// can be tracked via [AnalyticsEvent.notificationOpened].
bool hasNotifOpenParam() {
  final params = Uri.parse(html.window.location.href).queryParameters;
  return params['notif'] == '1';
}

/// Remove ?notif=1 from the URL without reloading the page (mirrors
/// [stripResetParam]).
void stripNotifOpenParam() {
  final current = Uri.parse(html.window.location.href);
  final cleaned = current.replace(queryParameters: {
    for (final e in current.queryParameters.entries)
      if (e.key != 'notif') e.key: e.value,
  });
  html.window.history.replaceState(null, '', cleaned.toString());
}
