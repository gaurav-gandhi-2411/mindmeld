import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/persistence.dart';
import 'package:path/path.dart' as p;

import 'test_helpers.dart';

/// Re-open the test database in the same temp directory.
Future<AppPersistence> reopenDb(Directory tmpDir) async {
  AppPersistence.resetForTest();
  final dbPath = p.join(tmpDir.path, 'test.db');
  final db = AppPersistence.instance;
  await db.init(dbPath: dbPath);
  return db;
}

void main() {
  setUpAll(() {
    initSqfliteFfi();
  });

  // ---------------------------------------------------------------------------
  // Pure function tests — no database needed
  // ---------------------------------------------------------------------------
  group('updateStreak — pure function', () {
    final day0 = DateTime(2026, 6, 12);
    final day1 = DateTime(2026, 6, 13);
    final day2 = DateTime(2026, 6, 14);
    final day5 = DateTime(2026, 6, 17);

    test('first ever win: streak becomes 1', () {
      final result = updateStreak(
        lastWinDate: null,
        today: day0,
        currentStreak: 0,
        maxStreak: 0,
      );
      expect(result.currentStreak, equals(1));
      expect(result.maxStreak, equals(1));
    });

    test('consecutive day win increments streak', () {
      final result = updateStreak(
        lastWinDate: day0,
        today: day1,
        currentStreak: 1,
        maxStreak: 1,
      );
      expect(result.currentStreak, equals(2));
      expect(result.maxStreak, equals(2));
    });

    test('same-day win is idempotent', () {
      final result = updateStreak(
        lastWinDate: day0,
        today: day0,
        currentStreak: 3,
        maxStreak: 5,
      );
      expect(result.currentStreak, equals(3));
      expect(result.maxStreak, equals(5));
    });

    test('gap resets streak to 1', () {
      final result = updateStreak(
        lastWinDate: day0,
        today: day5,
        currentStreak: 10,
        maxStreak: 10,
      );
      expect(result.currentStreak, equals(1));
      // maxStreak is unchanged when new streak < max
      expect(result.maxStreak, equals(10));
    });

    test('streak grow updates maxStreak', () {
      final result = updateStreak(
        lastWinDate: day1,
        today: day2,
        currentStreak: 5,
        maxStreak: 5,
      );
      expect(result.currentStreak, equals(6));
      expect(result.maxStreak, equals(6));
    });

    test('multiple consecutive days build streak correctly', () {
      var lastWin = day0;
      int current = 0;
      int max = 0;

      for (int i = 1; i <= 7; i++) {
        final today = day0.add(Duration(days: i));
        final r = updateStreak(
          lastWinDate: lastWin,
          today: today,
          currentStreak: current,
          maxStreak: max,
        );
        current = r.currentStreak;
        max = r.maxStreak;
        lastWin = today;
      }

      expect(current, equals(7));
      expect(max, equals(7));
    });
  });

  // ---------------------------------------------------------------------------
  // Database integration tests
  // ---------------------------------------------------------------------------
  group('streak persistence across store re-instantiation', () {
    test('win recorded on day 1, re-open db, win on day 2 shows streak=2',
        () async {
      AppPersistence.resetForTest();
      final tmpDir = await Directory.systemTemp.createTemp('mindmeld_streak_');

      try {
        final dbPath = p.join(tmpDir.path, 'test.db');
        var db = AppPersistence.instance;
        await db.init(dbPath: dbPath);

        final day1 = DateTime(2026, 6, 12);
        final day2 = DateTime(2026, 6, 13);

        // Record day 1 win
        await db.recordWin(lang: 'en', guessCount: 5, today: day1);
        var stats = await db.loadStats('en');
        expect(stats.currentStreak, equals(1));

        // Close and re-open the database
        await db.close();
        db = await reopenDb(tmpDir);

        // Record day 2 win
        await db.recordWin(lang: 'en', guessCount: 8, today: day2);
        stats = await db.loadStats('en');
        expect(stats.currentStreak, equals(2));
        expect(stats.maxStreak, equals(2));
        expect(stats.wins, equals(2));
        expect(stats.played, equals(2));

        await db.close();
        AppPersistence.resetForTest();
      } finally {
        await tmpDir.delete(recursive: true);
      }
    });

    test('same-day win does not double-increment streak', () async {
      final (db, tmpDir) = await openTestDb();

      try {
        final day1 = DateTime(2026, 6, 12);

        await db.recordWin(lang: 'en', guessCount: 3, today: day1);
        // Simulate calling recordWin again on the same day
        await db.recordWin(lang: 'en', guessCount: 4, today: day1);

        final stats = await db.loadStats('en');
        // Streak should not double — streak stays at 1 for same-day.
        expect(stats.currentStreak, equals(1));
      } finally {
        await closeTestDb(db, tmpDir);
      }
    });

    test('gap resets streak; loss records played without win', () async {
      final (db, tmpDir) = await openTestDb();

      try {
        final day1 = DateTime(2026, 6, 12);
        final day5 = DateTime(2026, 6, 17);

        await db.recordWin(lang: 'en', guessCount: 5, today: day1);

        // Record a loss
        await db.recordLoss(lang: 'en');

        var stats = await db.loadStats('en');
        expect(stats.played, equals(2));
        expect(stats.wins, equals(1));
        expect(stats.currentStreak, equals(0)); // loss resets

        // Win on day 5 after the gap — streak restarts at 1
        await db.recordWin(lang: 'en', guessCount: 10, today: day5);
        stats = await db.loadStats('en');
        expect(stats.currentStreak, equals(1));
        expect(stats.maxStreak, equals(1));
      } finally {
        await closeTestDb(db, tmpDir);
      }
    });
  });

  // ---------------------------------------------------------------------------
  // Day state lang isolation
  // ---------------------------------------------------------------------------
  //
  // Regression for: integration test hi-en pass fails because the en win state
  // (won: true) written in the en pass was read back when the hi-en pass opened
  // the same database file and queried for the same date without a lang filter.
  //
  // day_state has a composite PRIMARY KEY (date, lang) so states for different
  // langs must be independent.  These tests enforce that contract explicitly.
  group('day state lang isolation', () {
    test('en and hi-en states are stored and loaded independently', () async {
      final (db, tmpDir) = await openTestDb();

      try {
        final enState = DayState(
          date: '2026-06-12',
          lang: 'en',
          guesses: [],
          hintsUsed: 0,
          won: true,
          gaveUp: false,
        );
        final hiEnState = DayState(
          date: '2026-06-12',
          lang: 'hi-en',
          guesses: [],
          hintsUsed: 0,
          won: false,
          gaveUp: false,
        );

        await db.saveDayState(enState);
        await db.saveDayState(hiEnState);

        final loadedEn = await db.loadDayState('2026-06-12', 'en');
        final loadedHiEn = await db.loadDayState('2026-06-12', 'hi-en');

        // en is won, hi-en is not — they must not share state.
        expect(loadedEn, isNotNull);
        expect(loadedEn!.won, isTrue,
            reason: 'en day state should be marked won');

        expect(loadedHiEn, isNotNull);
        expect(loadedHiEn!.won, isFalse,
            reason: 'hi-en day state must not inherit the en win');
      } finally {
        await closeTestDb(db, tmpDir);
      }
    });

    test('loading hi-en state returns null when only en state exists', () async {
      final (db, tmpDir) = await openTestDb();

      try {
        final enState = DayState(
          date: '2026-06-12',
          lang: 'en',
          guesses: [],
          hintsUsed: 0,
          won: true,
          gaveUp: false,
        );
        await db.saveDayState(enState);

        // hi-en was never saved — must return null, not the en row.
        final loadedHiEn = await db.loadDayState('2026-06-12', 'hi-en');
        expect(loadedHiEn, isNull,
            reason: 'hi-en query must return null when only en row exists; '
                'day_state keying by (date, lang) must prevent cross-lang bleed');
      } finally {
        await closeTestDb(db, tmpDir);
      }
    });
  });

  // ---------------------------------------------------------------------------
  // Day state persistence
  // ---------------------------------------------------------------------------
  group('day state persistence', () {
    test('save and load day state round-trips correctly', () async {
      final (db, tmpDir) = await openTestDb();

      try {
        final guess = Guess(
          word: 'water',
          rank: 79,
          similarity: 0.558,
          band: TemperatureBand.scorching,
        );
        final state = DayState(
          date: '2026-06-12',
          lang: 'en',
          guesses: [guess],
          hintsUsed: 1,
          won: false,
          gaveUp: false,
        );

        await db.saveDayState(state);
        final loaded = await db.loadDayState('2026-06-12', 'en');

        expect(loaded, isNotNull);
        expect(loaded!.guesses.length, equals(1));
        expect(loaded.guesses.first.word, equals('water'));
        expect(loaded.guesses.first.rank, equals(79));
        expect(loaded.hintsUsed, equals(1));
        expect(loaded.won, isFalse);
      } finally {
        await closeTestDb(db, tmpDir);
      }
    });
  });

  // ---------------------------------------------------------------------------
  // Passive streak reset (on Stats screen open)
  // ---------------------------------------------------------------------------
  group('applyPassiveStreakReset', () {
    test('gap > 1 day resets streak to 0 and persists', () async {
      final (db, tmpDir) = await openTestDb();
      try {
        final day1 = DateTime(2026, 6, 10);
        final day5 = DateTime(2026, 6, 15);
        await db.recordWin(lang: 'en', guessCount: 5, today: day1);

        final reset = await db.applyPassiveStreakReset(lang: 'en', today: day5);
        expect(reset.currentStreak, equals(0),
            reason: 'streak reset to 0 after gap');
        expect(reset.maxStreak, equals(1), reason: 'maxStreak unchanged');
        expect(reset.played, equals(1), reason: 'played count unchanged');
        expect(reset.wins, equals(1), reason: 'wins unchanged');

        // Confirm persisted to DB.
        final reloaded = await db.loadStats('en');
        expect(reloaded.currentStreak, equals(0),
            reason: 'persisted streak is 0');
      } finally {
        await closeTestDb(db, tmpDir);
      }
    });

    test('consecutive day (gap=1) does not reset streak', () async {
      final (db, tmpDir) = await openTestDb();
      try {
        final day1 = DateTime(2026, 6, 10);
        final day2 = DateTime(2026, 6, 11);
        await db.recordWin(lang: 'en', guessCount: 5, today: day1);

        final result =
            await db.applyPassiveStreakReset(lang: 'en', today: day2);
        expect(result.currentStreak, equals(1),
            reason: 'consecutive day preserves streak');
      } finally {
        await closeTestDb(db, tmpDir);
      }
    });

    test('same-day return (gap=0) does not reset streak', () async {
      final (db, tmpDir) = await openTestDb();
      try {
        final day1 = DateTime(2026, 6, 10);
        await db.recordWin(lang: 'en', guessCount: 5, today: day1);

        final result =
            await db.applyPassiveStreakReset(lang: 'en', today: day1);
        expect(result.currentStreak, equals(1),
            reason: 'same-day return preserves streak');
      } finally {
        await closeTestDb(db, tmpDir);
      }
    });

    test('already-zero streak is a no-op', () async {
      final (db, tmpDir) = await openTestDb();
      try {
        final day1 = DateTime(2026, 6, 10);
        final day5 = DateTime(2026, 6, 15);
        await db.recordWin(lang: 'en', guessCount: 5, today: day1);
        await db.recordLoss(lang: 'en');

        final result =
            await db.applyPassiveStreakReset(lang: 'en', today: day5);
        expect(result.currentStreak, equals(0),
            reason: 'already 0 — no-op');
      } finally {
        await closeTestDb(db, tmpDir);
      }
    });

    test('no prior win is a no-op', () async {
      final (db, tmpDir) = await openTestDb();
      try {
        final result = await db.applyPassiveStreakReset(
          lang: 'en',
          today: DateTime(2026, 6, 15),
        );
        expect(result.currentStreak, equals(0),
            reason: 'no prior win — nothing to reset');
      } finally {
        await closeTestDb(db, tmpDir);
      }
    });
  });
}
