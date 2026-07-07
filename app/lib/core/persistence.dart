import 'dart:developer' as dev;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:mindmeld/core/memory_store.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/prefs_store.dart';
import 'package:mindmeld/core/sqlite_store.dart';
import 'package:mindmeld/core/storage_backend.dart';

export 'package:mindmeld/core/storage_backend.dart' show StorageBackend, StorageBackendKind;

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

/// SQLite-backed persistence layer for Mindmeld with shared_preferences fallback.
///
/// On web, SQLite is attempted first (sqflite_common_ffi_web / WASM).  If the
/// WASM instantiation fails (e.g. Chrome 124 "Import #25 module='env'" error),
/// the initialisation falls back to [PrefsStore] so the app NEVER renders blank.
///
/// On native platforms, [SqliteStore] is always used (no fallback needed).
///
/// Call [activeBackendKind] after [init] to verify which backend is active.
class AppPersistence {
  AppPersistence._();

  static AppPersistence? _instance;
  StorageBackend? _backend;

  static AppPersistence get instance {
    _instance ??= AppPersistence._();
    return _instance!;
  }

  /// Which backend is currently active.  Valid after [init].
  StorageBackendKind? get activeBackendKind => _backend?.kind;

  /// Initialise (or open) the underlying store.
  ///
  /// On web: tries [SqliteStore] first; falls back to [PrefsStore] on error.
  /// On native: always uses [SqliteStore].
  ///
  /// [dbPath] is forwarded to [SqliteStore.init]; ignored by [PrefsStore].
  Future<void> init({String? dbPath}) async {
    if (_backend != null) return;

    if (kIsWeb) {
      await _initWeb(dbPath: dbPath);
    } else {
      final store = SqliteStore();
      await store.init(dbPath: dbPath);
      _backend = store;
      dev.log('AppPersistence: SQLite backend active', name: 'AppPersistence');
    }
  }

  /// Web-specific init: sqflite-first with PrefsStore fallback, then MemoryStore.
  Future<void> _initWeb({String? dbPath}) async {
    try {
      final store = SqliteStore();
      await store.init(dbPath: dbPath);
      _backend = store;
      dev.log('AppPersistence: SQLite/WASM backend active (web)',
          name: 'AppPersistence');
    } catch (e, st) {
      dev.log(
        'AppPersistence: SQLite/WASM init failed — falling back to PrefsStore. Error: $e',
        name: 'AppPersistence',
        error: e,
        stackTrace: st,
      );
      try {
        final prefs = PrefsStore();
        await prefs.init();
        _backend = prefs;
        dev.log(
            'AppPersistence: PrefsStore backend active (web SQLite fallback)',
            name: 'AppPersistence');
      } catch (e2, st2) {
        dev.log(
          'AppPersistence: PrefsStore also failed — falling back to MemoryStore. Error: $e2',
          name: 'AppPersistence',
          error: e2,
          stackTrace: st2,
        );
        final mem = MemoryStore();
        await mem.init();
        _backend = mem;
        dev.log(
            'AppPersistence: MemoryStore active (all storage unavailable)',
            name: 'AppPersistence');
      }
    }
  }

  StorageBackend get _store {
    if (_backend == null) {
      throw StateError('AppPersistence not initialised. Call init() first.');
    }
    return _backend!;
  }

  // ---------------------------------------------------------------------------
  // Day state (delegated to backend)
  // ---------------------------------------------------------------------------

  Future<DayState?> loadDayState(String date, String lang) =>
      _store.loadDayState(date, lang);

  Future<void> saveDayState(DayState state) => _store.saveDayState(state);

  // ---------------------------------------------------------------------------
  // Themed-pack progress (phase 6c)
  //
  // CRITICAL INVARIANT: none of these methods ever touch day_state or stats —
  // they are backed by a dedicated pack_progress table/store so pack play can
  // never affect the daily streak. See test: pack_isolation_test.dart.
  // ---------------------------------------------------------------------------

  Future<PackPuzzleState?> loadPackState(String packId, int idx, String lang) =>
      _store.loadPackState(packId, idx, lang);

