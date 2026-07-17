/// Unit tests for [migratePrefsIntoSqliteIfNeeded] — the one-time PrefsStore
/// -> SqliteStore migration that runs when the wasm-stub-remediation fix
/// restores real SQLite/IndexedDB storage on web (known-limitations entry
/// 19). Production persisted via [PrefsStore] (localStorage) from 2026-07-12
/// until that fix; without this migration a returning player's streak would
/// silently vanish the moment SqliteStore starts working again.
///
/// Uses the sqflite_common_ffi native factory (same convention as
/// storage_rename_migration_test.dart) so these tests exercise a real
/// SqliteStore without a browser — the migration function itself is
/// backend-agnostic Dart, so this is a faithful proxy for the web path.
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/persistence.dart';
import 'package:mindmeld/core/prefs_store.dart';
import 'package:mindmeld/core/sqlite_store.dart';
import 'package:path/path.dart' as p;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

/// Creates a fresh, isolated [SqliteStore] backed by a temp file, and an
/// isolated in-memory [PrefsStore] — both cleaned up via [addTearDown].
Future<(SqliteStore, PrefsStore)> _openStores() async {
  final tmpDir =
      await Directory.systemTemp.createTemp('warmer_prefs_migration_');
  addTearDown(() => tmpDir.delete(recursive: true));

  final sqlite = SqliteStore();
  await sqlite.init(dbPath: p.join(tmpDir.path, 'mindmeld.db'));
  addTearDown(sqlite.close);

  SharedPreferences.setMockInitialValues({});
  final prefs = PrefsStore();
  await prefs.init();

  return (sqlite, prefs);
}

