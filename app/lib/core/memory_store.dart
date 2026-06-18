library;

import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/storage_backend.dart';

/// In-memory fallback storage backend.
///
/// Used when both SQLite/WASM and SharedPreferences are unavailable
/// (e.g. private browsing mode with storage disabled). Game state is
/// preserved for the session but lost on page close.
class MemoryStore implements StorageBackend {
  final Map<String, DayState> _days = {};
  final Map<String, _StatsRow> _stats = {};
  final List<Map<String, dynamic>> _analytics = [];
  int _nextId = 0;

  static const int _kMaxRows = 500;

  @override
  StorageBackendKind get kind => StorageBackendKind.memory;

  @override
  Future<void> init({String? dbPath}) async {}

  @override
  Future<void> close() async {
    _days.clear();
    _stats.clear();
    _analytics.clear();
  }

  @override
  Future<DayState?> loadDayState(String date, String lang) async =>
      _days['${date}_$lang'];

  @override
  Future<void> saveDayState(DayState state) async {
    _days['${state.date}_${state.lang}'] = state;
  }

  @override
  Future<PlayerStats> loadStats(String lang) async =>
      _stats[lang]?.stats ?? PlayerStats.empty;

  @override
  Future<DateTime?> loadLastWinDate(String lang) async =>
      _stats[lang]?.lastWinDate;

  @override
  Future<void> saveStats(
      String lang, PlayerStats stats, DateTime? lastWinDate) async {
    _stats[lang] = _StatsRow(stats: stats, lastWinDate: lastWinDate);
  }

  @override
  Future<void> logEvent(String name, Map<String, dynamic> props) async {
    _nextId++;
    _analytics.add({
      'id': _nextId,
      'event_name': name,
      'props_json': props.toString(),
      'ts': DateTime.now().millisecondsSinceEpoch,
      'flushed': 0,
    });
    if (_analytics.length > _kMaxRows) {
      _analytics.removeAt(0);
    }
  }

  @override
  Future<List<Map<String, dynamic>>> exportAnalyticsBuffer() async =>
      List.unmodifiable(_analytics);

  @override
  Future<List<Map<String, dynamic>>> exportUnflushedEvents(
      {int limit = 500}) async {
    final unflushed =
        _analytics.where((r) => (r['flushed'] as int) == 0).toList();
    return unflushed.length > limit ? unflushed.sublist(0, limit) : unflushed;
  }

  @override
  Future<void> markEventsFlushed(List<int> ids) async {
    final idSet = ids.toSet();
    for (var i = 0; i < _analytics.length; i++) {
      if (idSet.contains(_analytics[i]['id'] as int)) {
        _analytics[i] = {..._analytics[i], 'flushed': 1};
      }
    }
  }

  @override
  Future<void> clearAll() async {
    _days.clear();
    _stats.clear();
    _analytics.clear();
    _nextId = 0;
  }
}

class _StatsRow {
  const _StatsRow({required this.stats, this.lastWinDate});
  final PlayerStats stats;
  final DateTime? lastWinDate;
}
