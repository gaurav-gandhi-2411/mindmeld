/// Abstract storage backend interface for Mindmeld persistence.
///
/// Two concrete implementations exist:
///   - [SqliteStore] — SQLite/IndexedDB via sqflite_common_ffi_web (default).
///   - [PrefsStore] — JSON blobs in shared_preferences (web fallback when WASM fails).
///
/// The interface is narrow: only the operations [AppPersistence] exposes publicly.
/// Internal helpers (serialisers, schema migrations) stay in the concrete impls.
library;

import 'package:mindmeld/core/models.dart';

/// Identifies which storage backend is active.
enum StorageBackendKind { sqlite, prefs, memory }

/// Narrow persistence contract used by [AppPersistence].
///
/// All methods are async; implementations may use any underlying store.
abstract class StorageBackend {
  /// Which backend flavour this instance represents.
  StorageBackendKind get kind;

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------

  /// Initialise the backend (open DB / prefs, run migrations, etc.).
  Future<void> init({String? dbPath});

  /// Release resources (close DB file handle). No-op on prefs backend.
  Future<void> close();

  // ---------------------------------------------------------------------------
  // Day state
  // ---------------------------------------------------------------------------

  /// Load the persisted game state for [date] + [lang], or null if absent.
  Future<DayState?> loadDayState(String date, String lang);

  /// Persist (upsert) [state] for its (date, lang) key.
  Future<void> saveDayState(DayState state);

  // ---------------------------------------------------------------------------
  // Stats
  // ---------------------------------------------------------------------------

  /// Load aggregated player statistics for [lang].
  ///
  /// Returns [PlayerStats.empty] when no rows exist yet.
  Future<PlayerStats> loadStats(String lang);

  /// Load the ISO-8601 date of the last win for [lang], or null if never won.
  Future<DateTime?> loadLastWinDate(String lang);

  /// Persist [stats] and (optionally) a new [lastWinDate] for [lang].
  Future<void> saveStats(String lang, PlayerStats stats, DateTime? lastWinDate);

  // ---------------------------------------------------------------------------
  // Analytics ring buffer
  // ---------------------------------------------------------------------------

  /// Append an analytics event and enforce the 500-row ring-buffer cap.
  Future<void> logEvent(String name, Map<String, dynamic> props);

  /// Return ALL buffered events ordered by insertion (oldest first).
  Future<List<Map<String, dynamic>>> exportAnalyticsBuffer();

  /// Return only events where `flushed = 0`, up to [limit] rows.
  Future<List<Map<String, dynamic>>> exportUnflushedEvents({int limit = 500});

  /// Mark the given event [ids] as flushed.
  Future<void> markEventsFlushed(List<int> ids);

  // ---------------------------------------------------------------------------
  // Reset
  // ---------------------------------------------------------------------------

  /// Delete ALL game data: day states, stats, analytics.
  ///
  /// Used by the ?reset=1 developer hook to simulate a first-time user.
  Future<void> clearAll();
}