void main() {
  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  group('migratePrefsIntoSqliteIfNeeded', () {
    test('migrates stats + lastWinDate per lang from PrefsStore into an '
        'empty SqliteStore, preserving the streak', () async {
      final (sqlite, prefs) = await _openStores();

      final enStats = PlayerStats(
        played: 12,
        wins: 10,
        currentStreak: 6,
        maxStreak: 8,
        guessDistribution: const {'3': 4, '4': 5, '5': 1},
      );
      await prefs.saveStats('en', enStats, DateTime.utc(2026, 7, 15));
      // 'hi-en' left untouched — PrefsStore has no data for it.

      await migratePrefsIntoSqliteIfNeeded(sqlite);

      final migratedEn = await sqlite.loadStats('en');
      final migratedEnLastWin = await sqlite.loadLastWinDate('en');
      expect(migratedEn.played, equals(12));
      expect(migratedEn.wins, equals(10));
      expect(migratedEn.currentStreak, equals(6),
          reason: 'streak preservation is the P0 concern this migration exists for');
      expect(migratedEn.maxStreak, equals(8));
      expect(migratedEnLastWin, equals(DateTime.utc(2026, 7, 15)));

      final migratedHiEn = await sqlite.loadStats('hi-en');
      expect(migratedHiEn.played, equals(0),
          reason: 'nothing to migrate for a lang PrefsStore never touched');
    });

    test('migrates unflushed analytics events (skips none — PrefsStore '
        'already filters to unflushed only)', () async {
      final (sqlite, prefs) = await _openStores();

      await prefs.logEvent('puzzle_started', {'lang': 'en'});
      await prefs.logEvent('puzzle_won', {'lang': 'en', 'guesses': 4});

      await migratePrefsIntoSqliteIfNeeded(sqlite);

      final events = await sqlite.exportAnalyticsBuffer();
      expect(events.length, equals(2));
      expect(events.map((e) => e['event_name']),
          containsAll(['puzzle_started', 'puzzle_won']));
    });

    test('marks the migration done so a second call is a no-op even if '
        'PrefsStore later gains more data', () async {
      final (sqlite, prefs) = await _openStores();

      await prefs.saveStats(
        'en',
        const PlayerStats(
          played: 1,
          wins: 1,
          currentStreak: 1,
          maxStreak: 1,
          guessDistribution: {'5': 1},
        ),
        DateTime.utc(2026, 7, 10),
      );
      await migratePrefsIntoSqliteIfNeeded(sqlite);
      expect(await sqlite.getMeta(kPrefsMigrationMetaKey), equals('1'));

      // Simulate a later, unrelated PrefsStore write (should never be pulled
      // in — the marker makes every subsequent call a pure no-op).
      await prefs.saveStats(
        'en',
        const PlayerStats(
          played: 99,
          wins: 99,
          currentStreak: 99,
          maxStreak: 99,
          guessDistribution: {'2': 99},
        ),
        DateTime.utc(2026, 7, 16),
      );
      await migratePrefsIntoSqliteIfNeeded(sqlite);

      final stats = await sqlite.loadStats('en');
      expect(stats.played, equals(1),
          reason: 'second call must be a no-op once the marker is set');
    });

    test('never overwrites pre-existing sqlite data, even without a prior '
        'marker (e.g. a pre-regression install)', () async {
      final (sqlite, prefs) = await _openStores();

      // Sqlite already has real data — e.g. this player used SQLite
      // successfully before the regression started.
      await sqlite.saveStats(
        'en',
        const PlayerStats(
          played: 20,
          wins: 18,
          currentStreak: 15,
          maxStreak: 15,
          guessDistribution: {'3': 18},
        ),
        DateTime.utc(2026, 7, 1),
      );

      // Stale/irrelevant PrefsStore data that must NOT clobber the above.
      await prefs.saveStats(
        'en',
        const PlayerStats(
          played: 2,
          wins: 1,
          currentStreak: 1,
          maxStreak: 1,
          guessDistribution: {'6': 1},
        ),
        DateTime.utc(2026, 6, 1),
      );

      await migratePrefsIntoSqliteIfNeeded(sqlite);

      final stats = await sqlite.loadStats('en');
      expect(stats.played, equals(20),
          reason: 'pre-existing sqlite data must never be overwritten');
      expect(stats.currentStreak, equals(15));
      // The marker is still recorded so future boots don't keep re-checking.
      expect(await sqlite.getMeta(kPrefsMigrationMetaKey), equals('1'));
    });

    test('is a safe no-op when PrefsStore has no data at all', () async {
      final (sqlite, prefs) = await _openStores();
      expect(prefs, isNotNull); // unused otherwise; documents the empty case

      await migratePrefsIntoSqliteIfNeeded(sqlite);

      expect(await sqlite.getMeta(kPrefsMigrationMetaKey), equals('1'));
      final stats = await sqlite.loadStats('en');
      expect(stats.played, equals(0));
    });
  });

  group('SqliteStore.isEmpty / getMeta / setMeta (support for the migration gate)', () {
    test('isEmpty is true for a freshly created database', () async {
      final (sqlite, _) = await _openStores();
      expect(await sqlite.isEmpty, isTrue);
    });

    test('isEmpty becomes false once a stats row exists', () async {
      final (sqlite, _) = await _openStores();
      await sqlite.saveStats('en', PlayerStats.empty.copyWith(played: 1), null);
      expect(await sqlite.isEmpty, isFalse);
    });

    test('isEmpty becomes false once a day_state row exists', () async {
      final (sqlite, _) = await _openStores();
      await sqlite.saveDayState(const DayState(
        date: '2026-07-16',
        lang: 'en',
        guesses: [],
        hintsUsed: 0,
        won: false,
        gaveUp: false,
      ));
      expect(await sqlite.isEmpty, isFalse);
    });

    test('getMeta returns null before setMeta, then round-trips the value',
        () async {
      final (sqlite, _) = await _openStores();
      expect(await sqlite.getMeta('some_flag'), isNull);
      await sqlite.setMeta('some_flag', '1');
      expect(await sqlite.getMeta('some_flag'), equals('1'));
    });
  });
}
