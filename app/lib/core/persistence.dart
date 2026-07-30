import 'dart:convert';
import 'dart:developer' as dev;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:mindmeld/core/config.dart';
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

/// Streak-freeze earning rule: one freeze granted every this-many-day streak
/// milestone (7, 14, 21, ...), capped at [maxStreakFreezes] held at once.
/// Earned, never purchased — see `AppPersistence.recordWin`'s grant and
/// `AppPersistence.rescueStreakOrReset`'s consumption.
const int streakFreezeMilestoneDays = 7;

/// Maximum number of unconsumed streak freezes a player can hold at once.
const int maxStreakFreezes = 3;

/// Result of [AppPersistence.rescueStreakOrReset].
class StreakRescueResult {
  const StreakRescueResult({required this.stats, required this.rescued});

  /// Stats after the check — either unchanged, freeze-consumed
  /// (streak preserved), or streak reset to 0.
  final PlayerStats stats;

  /// True when a streak freeze was just spent to cover exactly one missed
  /// day. False for "nothing to do" (streak intact) and for "streak reset"
  /// (gap too large, or no freeze held) alike — callers that need to tell
  /// those two apart can compare `stats.currentStreak` before/after.
  final bool rescued;
}

/// [SqliteStore.meta] key marking the one-time PrefsStore -> SQLite
/// migration (wasm-stub-remediation wave, see [migratePrefsIntoSqliteIfNeeded])
/// as done. Bump the suffix (`_v2`, ...) if the migration logic itself ever
/// changes in a way that should force a re-evaluation.
const String kPrefsMigrationMetaKey = 'prefs_to_sqlite_migration_v1';

