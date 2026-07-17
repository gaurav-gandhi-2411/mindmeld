library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/core/memory_store.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/persistence.dart';
import 'package:mindmeld/features/onboarding/first_run.dart';
import 'package:mindmeld/main.dart';
import 'package:path/path.dart' as p;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

void main() {
  late Directory tmpDir;
  late String dbPath;

  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    AppPersistence.resetForTest();
    tmpDir = await Directory.systemTemp.createTemp('mindmeld_reset_');
    dbPath = p.join(tmpDir.path, 'reset_test.db');
    await AppPersistence.instance.init(dbPath: dbPath);
  });

  tearDown(() async {
    await AppPersistence.instance.close();
    AppPersistence.resetForTest();
    await tmpDir.delete(recursive: true);
  });

  test('reset hook: clearAll() wipes day states, stats, analytics', () async {
    // Populate DB.
    await AppPersistence.instance.saveDayState(DayState(
      date: '2026-06-12',
      lang: 'en',
      guesses: [
        Guess(word: 'water', rank: 79, similarity: 0.55, band: TemperatureBand.hot),
      ],
      hintsUsed: 0,
      won: false,
      gaveUp: false,
    ));
    await AppPersistence.instance.recordWin(
      lang: 'en',
      guessCount: 5,
      today: DateTime(2026, 6, 12),
    );
    await AppPersistence.instance.logEvent('puzzle_started', {'lang': 'en'});

    // Verify data exists.
    final statsBefore = await AppPersistence.instance.loadStats('en');
    expect(statsBefore.wins, equals(1));
    final dayBefore =
        await AppPersistence.instance.loadDayState('2026-06-12', 'en');
    expect(dayBefore, isNotNull);
    final eventsBefore = await AppPersistence.instance.exportAnalyticsBuffer();
    expect(eventsBefore, isNotEmpty);

    // clearAll.
    await AppPersistence.instance.clearAll();

    // Everything gone.
    final statsAfter = await AppPersistence.instance.loadStats('en');
    expect(statsAfter.wins, equals(0), reason: 'stats wiped by clearAll');
    final dayAfter =
        await AppPersistence.instance.loadDayState('2026-06-12', 'en');
    expect(dayAfter, isNull, reason: 'day state wiped by clearAll');
    final eventsAfter = await AppPersistence.instance.exportAnalyticsBuffer();
    expect(eventsAfter, isEmpty, reason: 'analytics wiped by clearAll');
  });

  test('reset hook: MemoryStore clearAll() wipes in-memory state', () async {
    // Close the SqliteStore opened in setUp before injecting the MemoryStore,
    // otherwise the DB file handle remains open and tearDown cannot delete tmpDir
    // on Windows (OS Error: file in use).
    await AppPersistence.instance.close();
    AppPersistence.resetForTest();
    final mem = MemoryStore();
    await AppPersistence.injectBackendForTest(mem);

    await AppPersistence.instance.saveDayState(DayState(
      date: '2026-06-12',
      lang: 'en',
      guesses: [],
      hintsUsed: 0,
      won: false,
      gaveUp: false,
    ));
    await AppPersistence.instance.clearAll();

    final day = await AppPersistence.instance.loadDayState('2026-06-12', 'en');
    expect(day, isNull, reason: 'MemoryStore clearAll wipes day state');
  });

  test(
    'reset hook: ?reset=1 pref-wipe list includes the onboarding first-run keys '
    '(first-session-hook wave)',
    () {
      // main.dart's kIsWeb-gated ?reset=1 handler can't be exercised directly
      // from a non-web test target, so this asserts on the extracted
      // kResetWipedPrefKeys constant it actually iterates — a genuinely new
      // profile after ?reset=1 requires BOTH of these keys to be wiped,
      // otherwise a "brand-new" cold-profile verification would incorrectly
      // resume/skip the onboarding puzzle instead of showing it fresh.
      expect(
        kResetWipedPrefKeys,
        containsAll(<String>[
          kOnboardingStateKey,
          kOnboardingGraduatedDateKey,
        ]),
        reason: 'reset hook must wipe both onboarding_puzzle_state and '
            'onboarding_graduated_date so ?reset=1 produces a genuinely '
            'brand-new profile',
      );
    },
  );
}
