/// First-run gate for the onboarding puzzle (first-session-hook wave).
///
/// Pure logic + prefs — no widgets — so every branch is unit-testable without
/// pumping a widget tree. See spec-first-session-hook.md's "First-run state
/// edge cases" risk: the app's Mindmeld -> Warmer rename means prefs alone
/// are not a reliable signal for "has this player played before", so the
/// resolution order below grandfathers migrated players via their SQLite
/// stats before concluding they're genuinely new.
library;

import 'package:mindmeld/core/persistence.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Pref key holding the onboarding-puzzle first-run state: absent |
/// `started` | `done`.
const String kOnboardingStateKey = 'onboarding_puzzle_state';

/// Pref key set (to today's yyyy-MM-dd, win path only) when a player
/// graduates from onboarding into today's real daily — consumed by
/// puzzle_screen.dart's `_logPuzzleCompleted` to fire
/// `daily_completed_after_onboarding` and then cleared.
const String kOnboardingGraduatedDateKey = 'onboarding_graduated_date';

/// Legacy pref written by the old 4-page [OnboardingScreen] (kept only for
/// its Settings > "Replay onboarding" entry point now, see
/// onboarding_screen.dart). Still checked here so a player who completed
/// THAT flow before this wave shipped is grandfathered straight to `done`
/// rather than being re-shown the new onboarding puzzle.
const String kLegacyOnboardingDonePref = 'onboarding_done';

const String _kStoredStarted = 'started';
const String _kStoredDone = 'done';

/// Raw onboarding-puzzle first-run state, as stored under
/// [kOnboardingStateKey].
enum OnboardingPuzzleState {
  /// Never started — a genuinely new player, or one predating this wave.
  absent,

  /// Started but not yet finished (win/loss/skip) — resume, never strand.
  started,

  /// Finished (win, loss, or skip) — never show again.
  done,
}

Future<OnboardingPuzzleState> _readState(SharedPreferences prefs) async {
  switch (prefs.getString(kOnboardingStateKey)) {
    case _kStoredStarted:
      return OnboardingPuzzleState.started;
    case _kStoredDone:
      return OnboardingPuzzleState.done;
    default:
      return OnboardingPuzzleState.absent;
  }
}

Future<void> _writeState(
  SharedPreferences prefs,
  OnboardingPuzzleState state,
) {
  final value = switch (state) {
    OnboardingPuzzleState.started => _kStoredStarted,
    OnboardingPuzzleState.done => _kStoredDone,
    OnboardingPuzzleState.absent => null,
  };
  return value == null
      ? prefs.remove(kOnboardingStateKey)
      : prefs.setString(kOnboardingStateKey, value);
}

/// Result of [resolveOnboardingGate].
class OnboardingGateResult {
  const OnboardingGateResult({
    required this.showOnboarding,
    required this.fireStartedEvent,
  });

  /// Whether the app shell should route to the onboarding puzzle instead of
  /// the normal tabbed app.
  final bool showOnboarding;

  /// Whether `AnalyticsEvent.onboardingStarted` should fire — true exactly
  /// once, the first time a genuinely new player is routed into onboarding.
  /// False on every resume of an already-`started` onboarding.
  final bool fireStartedEvent;
}

/// Resolves the first-run gate on boot.
///
/// Resolution order:
///   1. `done`    -> normal app.
///   2. `started` -> resume onboarding (never strand mid-teach); does NOT
///                   re-fire `onboarding_started`.
///   3. absent, legacy `onboarding_done` pref = true
///                -> grandfather to `done`, normal app (a player who
///                   completed the OLD 4-page pager before this wave
///                   shipped).
///   4. absent, [persistence].loadStats has `played` > 0 for either
///      supported language
///                -> grandfather to `done`, normal app (a migrated player
///                   whose prefs were lost across the rename but whose
///                   SQLite DB survived).
///   5. otherwise -> genuinely new; write `started` and fire
///                   `onboarding_started` exactly once.
Future<OnboardingGateResult> resolveOnboardingGate({
  required SharedPreferences prefs,
  required AppPersistence persistence,
}) async {
  final state = await _readState(prefs);

  if (state == OnboardingPuzzleState.done) {
    return const OnboardingGateResult(
        showOnboarding: false, fireStartedEvent: false);
  }

  if (state == OnboardingPuzzleState.started) {
    return const OnboardingGateResult(
        showOnboarding: true, fireStartedEvent: false);
  }

  // state == absent — grandfather checks, in order.
  final legacyDone = prefs.getBool(kLegacyOnboardingDonePref) ?? false;
  if (legacyDone) {
    await _writeState(prefs, OnboardingPuzzleState.done);
    return const OnboardingGateResult(
        showOnboarding: false, fireStartedEvent: false);
  }

  final enStats = await persistence.loadStats('en');
  final hiEnStats = await persistence.loadStats('hi-en');
  if (enStats.played > 0 || hiEnStats.played > 0) {
    await _writeState(prefs, OnboardingPuzzleState.done);
    return const OnboardingGateResult(
        showOnboarding: false, fireStartedEvent: false);
  }

  // Genuinely new.
  await _writeState(prefs, OnboardingPuzzleState.started);
  return const OnboardingGateResult(
      showOnboarding: true, fireStartedEvent: true);
}

/// Marks the onboarding puzzle complete — called on win, loss, or skip, and
/// by the [AppOverrides.skipOnboarding] test bypass so downstream logic
/// (e.g. the `?reset=1` hook) always sees a consistent completed state.
Future<void> markOnboardingPuzzleDone(SharedPreferences prefs) =>
    _writeState(prefs, OnboardingPuzzleState.done);
