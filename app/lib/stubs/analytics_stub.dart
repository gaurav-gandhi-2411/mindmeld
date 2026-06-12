import 'package:mindmeld/core/persistence.dart';

/// Analytics event names used throughout the app.
class AnalyticsEvent {
  static const String guessMade = 'guess_made';
  static const String hintUsed = 'hint_used';
  static const String win = 'win';
  static const String shareTapped = 'share_tapped';

  /// Fired after every rewarded-ad gate pass (real or stub).
  ///
  /// Props: `{fallback: bool, lang: String?, day: String?}`
  static const String adWatched = 'ad_watched';
}

/// Analytics stub — logs events to the local SQLite ring buffer.
///
/// Phase 2: Replace [_export] with a real Firebase Analytics or PostHog call.
/// The [logEvent] interface stays the same — callers need not change.
class AnalyticsStub {
  const AnalyticsStub(this._persistence);

  final AppPersistence _persistence;

  /// Log [name] with optional [props] to the local ring buffer.
  ///
  /// Events: guess_made, hint_used, win, share_tapped.
  Future<void> logEvent(String name, [Map<String, dynamic>? props]) async {
    await _persistence.logEvent(name, props ?? {});
  }

  /// Export buffered events.
  ///
  /// Phase 2: flush to Firebase or remote analytics endpoint.
  /// Currently an explicit no-op stub — data stays in the ring buffer.
  Future<void> export() async {
    // Phase 2: iterate exportAnalyticsBuffer() and send to remote.
    // final events = await _persistence.exportAnalyticsBuffer();
    // await FirebaseAnalytics.instance.logMany(events);
  }
}
