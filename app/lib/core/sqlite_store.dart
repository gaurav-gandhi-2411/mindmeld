/// SQLite-backed [StorageBackend] implementation for Mindmeld.
///
/// On native platforms the sqflite platform-channel factory is used.
/// On web, sqflite_common_ffi_web provides a WASM/IndexedDB backend.
///
/// Schema (v5):
///   day_state      — one row per (date, lang): guess history, hints, won/gaveUp.
///   stats          — one row per lang: played, wins, streaks, distribution.
///   analytics      — ring buffer max 500 rows; FIFO eviction; flushed flag.
///   pack_progress  — one row per (pack_id, idx, lang): themed-pack puzzle
///                    state (phase 6c). Deliberately separate from day_state/
///                    stats so pack play never touches the daily streak.
///   meta           — one row per (key): small internal flags, e.g. the
///                    PrefsStore -> SQLite one-time migration marker (see
///                    persistence.dart's wasm-stub-remediation migration).
library;

import 'dart:convert';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/storage_backend.dart';
// dart.library.js_interop, not dart.library.html: html is FALSE under the
// --wasm production build target, which silently selected the stub factory
// (UnsupportedError at init, then AppPersistence fell back to PrefsStore) on
// every production web build since the launch-1 wasm adoption. js_interop is
// true for BOTH web compile targets (dart2js/DDC and dart2wasm), false on
// native. See known-limitations entry 19 / reset_web.dart for the same fix
// pattern applied elsewhere in this repo.
import 'package:mindmeld/core/storage_factory_stub.dart'
    // ignore: uri_does_not_exist
    if (dart.library.io) 'package:mindmeld/core/storage_factory_io.dart'
    // ignore: uri_does_not_exist
    if (dart.library.js_interop) 'package:mindmeld/core/storage_factory_web.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:sqflite_common/sqlite_api.dart';
import 'package:sqflite_common/utils/utils.dart' show firstIntValue;

/// SQLite / WASM-SQLite implementation of [StorageBackend].
class SqliteStore implements StorageBackend {
  SqliteStore();

  Database? _db;

  static const int _analyticsMaxRows = 500;

  @override
  StorageBackendKind get kind => StorageBackendKind.sqlite;

  @override
  Future<void> init({String? dbPath}) async {
    if (_db != null) return;

    final factory = getPlatformDatabaseFactory();

    // On web, path_provider is not available; use a fixed virtual path that
    // sqflite_common_ffi_web maps to IndexedDB.
    //
    // kIsWeb (not a dart.library.* const check) so this stays correct on
    // BOTH web compile targets — dart.library.html is FALSE under --wasm,
    // which previously made this branch skip the virtual path and attempt a
    // real filesystem path on web, throwing during init and silently
    // dropping SqliteStore to the PrefsStore fallback (production since
    // 2026-07-12). kIsWeb is a compile-time const on every platform.
    final bool isWeb = kIsWeb;
    final String path;
    if (isWeb) {
      path = dbPath ?? 'mindmeld.db';
    } else {
      path = dbPath ??
          p.join(
            (await getApplicationDocumentsDirectory()).path,
            'mindmeld.db',
          );
    }

    _db = await factory.openDatabase(
      path,
      options: OpenDatabaseOptions(
        version: 6,
        onCreate: _onCreate,
        onUpgrade: _onUpgrade,
      ),
    );
  }

  @override
  Future<void> close() async {
    await _db?.close();
    _db = null;
  }

  Database get _database {
    if (_db == null) {
      throw StateError('SqliteStore not initialised. Call init() first.');
    }
    return _db!;
  }

