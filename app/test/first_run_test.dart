/// Unit tests for [resolveOnboardingGate] (first-session-hook wave) — pure
/// logic + prefs, no widget tree needed. Covers every branch in the
/// resolution order documented on first_run.dart: done / started / legacy
/// pref grandfather / stats grandfather / genuinely new.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/core/memory_store.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/persistence.dart';
import 'package:mindmeld/features/onboarding/first_run.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() async {
    AppPersistence.resetForTest();
    await AppPersistence.injectBackendForTest(MemoryStore());
  });

  tearDown(() async {
    await AppPersistence.instance.close();
    AppPersistence.resetForTest();
  });

  test('genuinely new player: absent state, no legacy pref, no stats -> '
      'onboarding shown, started event fires, state written to started',
      () async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();

    final result = await resolveOnboardingGate(
      prefs: prefs,
      persistence: AppPersistence.instance,
    );

    expect(result.showOnboarding, isTrue);
    expect(result.fireStartedEvent, isTrue);
    expect(prefs.getString(kOnboardingStateKey), equals('started'));
  });

  test('started: resumes onboarding without re-firing the started event',
      () async {
    SharedPreferences.setMockInitialValues({
      kOnboardingStateKey: 'started',
    });
    final prefs = await SharedPreferences.getInstance();

    final result = await resolveOnboardingGate(
      prefs: prefs,
      persistence: AppPersistence.instance,
    );

    expect(result.showOnboarding, isTrue,
        reason: 'an interrupted onboarding must resume, never strand');
    expect(result.fireStartedEvent, isFalse,
        reason: 'onboarding_started must fire exactly once, not on every resume');
    expect(prefs.getString(kOnboardingStateKey), equals('started'),
        reason: 'resuming must not mutate the stored state');
  });

  test('done: normal app, no onboarding, no event', () async {
    SharedPreferences.setMockInitialValues({
      kOnboardingStateKey: 'done',
    });
    final prefs = await SharedPreferences.getInstance();

    final result = await resolveOnboardingGate(
      prefs: prefs,
      persistence: AppPersistence.instance,
    );

    expect(result.showOnboarding, isFalse);
    expect(result.fireStartedEvent, isFalse);
  });

  test(
    'grandfather via legacy onboarding_done pref: absent state + legacy pref '
    'true -> grandfathered to done, no onboarding shown',
    () async {
      SharedPreferences.setMockInitialValues({
        kLegacyOnboardingDonePref: true,
      });
      final prefs = await SharedPreferences.getInstance();

      final result = await resolveOnboardingGate(
        prefs: prefs,
        persistence: AppPersistence.instance,
      );

      expect(result.showOnboarding, isFalse,
          reason: 'a player who completed the OLD 4-page pager must never '
              'be re-shown the new onboarding puzzle');
      expect(result.fireStartedEvent, isFalse);
      expect(prefs.getString(kOnboardingStateKey), equals('done'),
          reason: 'the grandfather check must persist done so it is not '
              're-evaluated on every boot');
    },
  );

  test(
    'grandfather via EN stats: absent state, no legacy pref, en stats played '
    '> 0 -> grandfathered to done (migrated player, prefs lost, DB survived)',
    () async {
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      await AppPersistence.instance.recordWin(
        lang: 'en',
        guessCount: 4,
        today: DateTime(2026, 6, 1),
      );

      final result = await resolveOnboardingGate(
        prefs: prefs,
        persistence: AppPersistence.instance,
      );

      expect(result.showOnboarding, isFalse,
          reason: 'a migrated player with EN play history must not be '
              'shown onboarding just because their prefs were reset');
      expect(prefs.getString(kOnboardingStateKey), equals('done'));
    },
  );

  test(
    'grandfather via hi-en stats: absent state, no legacy pref, hi-en stats '
    'played > 0 -> grandfathered to done',
    () async {
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      await AppPersistence.instance.recordWin(
        lang: 'hi-en',
        guessCount: 6,
        today: DateTime(2026, 6, 1),
      );

      final result = await resolveOnboardingGate(
        prefs: prefs,
        persistence: AppPersistence.instance,
      );

      expect(result.showOnboarding, isFalse,
          reason: 'the hi-en stats check must independently trigger the '
              'grandfather path, not just en');
      expect(prefs.getString(kOnboardingStateKey), equals('done'));
    },
  );

  test('markOnboardingPuzzleDone writes done regardless of prior state',
      () async {
    SharedPreferences.setMockInitialValues({
      kOnboardingStateKey: 'started',
    });
    final prefs = await SharedPreferences.getInstance();

    await markOnboardingPuzzleDone(prefs);

    expect(prefs.getString(kOnboardingStateKey), equals('done'));
  });

  test('PlayerStats sanity: empty stats has played == 0 (grandfather base case)',
      () {
    expect(PlayerStats.empty.played, equals(0));
  });
}
