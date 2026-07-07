/// shared_preferences-backed [StorageBackend] — web fallback when WASM SQLite fails.
///
/// Storage layout (all keys prefixed "mm_"):
///
///   mm_day_{date}_{lang}                 → JSON object: DayState fields
///   mm_stats_{lang}                      → JSON object: PlayerStats + last_win_date
///   mm_analytics                         → JSON array: up to [_kMaxRows] event objects
///   mm_pack_{packId}__{lang}__{idx}      → JSON object: PackPuzzleState fields
///     (phase 6c; stored separately from mm_day_*/mm_stats_* so pack play can
///     never affect the daily streak — see [AppPersistence] class doc).
///
/// Analytics ring buffer:
///   Each event is a JSON object with keys:
///     id          — auto-incrementing int (persisted in mm_analytics_next_id)
///     event_name  — String
///     props_json  — String (JSON-encoded Map)
///     ts          — int (milliseconds since epoch)
///     flushed     — int (0 or 1)
///
///   The buffer is capped at [_kMaxRows] (500) entries; oldest are dropped
///   on insert.  The full list is stored as a single prefs key so atomic
///   read-modify-write is possible without a real DB transaction.
library;

import 'dart:convert';
import 'dart:developer' as dev;

import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/storage_backend.dart';
import 'package:shared_preferences/shared_preferences.dart';

class PrefsStore implements StorageBackend {
  PrefsStore();

  SharedPreferences? _prefs;

  static const int _kMaxRows = 500;

  static const String _kNextIdKey = 'mm_analytics_next_id';
  static const String _kAnalyticsKey = 'mm_analytics';

  @override
  StorageBackendKind get kind => StorageBackendKind.prefs;

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------

  @override
  Future<void> init({String? dbPath}) async {
    if (_prefs != null) return;
    _prefs = await SharedPreferences.getInstance();
    dev.log('PrefsStore: initialised (web SQLite fallback active)',
        name: 'PrefsStore');
  }

  @override
  Future<void> close() async {
    // shared_preferences has no explicit close; just release the reference.
    _prefs = null;
  }

  SharedPreferences get _p {
    if (_prefs == null) {
      throw StateError('PrefsStore not initialised. Call init() first.');
    }
    return _prefs!;
  }

  // ---------------------------------------------------------------------------
  // Day state
  // ---------------------------------------------------------------------------

  static String _dayKey(String date, String lang) => 'mm_day_${date}_$lang';

  @override
  Future<DayState?> loadDayState(String date, String lang) async {
    final raw = _p.getString(_dayKey(date, lang));
    if (raw == null) return null;
    try {
      final m = jsonDecode(raw) as Map<String, dynamic>;
      return _dayStateFromMap(m, date, lang);
    } catch (e) {
      dev.log('PrefsStore.loadDayState decode error: $e', name: 'PrefsStore');
      return null;
    }
  }

  @override
  Future<void> saveDayState(DayState state) async {
    final m = _dayStateToMap(state);
    await _p.setString(_dayKey(state.date, state.lang), jsonEncode(m));
  }

  Map<String, dynamic> _dayStateToMap(DayState s) => {
        'guesses': s.guesses.map(_guessToJson).toList(),
        'hints_used': s.hintsUsed,
        'won': s.won,
        'gave_up': s.gaveUp,
        'revealed_hints': s.revealedHints.map(_revealedHintToJson).toList(),
      };

  DayState _dayStateFromMap(Map<String, dynamic> m, String date, String lang) {
    final rawGuesses = m['guesses'] as List<dynamic>;
    final guesses = rawGuesses.map(_guessFromJson).toList();
    final rawHints = m['revealed_hints'] as List<dynamic>? ?? [];
    final revealedHints = rawHints.map(_revealedHintFromJson).toList();
    return DayState(
      date: date,
      lang: lang,
      guesses: guesses,
      hintsUsed: (m['hints_used'] as num).toInt(),
      won: m['won'] as bool,
      gaveUp: m['gave_up'] as bool,
      revealedHints: revealedHints,
    );
  }

  // ---------------------------------------------------------------------------
  // Themed-pack progress (phase 6c) — see class doc for the isolation invariant.
  // ---------------------------------------------------------------------------

  static String _packKeyPrefix(String packId, String lang) =>
      'mm_pack_${packId}__${lang}__';

  static String _packKey(String packId, int idx, String lang) =>
      '${_packKeyPrefix(packId, lang)}$idx';

  @override
  Future<PackPuzzleState?> loadPackState(
      String packId, int idx, String lang) async {
    final raw = _p.getString(_packKey(packId, idx, lang));
    if (raw == null) return null;
    try {
      final m = jsonDecode(raw) as Map<String, dynamic>;
      return _packStateFromMap(m, packId, idx, lang);
    } catch (e) {
      dev.log('PrefsStore.loadPackState decode error: $e', name: 'PrefsStore');
      return null;
    }
  }

  @override
  Future<void> savePackState(PackPuzzleState state) async {
    final m = {
      'guesses': state.guesses.map(_guessToJson).toList(),
      'hints_used': state.hintsUsed,
      'won': state.won,
      'gave_up': state.gaveUp,
      'revealed_hints': state.revealedHints.map(_revealedHintToJson).toList(),
    };
    await _p.setString(
      _packKey(state.packId, state.idx, state.lang),
      jsonEncode(m),
    );
  }