  Future<void> savePackState(PackPuzzleState state) =>
      _store.savePackState(state);

  /// Number of puzzles won so far in [packId] for [lang] — used by the pack
  /// selector to render "x/count" progress.
  Future<int> packProgress(String packId, String lang) async {
    final states = await _store.loadPackStatesForPack(packId, lang);
    return states.where((s) => s.won).length;
  }

  /// All persisted puzzle states for [packId] + [lang] — used by the pack
  /// puzzle list screen to render per-puzzle won/attempted/unplayed status.
  Future<List<PackPuzzleState>> loadPackStatesForPack(
          String packId, String lang) =>
      _store.loadPackStatesForPack(packId, lang);

  // ---------------------------------------------------------------------------
  // Stats
  // ---------------------------------------------------------------------------

  Future<PlayerStats> loadStats(String lang) => _store.loadStats(lang);

  Future<DateTime?> loadLastWinDate(String lang) =>
      _store.loadLastWinDate(lang);

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

    await _store.saveStats(lang, updated, today);
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
    await _store.saveStats(lang, updated, null);
    return updated;
  }

  /// Passive streak reset called on Stats screen open.
  ///
  /// If today is more than 1 day after the last win, the streak is broken.
  /// Resets [currentStreak] to 0 and persists the change (preserving
  /// [lastWinDate] and all other stats). Streak-freeze consumption is the
  /// caller's responsibility before invoking this.
  ///
  /// Returns the (possibly updated) stats.
  Future<PlayerStats> applyPassiveStreakReset({
    required String lang,
    required DateTime today,
  }) async {
    final current = await loadStats(lang);
    if (current.currentStreak == 0) return current;

    final lastWin = await loadLastWinDate(lang);
    if (lastWin == null) return current;

    final todayNorm = DateTime(today.year, today.month, today.day);
    final lastNorm = DateTime(lastWin.year, lastWin.month, lastWin.day);
    if (todayNorm.difference(lastNorm).inDays <= 1) return current;

    final updated = current.copyWith(currentStreak: 0);
    await _store.saveStats(lang, updated, null);
    return updated;
  }

  // ---------------------------------------------------------------------------
  // Analytics ring buffer
  // ---------------------------------------------------------------------------

  /// Log an analytics event to the local ring buffer.
  Future<void> logEvent(String name, Map<String, dynamic> props) =>
      _store.logEvent(name, props);

  /// Export all buffered analytics events (including already-flushed rows).
  Future<List<Map<String, dynamic>>> exportAnalyticsBuffer() =>
      _store.exportAnalyticsBuffer();

  /// Export only analytics events that have NOT yet been flushed to Firebase.
  Future<List<Map<String, dynamic>>> exportUnflushedEvents({int limit = 500}) =>
      _store.exportUnflushedEvents(limit: limit);

  /// Mark the given event [ids] as flushed so they are not re-sent.
  Future<void> markEventsFlushed(List<int> ids) =>
      _store.markEventsFlushed(ids);

  // ---------------------------------------------------------------------------
  // Reset
  // ---------------------------------------------------------------------------

  /// Delete ALL game data (day states, stats, analytics).
  ///
  /// Exposed for the ?reset=1 developer hook (web only).
  Future<void> clearAll() => _store.clearAll();

  // ---------------------------------------------------------------------------
  // Test utilities
  // ---------------------------------------------------------------------------

  /// Close the database (used in tests).
  Future<void> close() async {
    await _backend?.close();
    _backend = null;
  }

  /// Reset the singleton (used in tests to get a fresh instance).
  static void resetForTest() {
    _instance = null;
  }

  /// Inject a specific backend (used in tests to bypass platform detection).
  ///
  /// Call [resetForTest] first, then [injectBackendForTest], then proceed.
  static Future<AppPersistence> injectBackendForTest(
    StorageBackend backend,
  ) async {
    _instance ??= AppPersistence._();
    _instance!._backend = backend;
    return _instance!;
  }
}

