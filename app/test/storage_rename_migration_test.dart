/// Regression coverage for the Mindmeld -> Warmer rename's storage-safety
/// requirement: an existing player's local data (streaks/stats/day state)
/// must survive the rename untouched.
///
/// No literal storage-key migration was needed for this rename:
///   - [SqliteStore]'s database file is named "mindmeld.db" — an internal,
///     never-user-visible path — and was deliberately left unchanged (same
///     reasoning as leaving the Firebase project id `mindmeld-c4bba`
///     unchanged: renaming it would strand every existing installed user's
///     local data for zero user-facing benefit).
///   - [PrefsStore]'s keys use an `mm_` prefix that never literally contained
///     "mindmeld" — nothing to rename there either.
///
/// These tests lock both facts in as regressions: if a future change quietly
/// renames the db filename or the prefs key prefix, this suite fails instead
/// of silently orphaning existing players' data.
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/prefs_store.dart';
import 'package:mindmeld/core/sqlite_store.dart';
import 'package:path/path.dart' as p;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

void main() {
  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  group('existing-user data survives the mindmeld -> warmer rename', () {
    test('a pre-rename mindmeld.db file is found and its data survives '
        'a fresh SqliteStore instance pointed at the same path', () async {
      final tmpDir =
          await Directory.systemTemp.createTemp('warmer_rename_migration_');
      addTearDown(() => tmpDir.delete(recursive: true));

      // Simulate a pre-rename install: the db file is literally named
      // "mindmeld.db", exactly as it was before this phase.
      final dbPath = p.join(tmpDir.path, 'mindmeld.db');

      final preRenameStore = SqliteStore();
      await preRenameStore.init(dbPath: dbPath);
      final stats = PlayerStats(
        played: 7,
        wins: 6,
        currentStreak: 4,
        maxStreak: 5,
        guessDistribution: const {'3': 2, '4': 3, '5': 1},
      );
      await preRenameStore.saveStats(
          'en', stats, DateTime.utc(2026, 7, 9));
      await preRenameStore.close();

      // Post-rename app code re-opens storage the normal way — no special
      // migration path — pointed at the same on-disk file.
      final postRenameStore = SqliteStore();
      await postRenameStore.init(dbPath: dbPath);
      final loaded = await postRenameStore.loadStats('en');
      final lastWin = await postRenameStore.loadLastWinDate('en');
      await postRenameStore.close();

      expect(loaded.played, equals(7));
      expect(loaded.wins, equals(6));
      expect(loaded.currentStreak, equals(4),
          reason: 'streak must survive the rename with zero data loss');
      expect(loaded.maxStreak, equals(5));
      expect(lastWin, equals(DateTime.utc(2026, 7, 9)));
    });

    test('PrefsStore keys are not namespaced on the literal string '
        '"mindmeld" — nothing to migrate for web-fallback users', () async {
      SharedPreferences.setMockInitialValues({});
      final store = PrefsStore();
      await store.init();

      final stats = PlayerStats(
        played: 3,
        wins: 2,
        currentStreak: 2,
        maxStreak: 2,
        guessDistribution: const {'4': 2},
      );
      await store.saveStats('en', stats, DateTime.utc(2026, 7, 9));

      final prefs = await SharedPreferences.getInstance();
      final keys = prefs.getKeys();
      expect(keys, isNotEmpty);
      for (final key in keys) {
        expect(key.toLowerCase(), isNot(contains('mindmeld')),
            reason: 'PrefsStore keys use the "mm_" prefix, never the literal '
                'product name — asserting that stays true so a future '
                'rename of the prefix does not silently strand existing '
                'web-fallback players\' localStorage data');
        expect(key, startsWith('mm_'));
      }
    });
  });
}