  Future<void> _onCreate(Database db, int version) async {
    await db.execute('''
      CREATE TABLE day_state (
        date TEXT NOT NULL,
        lang TEXT NOT NULL,
        guesses_json TEXT NOT NULL DEFAULT '[]',
        hints_used INTEGER NOT NULL DEFAULT 0,
        won INTEGER NOT NULL DEFAULT 0,
        gave_up INTEGER NOT NULL DEFAULT 0,
        revealed_hints_json TEXT NOT NULL DEFAULT '[]',
        PRIMARY KEY (date, lang)
      )
    ''');

    await db.execute('''
      CREATE TABLE stats (
        lang TEXT PRIMARY KEY,
        played INTEGER NOT NULL DEFAULT 0,
        wins INTEGER NOT NULL DEFAULT 0,
        current_streak INTEGER NOT NULL DEFAULT 0,
        max_streak INTEGER NOT NULL DEFAULT 0,
        last_win_date TEXT,
        dist_json TEXT NOT NULL DEFAULT '{}',
        streak_freezes INTEGER NOT NULL DEFAULT 0
      )
    ''');

    await db.execute('''
      CREATE TABLE analytics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_name TEXT NOT NULL,
        props_json TEXT NOT NULL DEFAULT '{}',
        ts INTEGER NOT NULL,
        flushed INTEGER NOT NULL DEFAULT 0
      )
    ''');

    await db.execute(_createPackProgressSql);
    await db.execute(_createMetaSql);
  }

  /// v1 → v2: add revealed_hints_json to day_state.
  /// v2 → v3: add flushed column to analytics.
  /// v3 → v4: add pack_progress table (phase 6c themed packs).
  /// v4 → v5: add meta table (internal flags, e.g. migration markers).
  /// v5 → v6: add streak_freezes to stats (earned streak-freeze mechanic).
  Future<void> _onUpgrade(Database db, int oldVersion, int newVersion) async {
    if (oldVersion < 2) {
      await db.execute(
        "ALTER TABLE day_state ADD COLUMN revealed_hints_json TEXT NOT NULL DEFAULT '[]'",
      );
    }
    if (oldVersion < 3) {
      await db.execute(
        'ALTER TABLE analytics ADD COLUMN flushed INTEGER NOT NULL DEFAULT 0',
      );
    }
    if (oldVersion < 4) {
      await db.execute(_createPackProgressSql);
    }
    if (oldVersion < 5) {
      await db.execute(_createMetaSql);
    }
    if (oldVersion < 6) {
      await db.execute(
        'ALTER TABLE stats ADD COLUMN streak_freezes INTEGER NOT NULL DEFAULT 0',
      );
    }
  }

  static const String _createPackProgressSql = '''
    CREATE TABLE IF NOT EXISTS pack_progress (
      pack_id TEXT NOT NULL,
      idx INTEGER NOT NULL,
      lang TEXT NOT NULL,
      guesses_json TEXT NOT NULL DEFAULT '[]',
      hints_used INTEGER NOT NULL DEFAULT 0,
      won INTEGER NOT NULL DEFAULT 0,
      gave_up INTEGER NOT NULL DEFAULT 0,
      revealed_hints_json TEXT NOT NULL DEFAULT '[]',
      PRIMARY KEY (pack_id, idx, lang)
    )
  ''';

  static const String _createMetaSql = '''
    CREATE TABLE IF NOT EXISTS meta (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    )
  ''';

  // ---------------------------------------------------------------------------
  // Internal meta flags (e.g. the PrefsStore -> SQLite one-time migration
  // marker — see persistence.dart's wasm-stub-remediation migration).
  // ---------------------------------------------------------------------------

  /// Reads a small internal flag by [key], or null if never set.
  Future<String?> getMeta(String key) async {
    final rows = await _database.query(
      'meta',
      where: 'key = ?',
      whereArgs: [key],
    );
    if (rows.isEmpty) return null;
    return rows.first['value'] as String?;
  }

