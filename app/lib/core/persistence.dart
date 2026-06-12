import 'dart:convert';

import 'package:mindmeld/core/models.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:sqflite/sqflite.dart';

/// Streak update result — returned by [updateStreak] for testability.
class StreakResult {
  const StreakResult({
    required this.currentStreak,
    required this.maxStreak,
  });

  final int currentStreak;
  final int maxStreak;
}

/// Pure-Dart streak calculation — no database I/O, fully unit-testable.
///
/// Rules:
///   - Same-day win: idempotent (streak unchanged).
///   - Consecutive-day win (today == lastWinDate + 1 day): increment streak.
///   - Gap > 1 day: reset streak to 1.
StreakResult updateStreak({
  required DateTime? lastWinDate,
  required DateTime today,
  required int currentStreak,
  required int maxStreak,
}) {
  // Normalise to midnight to avoid time-of-day drift.
  final todayNorm = DateTime(today.year, today.month, today.day);

  if (lastWinDate == null) {
    // First ever win.
    final next = StreakResult(currentStreak: 1, maxStreak: maxStreak.clamp(1, 999999));
    return StreakResult(
      currentStreak: 1,
      maxStreak: next.maxStreak < 1 ? 1 : next.maxStreak,
    );
  }

  final lastNorm =
      DateTime(lastWinDate.year, lastWinDate.month, lastWinDate.day);
  final diff = todayNorm.difference(lastNorm).inDays;

  if (diff == 0) {
    // Same day — idempotent.
    return StreakResult(currentStreak: currentStreak, maxStreak: maxStreak);
  }

  int next;
  if (diff == 1) {
    // Consecutive day — extend streak.
    next = currentStreak + 1;
  } else {
    // Gap — reset.
    next = 1;
  }

  return StreakResult(
    currentStreak: next,
    maxStreak: next > maxStreak ? next : maxStreak,
  );
}

/// SQLite-backed persistence layer for Mindmeld.
///
/// Tables:
///   - day_state:   one row per (date, lang); stores guess history, hints used, won/gaveUp.
///   - stats:       one row per lang; stores played, wins, streaks, guess distribution.
///   - analytics:   ring buffer, max 500 rows; FIFO eviction.
class AppPersistence {
  AppPersistence._();

  static AppPersistence? _instance;
  Database? _db;

  static AppPersistence get instance {
    _instance ??= AppPersistence._();
    return _instance!;
  }

  static const int _analyticsMaxRows = 500;

  /// Initialise (or open) the database at [dbPath].
  ///
  /// If [dbPath] is null the platform default documents directory is used.
  /// Pass an explicit path in tests (sqflite_common_ffi + temp dir).
  Future<void> init({String? dbPath}) async {
    if (_db != null) return;
    final path = dbPath ?? p.join(
      (await getApplicationDocumentsDirectory()).path,
      'mindmeld.db',
    );
    _db = await openDatabase(
      path,
      version: 2,
      onCreate: _onCreate,
      onUpgrade: _onUpgrade,
    );
  }

  Database get _database {
    if (_db == null) throw StateError('AppPersistence not initialised. Call init() first.');
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
        ts INTEGER NOT NULL
      )
    ''');
  }

  /// Incremental schema migrations.
  ///
  /// v1 → v2: add [revealed_hints_json] column to [day_state].
  /// Existing rows get the DEFAULT value ('[]') automatically.
  Future<void> _onUpgrade(Database db, int oldVersion, int newVersion) async {
    if (oldVersion < 2) {
      await db.execute(
        "ALTER TABLE day_state ADD COLUMN revealed_hints_json TEXT NOT NULL DEFAULT '[]'",
      );
    }
  }

  // ---------------------------------------------------------------------------
  // Day state
  // ---------------------------------------------------------------------------

  Future<DayState?> loadDayState(String date, String lang) async {
    final rows = await _database.query(
      'day_state',
      where: 'date = ? AND lang = ?',
      whereArgs: [date, lang],
    );
    if (rows.isEmpty) return null;
    final row = rows.first;
    final guessesJson = jsonDecode(row['guesses_json'] as String) as List<dynamic>;
    final guesses = guessesJson.map(_guessFromJson).toList();
    // revealed_hints_json was added in schema v2; guard against missing column
    // on old DBs that were upgraded before the DEFAULT filled in (belt-and-suspenders).
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

  /// Record a win and update streaks atomically.
  ///
  /// [guessCount] is added to the guess distribution.
  /// [today] should be the puzzle date (not wall-clock time in tests).
  Future<PlayerStats> recordWin({
    required String lang,
    required int guessCount,
    required DateTime today,
  }) async {
    final current = await loadStats(lang);
    final lastWin = await loadLastWinDate(lang);

    final streak = updateStreak(
      lastWinDate: lastWin,
      today: today,
      currentStreak: current.currentStreak,
      maxStreak: current.maxStreak,
    );

    final dist = Map<String, int>.from(current.guessDistribution);
    final key = guessCount.toString();
    dist[key] = (dist[key] ?? 0) + 1;

    final updated = current.copyWith(
      played: current.played + 1,
      wins: current.wins + 1,
      currentStreak: streak.currentStreak,
      maxStreak: streak.maxStreak,
      guessDistribution: dist,
    );

    await _saveStats(lang, updated, today);
    return updated;
  }

  /// Record a loss (give-up) — increments played without updating streak.
  Future<PlayerStats> recordLoss({required String lang}) async {
    final current = await loadStats(lang);
    final updated = current.copyWith(
      played: current.played + 1,
      // Losing resets streak to 0.
      currentStreak: 0,
    );
    await _saveStats(lang, updated, null);
    return updated;
  }

  Future<void> _saveStats(
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

  /// Log an analytics event to the local ring buffer.
  ///
  /// Automatically evicts oldest rows when count exceeds [_analyticsMaxRows].
  Future<void> logEvent(String name, Map<String, dynamic> props) async {
    final ts = DateTime.now().millisecondsSinceEpoch;
    await _database.insert('analytics', {
      'event_name': name,
      'props_json': jsonEncode(props),
      'ts': ts,
    });

    // Enforce ring buffer cap: delete oldest rows beyond the limit.
    await _database.rawDelete('''
      DELETE FROM analytics
      WHERE id NOT IN (
        SELECT id FROM analytics ORDER BY id DESC LIMIT $_analyticsMaxRows
      )
    ''');
  }

  /// Export all buffered analytics events (explicit no-op stub; Phase 2 wires Firebase).
  Future<List<Map<String, dynamic>>> exportAnalyticsBuffer() async {
    return _database.query('analytics', orderBy: 'id ASC');
  }

  // ---------------------------------------------------------------------------
  // Helpers
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

  /// Close the database (used in tests).
  Future<void> close() async {
    await _db?.close();
    _db = null;
  }

  /// Reset the singleton (used in tests to get a fresh instance).
  static void resetForTest() {
    _instance = null;
  }
}