  @override
  Future<List<PackPuzzleState>> loadPackStatesForPack(
      String packId, String lang) async {
    final prefix = _packKeyPrefix(packId, lang);
    final keys = _p.getKeys().where((k) => k.startsWith(prefix));
    final states = <PackPuzzleState>[];
    for (final key in keys) {
      final idx = int.tryParse(key.substring(prefix.length));
      if (idx == null) continue;
      final raw = _p.getString(key);
      if (raw == null) continue;
      try {
        final m = jsonDecode(raw) as Map<String, dynamic>;
        states.add(_packStateFromMap(m, packId, idx, lang));
      } catch (e) {
        dev.log('PrefsStore.loadPackStatesForPack decode error: $e',
            name: 'PrefsStore');
      }
    }
    return states;
  }

  PackPuzzleState _packStateFromMap(
    Map<String, dynamic> m,
    String packId,
    int idx,
    String lang,
  ) {
    final rawGuesses = m['guesses'] as List<dynamic>;
    final guesses = rawGuesses.map(_guessFromJson).toList();
    final rawHints = m['revealed_hints'] as List<dynamic>? ?? [];
    final revealedHints = rawHints.map(_revealedHintFromJson).toList();
    return PackPuzzleState(
      packId: packId,
      idx: idx,
      lang: lang,
      guesses: guesses,
      hintsUsed: (m['hints_used'] as num).toInt(),
      won: m['won'] as bool,
      gaveUp: m['gave_up'] as bool,
      revealedHints: revealedHints,
    );
  }

  // ---------------------------------------------------------------------------
  // Stats
  // ---------------------------------------------------------------------------

  static String _statsKey(String lang) => 'mm_stats_$lang';

  @override
  Future<PlayerStats> loadStats(String lang) async {
    final raw = _p.getString(_statsKey(lang));
    if (raw == null) return PlayerStats.empty;
    try {
      final m = jsonDecode(raw) as Map<String, dynamic>;
      final distRaw = m['dist'] as Map<String, dynamic>? ?? {};
      return PlayerStats(
        played: (m['played'] as num).toInt(),
        wins: (m['wins'] as num).toInt(),
        currentStreak: (m['current_streak'] as num).toInt(),
        maxStreak: (m['max_streak'] as num).toInt(),
        guessDistribution: distRaw.map((k, v) => MapEntry(k, (v as num).toInt())),
      );
    } catch (e) {
      dev.log('PrefsStore.loadStats decode error: $e', name: 'PrefsStore');
      return PlayerStats.empty;
    }
  }

  @override
  Future<DateTime?> loadLastWinDate(String lang) async {
    final raw = _p.getString(_statsKey(lang));
    if (raw == null) return null;
    try {
      final m = jsonDecode(raw) as Map<String, dynamic>;
      final lwd = m['last_win_date'] as String?;
      if (lwd == null) return null;
      return DateTime.tryParse(lwd);
    } catch (_) {
      return null;
    }
  }

  @override
  Future<void> saveStats(
    String lang,
    PlayerStats stats,
    DateTime? lastWinDate,
  ) async {
    final m = {
      'played': stats.played,
      'wins': stats.wins,
      'current_streak': stats.currentStreak,
      'max_streak': stats.maxStreak,
      'last_win_date': lastWinDate?.toIso8601String(),
      'dist': stats.guessDistribution,
    };
    await _p.setString(_statsKey(lang), jsonEncode(m));
  }

  // ---------------------------------------------------------------------------
  // Analytics ring buffer
  // ---------------------------------------------------------------------------

  List<Map<String, dynamic>> _loadBuffer() {
    final raw = _p.getString(_kAnalyticsKey);
    if (raw == null) return [];
    try {
      return (jsonDecode(raw) as List<dynamic>)
          .cast<Map<String, dynamic>>()
          .toList();
    } catch (_) {
      return [];
    }
  }

  Future<void> _saveBuffer(List<Map<String, dynamic>> rows) async {
    await _p.setString(_kAnalyticsKey, jsonEncode(rows));
  }

  int _nextId() {
    final current = _p.getInt(_kNextIdKey) ?? 0;
    final next = current + 1;
    _p.setInt(_kNextIdKey, next);
    return next;
  }

  @override
  Future<void> logEvent(String name, Map<String, dynamic> props) async {
    final buf = _loadBuffer();
    final id = _nextId();
    buf.add({
      'id': id,
      'event_name': name,
      'props_json': jsonEncode(props),
      'ts': DateTime.now().millisecondsSinceEpoch,
      'flushed': 0,
    });
    // Enforce cap: keep only the newest _kMaxRows rows.
    final capped = buf.length > _kMaxRows
        ? buf.sublist(buf.length - _kMaxRows)
        : buf;
    await _saveBuffer(capped);
  }

  @override
  Future<List<Map<String, dynamic>>> exportAnalyticsBuffer() async {
    return _loadBuffer();
  }

  @override
  Future<List<Map<String, dynamic>>> exportUnflushedEvents(
      {int limit = 500}) async {
    final all = _loadBuffer().where((r) => (r['flushed'] as int) == 0).toList();
    return all.length > limit ? all.sublist(0, limit) : all;
  }

  @override
  Future<void> markEventsFlushed(List<int> ids) async {
    if (ids.isEmpty) return;
    final idSet = ids.toSet();
    final buf = _loadBuffer().map((r) {
      if (idSet.contains(r['id'] as int)) {
        return {...r, 'flushed': 1};
      }
      return r;
    }).toList();
    await _saveBuffer(buf);
  }

  @override
  Future<void> clearAll() async {
    final keys = _p.getKeys().where((k) => k.startsWith('mm_')).toList();
    for (final k in keys) {
      await _p.remove(k);
    }
  }

  // ---------------------------------------------------------------------------
  // Serialisation helpers (shared with SqliteStore shape for compatibility)
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
      rank: (m['rank'] as num).toInt(),
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
    return RevealedHint(
        rank: (m['rank'] as num).toInt(), word: m['word'] as String);
  }
}