  /// Persists a small internal flag [key] = [value] (upsert).
  Future<void> setMeta(String key, String value) async {
    await _database.insert(
      'meta',
      {'key': key, 'value': value},
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  /// True when this database has never recorded any player data (no `stats`
  /// rows and no `day_state` rows) — used by [AppPersistence]'s one-time
  /// PrefsStore migration to decide it is safe to copy data in without ever
  /// overwriting existing sqlite data.
  Future<bool> get isEmpty async {
    final statsCount = firstIntValue(
          await _database.rawQuery('SELECT COUNT(*) AS c FROM stats'),
        ) ??
        0;
    if (statsCount > 0) return false;
    final dayStateCount = firstIntValue(
          await _database.rawQuery('SELECT COUNT(*) AS c FROM day_state'),
        ) ??
        0;
    return dayStateCount == 0;
  }

  // ---------------------------------------------------------------------------
  // Day state
  // ---------------------------------------------------------------------------

  @override
  Future<DayState?> loadDayState(String date, String lang) async {
    final rows = await _database.query(
      'day_state',
      where: 'date = ? AND lang = ?',
      whereArgs: [date, lang],
    );
    if (rows.isEmpty) return null;
    final row = rows.first;
    final guessesJson =
        jsonDecode(row['guesses_json'] as String) as List<dynamic>;
    final guesses = guessesJson.map(_guessFromJson).toList();
    final rawHints = row['revealed_hints_json'];
    final revealedHints = rawHints == null
        ? <RevealedHint>[]
        : (jsonDecode(rawHints as String) as List<dynamic>)
            .map(_revealedHintFromJson)
            .toList();
    return DayState(
      date: date,
      lang: lang,
      guesses: guesses,
      hintsUsed: row['hints_used'] as int,
      won: (row['won'] as int) == 1,
      gaveUp: (row['gave_up'] as int) == 1,
      revealedHints: revealedHints,
    );
  }

  @override
  Future<void> saveDayState(DayState state) async {
    final guessesJson = jsonEncode(state.guesses.map(_guessToJson).toList());
    final hintsJson =
        jsonEncode(state.revealedHints.map(_revealedHintToJson).toList());
    await _database.insert(
      'day_state',
      {
        'date': state.date,
        'lang': state.lang,
        'guesses_json': guessesJson,
        'hints_used': state.hintsUsed,
        'won': state.won ? 1 : 0,
        'gave_up': state.gaveUp ? 1 : 0,
        'revealed_hints_json': hintsJson,
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  // ---------------------------------------------------------------------------
  // Themed-pack progress (phase 6c) — see class doc for the isolation invariant.
  // ---------------------------------------------------------------------------

  @override
  Future<PackPuzzleState?> loadPackState(
      String packId, int idx, String lang) async {
    final rows = await _database.query(
      'pack_progress',
      where: 'pack_id = ? AND idx = ? AND lang = ?',
      whereArgs: [packId, idx, lang],
    );
    if (rows.isEmpty) return null;
    return _packStateFromRow(rows.first, packId, idx, lang);
  }

  @override
  Future<void> savePackState(PackPuzzleState state) async {
    final guessesJson = jsonEncode(state.guesses.map(_guessToJson).toList());
    final hintsJson =
        jsonEncode(state.revealedHints.map(_revealedHintToJson).toList());
    await _database.insert(
      'pack_progress',
      {
        'pack_id': state.packId,
        'idx': state.idx,
        'lang': state.lang,
        'guesses_json': guessesJson,
        'hints_used': state.hintsUsed,
        'won': state.won ? 1 : 0,
        'gave_up': state.gaveUp ? 1 : 0,
        'revealed_hints_json': hintsJson,
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  @override
  Future<List<PackPuzzleState>> loadPackStatesForPack(
      String packId, String lang) async {
    final rows = await _database.query(
      'pack_progress',
      where: 'pack_id = ? AND lang = ?',
      whereArgs: [packId, lang],
    );
    return rows
        .map((row) => _packStateFromRow(row, packId, row['idx'] as int, lang))
        .toList();
  }

  PackPuzzleState _packStateFromRow(
    Map<String, dynamic> row,
    String packId,
    int idx,
    String lang,
  ) {
    final guessesJson =
        jsonDecode(row['guesses_json'] as String) as List<dynamic>;
    final guesses = guessesJson.map(_guessFromJson).toList();
    final rawHints = row['revealed_hints_json'];
    final revealedHints = rawHints == null
        ? <RevealedHint>[]
        : (jsonDecode(rawHints as String) as List<dynamic>)
            .map(_revealedHintFromJson)
            .toList();
    return PackPuzzleState(
      packId: packId,
      idx: idx,
      lang: lang,
      guesses: guesses,
      hintsUsed: row['hints_used'] as int,
      won: (row['won'] as int) == 1,
      gaveUp: (row['gave_up'] as int) == 1,
      revealedHints: revealedHints,
    );
  }

  // ---------------------------------------------------------------------------
  // Stats
  // ---------------------------------------------------------------------------

  @override
  Future<PlayerStats> loadStats(String lang) async {
    final rows = await _database.query(
      'stats',
      where: 'lang = ?',
      whereArgs: [lang],
    );
    if (rows.isEmpty) return PlayerStats.empty;
    final row = rows.first;
    final distJson =
        jsonDecode(row['dist_json'] as String) as Map<String, dynamic>;
    return PlayerStats(
      played: row['played'] as int,
      wins: row['wins'] as int,
      currentStreak: row['current_streak'] as int,
      maxStreak: row['max_streak'] as int,
      guessDistribution: distJson.map((k, v) => MapEntry(k, v as int)),
      streakFreezes: (row['streak_freezes'] as int?) ?? 0,
    );
  }

  @override
  Future<DateTime?> loadLastWinDate(String lang) async {
    final rows = await _database.query(
      'stats',
      columns: ['last_win_date'],
      where: 'lang = ?',
      whereArgs: [lang],
    );
    if (rows.isEmpty) return null;
    final raw = rows.first['last_win_date'];
    if (raw == null) return null;
    return DateTime.tryParse(raw as String);
  }

  @override
  Future<void> saveStats(
    String lang,
    PlayerStats stats,
    DateTime? lastWinDate,
  ) async {
    await _database.insert(
      'stats',
      {
        'lang': lang,
        'played': stats.played,
        'wins': stats.wins,
        'current_streak': stats.currentStreak,
        'max_streak': stats.maxStreak,
        'last_win_date': lastWinDate?.toIso8601String(),
        'dist_json': jsonEncode(stats.guessDistribution),
        'streak_freezes': stats.streakFreezes,
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  // ---------------------------------------------------------------------------
  // Analytics ring buffer
  // ---------------------------------------------------------------------------

  @override
  Future<void> logEvent(String name, Map<String, dynamic> props) async {
    final ts = DateTime.now().millisecondsSinceEpoch;
    await _database.insert('analytics', {
      'event_name': name,
      'props_json': jsonEncode(props),
      'ts': ts,
    });

    await _database.rawDelete('''
      DELETE FROM analytics
      WHERE id NOT IN (
        SELECT id FROM analytics ORDER BY id DESC LIMIT $_analyticsMaxRows
      )
    ''');
  }

  @override
  Future<List<Map<String, dynamic>>> exportAnalyticsBuffer() async {
    return _database.query('analytics', orderBy: 'id ASC');
  }

  @override
  Future<List<Map<String, dynamic>>> exportUnflushedEvents(
      {int limit = 500}) async {
    return _database.query(
      'analytics',
      where: 'flushed = 0',
      orderBy: 'id ASC',
      limit: limit,
    );
  }

  @override
  Future<void> markEventsFlushed(List<int> ids) async {
    if (ids.isEmpty) return;
    final placeholders = List.filled(ids.length, '?').join(',');
    await _database.rawUpdate(
      'UPDATE analytics SET flushed = 1 WHERE id IN ($placeholders)',
      ids,
    );
  }

  @override
  Future<void> clearAll() async {
    await _database.delete('day_state');
    await _database.delete('stats');
    await _database.delete('analytics');
    await _database.delete('pack_progress');
  }

  // ---------------------------------------------------------------------------
  // Serialisation helpers
  // ---------------------------------------------------------------------------

  Map<String, dynamic> _guessToJson(Guess g) => {
        'word': g.word,
        'rank': g.rank,
        'similarity': g.similarity,
        'band': g.band.name,
      };

  Guess _guessFromJson(dynamic json) {
    final m = json as Map<String, dynamic>;
    return Guess(
      word: m['word'] as String,
      rank: m['rank'] as int,
      similarity: (m['similarity'] as num).toDouble(),
      band: TemperatureBand.values.firstWhere((b) => b.name == m['band']),
    );
  }

  Map<String, dynamic> _revealedHintToJson(RevealedHint h) => {
        'rank': h.rank,
        'word': h.word,
      };

  RevealedHint _revealedHintFromJson(dynamic json) {
    final m = json as Map<String, dynamic>;
    return RevealedHint(rank: m['rank'] as int, word: m['word'] as String);
  }
}
