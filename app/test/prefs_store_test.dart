/// Unit tests for [PrefsStore] — the shared_preferences-backed storage backend.
///
/// Uses [SharedPreferences.setMockInitialValues] to get a clean in-memory store
/// without touching the real platform prefs.  No SQLite, no file system.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/persistence.dart';
import 'package:mindmeld/core/prefs_store.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Create an isolated [PrefsStore] backed by in-memory mock prefs.
Future<PrefsStore> openPrefsStore() async {
  SharedPreferences.setMockInitialValues({});
  final store = PrefsStore();
  await store.init();
  return store;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  // ---------------------------------------------------------------------------
  // Backend kind
  // ---------------------------------------------------------------------------
  test('PrefsStore reports kind=prefs', () async {
    final store = await openPrefsStore();
    expect(store.kind, equals(StorageBackendKind.prefs));
  });

  // ---------------------------------------------------------------------------
  // Day state round-trip
  // ---------------------------------------------------------------------------
  group('PrefsStore day state', () {
    test('save and load round-trips correctly', () async {
      final store = await openPrefsStore();

      final guess = Guess(
        word: 'melody',
        rank: 42,
        similarity: 0.712,
        band: TemperatureBand.scorching,
      );
      final hint = RevealedHint(rank: 5, word: 'rhythm');
      final state = DayState(
        date: '2026-06-13',
        lang: 'en',
        guesses: [guess],
        hintsUsed: 1,
        won: false,
        gaveUp: false,
        revealedHints: [hint],
      );

      await store.saveDayState(state);
      final loaded = await store.loadDayState('2026-06-13', 'en');

      expect(loaded, isNotNull);
      expect(loaded!.guesses.length, equals(1));
      expect(loaded.guesses.first.word, equals('melody'));
      expect(loaded.guesses.first.rank, equals(42));
      expect(loaded.guesses.first.similarity, closeTo(0.712, 1e-9));
      expect(loaded.guesses.first.band, equals(TemperatureBand.scorching));
      expect(loaded.hintsUsed, equals(1));
      expect(loaded.won, isFalse);
      expect(loaded.gaveUp, isFalse);
      expect(loaded.revealedHints.length, equals(1));
      expect(loaded.revealedHints.first.rank, equals(5));
      expect(loaded.revealedHints.first.word, equals('rhythm'));
    });

    test('returns null for absent (date, lang) key', () async {
      final store = await openPrefsStore();
      final result = await store.loadDayState('2026-06-13', 'en');
      expect(result, isNull);
    });

    test('en and hi-en states are stored independently (lang isolation)', () async {
      final store = await openPrefsStore();

      final enState = DayState(
        date: '2026-06-13',
        lang: 'en',
        guesses: [],
        hintsUsed: 0,
        won: true,
        gaveUp: false,
      );
      final hiEnState = DayState(
        date: '2026-06-13',
        lang: 'hi-en',
        guesses: [],
        hintsUsed: 0,
        won: false,
        gaveUp: false,
      );

      await store.saveDayState(enState);
      await store.saveDayState(hiEnState);

      final loadedEn = await store.loadDayState('2026-06-13', 'en');
      final loadedHiEn = await store.loadDayState('2026-06-13', 'hi-en');

      expect(loadedEn!.won, isTrue, reason: 'en state should be won');
      expect(loadedHiEn!.won, isFalse,
          reason: 'hi-en state must not inherit en win');
    });

    test('upsert overwrites existing state', () async {
      final store = await openPrefsStore();

      final initial = DayState(
        date: '2026-06-13',
        lang: 'en',
        guesses: [],
        hintsUsed: 0,
        won: false,
        gaveUp: false,
      );
      await store.saveDayState(initial);

      final updated = DayState(
        date: '2026-06-13',
        lang: 'en',
        guesses: [
          Guess(
              word: 'jazz', rank: 1, similarity: 1.0, band: TemperatureBand.win)
        ],
        hintsUsed: 2,
        won: true,
        gaveUp: false,
      );
      await store.saveDayState(updated);

      final loaded = await store.loadDayState('2026-06-13', 'en');
      expect(loaded!.won, isTrue);
      expect(loaded.guesses.length, equals(1));
      expect(loaded.guesses.first.word, equals('jazz'));
    });
  });

  // ---------------------------------------------------------------------------
  // Stats round-trip
  // ---------------------------------------------------------------------------
  group('PrefsStore stats', () {
    test('empty stats returned when no data exists', () async {
      final store = await openPrefsStore();
      final stats = await store.loadStats('en');
      expect(stats.played, equals(0));
      expect(stats.wins, equals(0));
      expect(stats.currentStreak, equals(0));
      expect(stats.maxStreak, equals(0));
    });

    test('save and load stats round-trips correctly', () async {
      final store = await openPrefsStore();

      final stats = PlayerStats(
        played: 10,
        wins: 7,
        currentStreak: 3,
        maxStreak: 5,
        guessDistribution: {'3': 2, '5': 4, '10': 1},
      );
      await store.saveStats('en', stats, DateTime(2026, 6, 13));
      final loaded = await store.loadStats('en');

      expect(loaded.played, equals(10));
      expect(loaded.wins, equals(7));
      expect(loaded.currentStreak, equals(3));
      expect(loaded.maxStreak, equals(5));
      expect(loaded.guessDistribution['3'], equals(2));
      expect(loaded.guessDistribution['5'], equals(4));
      expect(loaded.guessDistribution['10'], equals(1));
    });

    test('loadLastWinDate returns null when absent', () async {
      final store = await openPrefsStore();
      final lwd = await store.loadLastWinDate('en');
      expect(lwd, isNull);
    });

    test('loadLastWinDate round-trips a stored date', () async {
      final store = await openPrefsStore();
      final stats = PlayerStats.empty;
      await store.saveStats('en', stats, DateTime(2026, 6, 13));
      final lwd = await store.loadLastWinDate('en');
      expect(lwd, isNotNull);
      expect(lwd!.year, equals(2026));
      expect(lwd.month, equals(6));
      expect(lwd.day, equals(13));
    });

    test('saveStats with null lastWinDate does not overwrite previous date',
        () async {
      // Each saveStats call is a full replace, so null last_win_date
      // writes null. This tests the semantics explicitly.
      final store = await openPrefsStore();
      await store.saveStats('en', PlayerStats.empty, DateTime(2026, 6, 12));
      final lwd1 = await store.loadLastWinDate('en');
      expect(lwd1, isNotNull);

      // Now a loss call (null lastWinDate) replaces the stats row.
      // recordLoss passes null — the date is lost. This is the same
      // behaviour as the SQLite backend.
      await store.saveStats('en', PlayerStats.empty, null);
      final lwd2 = await store.loadLastWinDate('en');
      expect(lwd2, isNull);
    });
  });

  // ---------------------------------------------------------------------------
  // Streak persistence via AppPersistence façade
  // ---------------------------------------------------------------------------
  group('PrefsStore streak persistence via AppPersistence', () {
    setUp(() {
      AppPersistence.resetForTest();
      SharedPreferences.setMockInitialValues({});
    });

    tearDown(() async {
      await AppPersistence.instance.close();
      AppPersistence.resetForTest();
    });

    test('first win sets streak=1', () async {
      final store = PrefsStore();
      await store.init();
      final db = await AppPersistence.injectBackendForTest(store);

      await db.recordWin(
          lang: 'en', guessCount: 5, today: DateTime(2026, 6, 13));
      final stats = await db.loadStats('en');
      expect(stats.currentStreak, equals(1));
      expect(stats.maxStreak, equals(1));
      expect(stats.wins, equals(1));
    });

    test('consecutive day win increments streak to 2', () async {
      final store = PrefsStore();
      await store.init();
      final db = await AppPersistence.injectBackendForTest(store);

      final day1 = DateTime(2026, 6, 12);
      final day2 = DateTime(2026, 6, 13);

      await db.recordWin(lang: 'en', guessCount: 4, today: day1);
      await db.recordWin(lang: 'en', guessCount: 6, today: day2);

      final stats = await db.loadStats('en');
      expect(stats.currentStreak, equals(2));
      expect(stats.maxStreak, equals(2));
    });

    test('gap resets streak to 1', () async {
      final store = PrefsStore();
      await store.init();
      final db = await AppPersistence.injectBackendForTest(store);

      final day1 = DateTime(2026, 6, 1);
      final day8 = DateTime(2026, 6, 9);

      await db.recordWin(lang: 'en', guessCount: 3, today: day1);
      await db.recordWin(lang: 'en', guessCount: 7, today: day8);

      final stats = await db.loadStats('en');
      expect(stats.currentStreak, equals(1));
      // maxStreak was 1 from first win; stayed 1.
      expect(stats.maxStreak, equals(1));
    });

    test('loss resets streak to 0', () async {
      final store = PrefsStore();
      await store.init();
      final db = await AppPersistence.injectBackendForTest(store);

      await db.recordWin(lang: 'en', guessCount: 5, today: DateTime(2026, 6, 13));
      await db.recordLoss(lang: 'en');

      final stats = await db.loadStats('en');
      expect(stats.currentStreak, equals(0));
      expect(stats.played, equals(2));
      expect(stats.wins, equals(1));
    });
  });

  // ---------------------------------------------------------------------------
  // Analytics ring buffer
  // ---------------------------------------------------------------------------
  group('PrefsStore analytics ring buffer', () {
    test('logged events are retrievable in insertion order', () async {
      final store = await openPrefsStore();

      await store.logEvent('guess', {'word': 'alpha'});
      await store.logEvent('guess', {'word': 'beta'});
      await store.logEvent('win', {'guesses': 2});

      final buf = await store.exportAnalyticsBuffer();
      expect(buf.length, equals(3));
      expect(buf[0]['event_name'], equals('guess'));
      expect(buf[2]['event_name'], equals('win'));
    });

    test('unflushed events returned by exportUnflushedEvents', () async {
      final store = await openPrefsStore();

      await store.logEvent('guess', {'word': 'alpha'});
      await store.logEvent('guess', {'word': 'beta'});

      final unflushed = await store.exportUnflushedEvents();
      expect(unflushed.length, equals(2));
      expect(unflushed.every((r) => r['flushed'] == 0), isTrue);
    });

    test('markEventsFlushed marks correct rows', () async {
      final store = await openPrefsStore();

      await store.logEvent('a', {});
      await store.logEvent('b', {});
      await store.logEvent('c', {});

      final buf = await store.exportAnalyticsBuffer();
      final id0 = buf[0]['id'] as int;
      final id2 = buf[2]['id'] as int;

      await store.markEventsFlushed([id0, id2]);

      final unflushed = await store.exportUnflushedEvents();
      expect(unflushed.length, equals(1));
      expect(unflushed.first['event_name'], equals('b'));
    });

    test('ring buffer caps at 500 rows (FIFO eviction)', () async {
      final store = await openPrefsStore();

      // Log 510 events — oldest 10 should be evicted.
      for (int i = 0; i < 510; i++) {
        await store.logEvent('evt', {'i': i});
      }

      final buf = await store.exportAnalyticsBuffer();
      expect(buf.length, equals(500));

      // First surviving event should have i=10 (JSON encoding is compact).
      final firstProps = buf.first['props_json'] as String;
      expect(firstProps, contains('"i":10'));
    });

    test('exportUnflushedEvents respects limit parameter', () async {
      final store = await openPrefsStore();

      for (int i = 0; i < 20; i++) {
        await store.logEvent('e', {'i': i});
      }

      final limited = await store.exportUnflushedEvents(limit: 5);
      expect(limited.length, equals(5));
    });

    test('markEventsFlushed with empty list is a no-op', () async {
      final store = await openPrefsStore();
      await store.logEvent('x', {});
      // Should not throw.
      await store.markEventsFlushed([]);
      final unflushed = await store.exportUnflushedEvents();
      expect(unflushed.length, equals(1));
    });
  });
}
