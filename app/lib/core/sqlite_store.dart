/// SQLite-backed [StorageBackend] implementation for Mindmeld.
///
/// On native platforms the sqflite platform-channel factory is used.
/// On web, sqflite_common_ffi_web provides a WASM/IndexedDB backend.
///
/// Schema (v3):
///   day_state  — one row per (date, lang): guess history, hints, won/gaveUp.
///   stats      — one row per lang: played, wins, streaks, distribution.
///   analytics  — ring buffer max 500 rows; FIFO eviction; flushed flag.
library;

import 'dart:convert';

import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/storage_backend.dart';
import 'package:mindmeld/core/storage_factory_stub.dart'
    // ignore: uri_does_not_exist
    if (dart.library.io) 'package:mindmeld/core/storage_factory_io.dart'
    // ignore: uri_does_not_exist
    if (dart.library.html) 'package:mindmeld/core/storage_factory_web.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:sqflite_common/sqlite_api.dart';

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
    final bool isWeb = const bool.fromEnvironment('dart.library.html');
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
        version: 3,
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
        dist_json TEXT NOT NULL DEFAULT '{}'
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
  }

  /// v1 → v2: add revealed_hints_json to day_state.
  /// v2 → v3: add flushed column to analytics.
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