/// One-time PrefsStore -> SqliteStore migration, run from [AppPersistence
/// ._initWeb] immediately after a SqliteStore successfully initialises.
///
/// Context: production web persisted via [PrefsStore] (localStorage) from
/// 2026-07-12 until the wasm-stub-remediation fix (known-limitations entry
/// 19) restored real SQLite/IndexedDB storage. Without this migration, a
/// returning player's existing PrefsStore data would become invisible the
/// moment SqliteStore starts working again — most importantly their win
/// streak.
///
/// Runs at most once per sqlite database (see [kPrefsMigrationMetaKey]) and
/// only when [sqlite] is provably empty (no `stats` rows, no `day_state`
/// rows — see [SqliteStore.isEmpty]), so it can never clobber real sqlite
/// data, whether from a previous migration or from a pre-regression install.
///
/// What migrates (fully expressible via the narrow [StorageBackend]
/// interface, without adding a raw key-enumeration primitive to either
/// concrete store):
///   - [PlayerStats] + last-win-date for every [AppConfig.supportedLangs]
///     entry — this alone preserves the streak, the P0 concern that
///     motivated this migration.
///   - Unflushed analytics events (bounded, ≤500 rows; already-flushed rows
///     are intentionally skipped — [StorageBackend.exportUnflushedEvents]
///     does exactly that filtering for us).
///
/// What does NOT migrate, and why (documented rather than silently dropped):
///   - `day_state`: [StorageBackend] only exposes a keyed lookup
///     (`loadDayState(date, lang)`); there is no "list every (date, lang)
///     this player ever played" primitive, and adding a raw key-scan to
///     [PrefsStore]/[StorageBackend] is out of this migration's scope.
///     Impact: if today's puzzle was already finished under PrefsStore, it
///     will look unstarted once under SQLite and can simply be replayed;
///     older Archive-only entries are not recoverable. The streak itself is
///     unaffected — it lives in `stats`, migrated above, independently of
///     `day_state`.
///   - `pack_progress`: enumerating it requires knowing every pack id the
///     player has touched, which is only discoverable via the themed-pack
///     manifest (a network/bundled-asset fetch that belongs to the
///     features/packs layer, not the storage layer). Same graceful
///     degradation as `day_state`: a finished pack puzzle looks unplayed
///     once; no data corruption, no streak impact.
///
/// Failures here are logged and swallowed (never fatal — a migration bug
/// must not turn into a boot failure); the app proceeds on the fresh, empty
/// SqliteStore exactly as it would have before this migration existed.
Future<void> migratePrefsIntoSqliteIfNeeded(SqliteStore sqlite) async {
  try {
    if (await sqlite.getMeta(kPrefsMigrationMetaKey) == '1') return;

    if (!await sqlite.isEmpty) {
      // Real sqlite data already exists (a previous migration that crashed
      // before recording the marker, or a pre-regression install that never
      // needed migrating) — never overwrite it. Just record the marker so
      // this check doesn't re-run on every future boot.
      await sqlite.setMeta(kPrefsMigrationMetaKey, '1');
      return;
    }

    final prefs = PrefsStore();
    await prefs.init();

    var migratedStats = 0;
    for (final lang in AppConfig.supportedLangs) {
      final stats = await prefs.loadStats(lang);
      final lastWinDate = await prefs.loadLastWinDate(lang);
      if (stats.played == 0 && lastWinDate == null) continue;
      await sqlite.saveStats(lang, stats, lastWinDate);
      migratedStats++;
    }

    final unflushed = await prefs.exportUnflushedEvents();
    for (final row in unflushed) {
      final propsRaw = row['props_json'];
      final props = propsRaw is String
          ? jsonDecode(propsRaw) as Map<String, dynamic>
          : <String, dynamic>{};
      await sqlite.logEvent(row['event_name'] as String, props);
    }

    await sqlite.setMeta(kPrefsMigrationMetaKey, '1');
    dev.log(
      'AppPersistence: PrefsStore -> SQLite migration complete '
      '($migratedStats lang(s) of stats, ${unflushed.length} analytics event(s))',
      name: 'AppPersistence',
    );
  } catch (e, st) {
    dev.log(
      'AppPersistence: PrefsStore -> SQLite migration failed (non-fatal, '
      'proceeding on the fresh SqliteStore): $e',
      name: 'AppPersistence',
      error: e,
      stackTrace: st,
    );
  }
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
      await migratePrefsIntoSqliteIfNeeded(store);
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

    // Earned streak-freeze grant: every streakFreezeMilestoneDays-day streak
    // milestone earns one freeze, capped at maxStreakFreezes held. Gated on
    // the streak actually just changing (excludes updateStreak's diff==0
    // idempotent-replay path) so replaying the same day's win never
    // double-grants.
    final justReachedMilestone = streak.currentStreak != current.currentStreak &&
        streak.currentStreak > 0 &&
        streak.currentStreak % streakFreezeMilestoneDays == 0;
    final freezes = justReachedMilestone
        ? (current.streakFreezes + 1).clamp(0, maxStreakFreezes)
        : current.streakFreezes;

    final updated = current.copyWith(
      played: current.played + 1,
      wins: current.wins + 1,
      currentStreak: streak.currentStreak,
      maxStreak: streak.maxStreak,
      guessDistribution: dist,
      streakFreezes: freezes,
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

  /// Passive streak check called on Stats screen open — folds in the earned
  /// streak-freeze mechanic (see [streakFreezeMilestoneDays]/
  /// [maxStreakFreezes]) so callers no longer orchestrate freeze consumption
  /// separately against an IAP gateway.
  ///
  /// - Streak already 0, no prior win, or gap <= 1 day: no-op.
  /// - Gap of EXACTLY 2 days (one missed day) AND a freeze is held: spend
  ///   one freeze, PRESERVE [PlayerStats.currentStreak], `rescued: true`. A
  ///   freeze protects a single missed day, not an extended absence.
  /// - Any larger gap, or no freeze held: reset [PlayerStats.currentStreak]
  ///   to 0, `rescued: false` — same unconditional reset as before the
  ///   freeze mechanic existed.
  ///
  /// Persists the resulting stats in either the rescue or reset branch.
  Future<StreakRescueResult> rescueStreakOrReset({
    required String lang,
    required DateTime today,
  }) async {
    final current = await loadStats(lang);
    if (current.currentStreak == 0) {
      return StreakRescueResult(stats: current, rescued: false);
    }

    final lastWin = await loadLastWinDate(lang);
    if (lastWin == null) {
      return StreakRescueResult(stats: current, rescued: false);
    }

    final todayNorm = DateTime(today.year, today.month, today.day);
    final lastNorm = DateTime(lastWin.year, lastWin.month, lastWin.day);
    final gapDays = todayNorm.difference(lastNorm).inDays;
    if (gapDays <= 1) {
      return StreakRescueResult(stats: current, rescued: false);
    }

    if (gapDays == 2 && current.streakFreezes > 0) {
      final rescued = current.copyWith(streakFreezes: current.streakFreezes - 1);
      // Bridge lastWinDate to "yesterday" (todayNorm - 1), NOT the original
      // lastWin: this makes the missed day look covered. Critical for
      // correctness — if a subsequent real win today calls recordWin() and
      // it still sees the ORIGINAL (2-days-stale) lastWinDate, updateStreak
      // computes diff=2 and resets the very streak this rescue just saved.
      // Bridging to todayNorm-1 makes that follow-up win see diff=1 and
      // extend the streak normally, exactly as if the missed day had been
      // played.
      final bridgedLastWin = todayNorm.subtract(const Duration(days: 1));
      await _store.saveStats(lang, rescued, bridgedLastWin);
      return StreakRescueResult(stats: rescued, rescued: true);
    }

    final reset = current.copyWith(currentStreak: 0);
    await _store.saveStats(lang, reset, null);
    return StreakRescueResult(stats: reset, rescued: false);
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

