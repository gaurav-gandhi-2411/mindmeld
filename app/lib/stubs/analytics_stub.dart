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
  static const String puzzleStarted = 'puzzle_started';
  static const String loss = 'loss';

  /// Fired on EVERY daily-puzzle terminal state (win, budget exhausted via a
  /// guess or a hint, or explicit give-up) — never fired for practice/pack
  /// mode. Added launch-1 wave so "% of DAU completing the daily puzzle"
  /// (PM header success metric) is a single GA4 event rather than a manual
  /// win-OR-loss union. Props: `{outcome: String}` where outcome is one of
  /// 'win' | 'loss_budget' | 'loss_hint_exhausted' | 'loss_gave_up'.
  static const String puzzleCompleted = 'puzzle_completed';
  static const String rivalOutcome = 'rival_outcome';
  static const String returningPlayer = 'returning_player';

  /// Fired when a player grants browser notification permission via the
  /// win/loss-screen opt-in card or the Settings toggle (phase 6b).
  static const String notificationPermissionGranted = 'notification_permission_granted';

  /// Fired when a player dismisses the win/loss-screen opt-in card without
  /// opting in (phase 6b) — never shown again after this per spec's "never nag".
  static const String notificationOptInDismissed = 'notification_opt_in_dismissed';

  /// Fired on cold boot when the app is opened via a `?notif=1` deep link —
  /// i.e. a real click-through from a delivered daily notification (phase 6b).
  static const String notificationOpened = 'notification_opened';
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
