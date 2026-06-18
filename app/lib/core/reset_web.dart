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
