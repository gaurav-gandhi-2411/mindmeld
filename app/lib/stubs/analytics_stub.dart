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

  // ---------------------------------------------------------------------------
  // First-session hook (onboarding puzzle) — see spec-first-session-hook.md.
  // ---------------------------------------------------------------------------

  /// Fired exactly once, when a genuinely new player is routed into the
  /// first-session onboarding puzzle. Never re-fired when an already-started
  /// onboarding resumes on a later boot. Props: `{lang: String}`.
  static const String onboardingStarted = 'onboarding_started';

  /// Fired on the player's FIRST guess of the onboarding puzzle only (not
  /// every guess — that's the generic [guessMade] above).
  /// Props: `{lang: String, rank: int, band: String}`.
  static const String onboardingFirstGuess = 'onboarding_first_guess';

  /// Fired when the onboarding puzzle is won.
  /// Props: `{lang: String, guesses_used: int}`.
  static const String onboardingWon = 'onboarding_won';

  /// Fired when the app is backgrounded/hidden while the onboarding puzzle
  /// is still unfinished. May fire more than once across sessions if the
  /// player backgrounds repeatedly without finishing — GA4 funnel analysis
  /// counts distinct users, not raw event count.
  /// Props: `{lang: String, guess_count: int}`.
  static const String onboardingAbandoned = 'onboarding_abandoned';

  /// Fired when the player taps "Skip to today's puzzle" during onboarding.
  /// Props: `{lang: String, guess_count: int}`.
  static const String onboardingSkipped = 'onboarding_skipped';

  /// Fired when the player leaves the onboarding graduation view for today's
  /// real daily (via the win or loss/skip CTA).
  /// Props: `{lang: String, from: String}` where `from` is one of
  /// 'win' | 'loss'. (A skip fires [onboardingSkipped] instead of this one —
  /// skipping is graduation without ceremony, see onboarding_flow.dart.)
  static const String graduatedToDaily = 'graduated_to_daily';

  /// Fired when a player who graduated from onboarding via a WIN that same
  /// day (tracked via the `onboarding_graduated_date` pref, see
  /// features/onboarding/first_run.dart) subsequently completes today's real
  /// daily. This closes the first-session funnel: onboarding_started ->
  /// ... -> graduated_to_daily -> daily_completed_after_onboarding.
  /// Props: `{lang: String, outcome: String}` (same outcome vocabulary as
  /// [puzzleCompleted]).
  static const String dailyCompletedAfterOnboarding =
      'daily_completed_after_onboarding';
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
