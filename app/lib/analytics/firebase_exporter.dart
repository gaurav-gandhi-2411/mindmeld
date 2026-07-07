/// Firebase Analytics + Crashlytics exporter.
///
/// ## Architecture
///
/// Mirrors the thin-client injection pattern from [rewarded_ad_service.dart] and
/// [revenuecat_gateway.dart]:
///
///   - [AnalyticsExporter] — abstract interface the rest of the app uses.
///   - [FirebaseExporter] — real implementation; wraps an [AnalyticsClient] that
///     is the only place firebase_analytics / firebase_crashlytics SDK calls live.
///   - [_NoOpExporter] — returned by [buildAnalyticsExporter] when
///     [AppConfig.analyticsEnabled] is false; touches no platform channels.
///   - [buildAnalyticsExporter] — factory keyed on [AppConfig.analyticsEnabled].
///
/// ## Flush semantics
///
/// Events ALWAYS write to the local SQLite ring buffer first (offline queue,
/// handled by [AppPersistence.logEvent]).  When [AppConfig.analyticsEnabled] is
/// true, a flush loop drains unflushed events to Firebase:
///
///   - On [init] (app start).
///   - After each successful [logEvent] call: on web, every event triggers an
///     immediate flush (tabs are usually closed rather than backgrounded, so
///     [onResume] can't be relied on to ever fire). On native platforms, a
///     flush triggers once the unflushed count reaches a multiple of
///     [_kFlushBatchSize] (10), since [onResume] reliably fires there.
///   - On [onResume] (lifecycle hook — wired in main.dart via [WidgetsBinding]).
///
/// Failed flushes (client throws) leave events in the ring buffer with
/// `flushed = 0` so the next cycle retries them.  Successfully flushed events
/// are marked `flushed = 1` and are never re-sent.
///
/// ## Param normalisation
///
/// Every event receives two mandatory params before forwarding to Firebase:
///   - `lang`: taken from the event props if already present; otherwise left
///     as-is (callers that carry lang already pass it through).
///   - `day`: ISO-8601 date of the event derived from the stored [ts] column
///     (milliseconds since epoch → DateFormat('yyyy-MM-dd')).
library;

import 'dart:async';
import 'dart:convert';
import 'dart:developer' as dev;

import 'package:firebase_analytics/firebase_analytics.dart';
import 'package:firebase_crashlytics/firebase_crashlytics.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:intl/intl.dart';
import 'package:mindmeld/core/config.dart';
import 'package:mindmeld/core/persistence.dart';

// ---------------------------------------------------------------------------
// Flush batch size
// ---------------------------------------------------------------------------

/// Number of events that triggers a proactive flush.
///
/// A flush is triggered after each [logEvent] call if the total number of
/// unflushed events is a non-zero multiple of this value.
const int _kFlushBatchSize = 10;

// ---------------------------------------------------------------------------
// AnalyticsExporter interface
// ---------------------------------------------------------------------------

/// Abstract interface for sending analytics events to a remote backend.
///
/// Callers depend only on this interface; the concrete implementation is
/// hidden behind [buildAnalyticsExporter].
abstract class AnalyticsExporter {
  /// Log [name] with optional [props] to the local ring buffer AND (when
  /// enabled) trigger a batch flush to the remote backend.
  ///
  /// Always writes locally first so events survive offline periods.
  Future<void> logEvent(String name, [Map<String, dynamic>? props]);

  /// Record a [FlutterError] / unhandled [Object] to Crashlytics.
  ///
  /// No-op in the [_NoOpExporter] / when [AppConfig.analyticsEnabled] is false.
  Future<void> recordError(Object error, StackTrace? stack, {bool fatal = false});

  /// Initialise the exporter and run the first flush cycle.
  ///
  /// Call once from [main] after [Firebase.initializeApp] (when enabled) or
  /// immediately (no-op path).
  Future<void> init();

  /// Trigger a flush — call from [AppLifecycleListener.onResume].
  Future<void> onResume();
}

// ---------------------------------------------------------------------------
// Thin-client interface (injectable for tests)
// ---------------------------------------------------------------------------

/// Thin wrapper interface around the Firebase Analytics + Crashlytics SDKs.
///
/// Tests inject a [FakeAnalyticsClient]; production supplies [defaultAnalyticsClient].
/// This decouples all firebase_* platform channels from host tests.
abstract class AnalyticsClient {
  /// Forward a single event to Firebase Analytics.
  ///
  /// [name] must conform to Firebase naming rules (≤ 40 chars, alphanumeric +
  /// underscore, must start with a letter — callers are responsible for clean names).
  /// [parameters] values must be [String] or [num].
  Future<void> logEvent(String name, Map<String, Object> parameters);

  /// Record a non-fatal error to Firebase Crashlytics.
  Future<void> recordError(
    Object exception,
    StackTrace? stack, {
    bool fatal = false,
  });
}

// ---------------------------------------------------------------------------
// Production AnalyticsClient implementation
// ---------------------------------------------------------------------------

/// Production [AnalyticsClient] that calls the real Firebase SDKs.
///
/// This is the ONLY place in the codebase that calls [FirebaseAnalytics] or
/// [FirebaseCrashlytics] methods.  Tests never instantiate this class.
class _LiveAnalyticsClient implements AnalyticsClient {
  @override
  Future<void> logEvent(String name, Map<String, Object> parameters) {
    return FirebaseAnalytics.instance.logEvent(
      name: name,
      parameters: parameters,
    );
  }

  @override
  Future<void> recordError(
    Object exception,
    StackTrace? stack, {
    bool fatal = false,
  }) {
    return FirebaseCrashlytics.instance.recordError(
      exception,
      stack,
      fatal: fatal,
    );
  }
}

/// Production [AnalyticsClient] singleton.
final AnalyticsClient defaultAnalyticsClient = _LiveAnalyticsClient();

// ---------------------------------------------------------------------------
// FirebaseExporter
// ---------------------------------------------------------------------------

/// [AnalyticsExporter] backed by Firebase Analytics + Crashlytics.
///
/// Construct via [buildAnalyticsExporter] rather than directly.
class FirebaseExporter implements AnalyticsExporter {
  FirebaseExporter({
    AppPersistence? persistence,
    AnalyticsClient? client,
  })  : _persistence = persistence ?? AppPersistence.instance,
        _client = client ?? defaultAnalyticsClient;

  final AppPersistence _persistence;
  final AnalyticsClient _client;

  // Guard against concurrent flushes.
  bool _flushing = false;

  // ---------------------------------------------------------------------------
  // AnalyticsExporter interface
  // ---------------------------------------------------------------------------

  @override
  Future<void> init() => _flush();

  @override
  Future<void> onResume() => _flush();

  @override
  Future<void> logEvent(String name, [Map<String, dynamic>? props]) async {
    // Always write to local ring buffer first — offline queue.
    await _persistence.logEvent(name, props ?? {});

    // Trigger a proactive flush. On web, flush every event: browser tabs are
    // usually closed outright rather than backgrounded, so [onResume] often
    // never fires and a batch-of-10 threshold would silently drop most short
    // sessions' events. Native platforms keep the battery/network-friendly
    // batch-of-[_kFlushBatchSize] behavior since [onResume] reliably fires
    // when the OS backgrounds/foregrounds the app.
    final unflushed = await _persistence.exportUnflushedEvents();
    final shouldFlush = kIsWeb
        ? unflushed.isNotEmpty
        : unflushed.length % _kFlushBatchSize == 0 && unflushed.isNotEmpty;
    if (shouldFlush) {
      await _flush();
    }
  }

  @override
  Future<void> recordError(
    Object error,
    StackTrace? stack, {
    bool fatal = false,
  }) async {
    try {
      await _client.recordError(error, stack, fatal: fatal);
    } catch (e) {
      dev.log(
        'FirebaseExporter.recordError failed: $e',
        name: 'FirebaseExporter',
      );
    }
  }

  // ---------------------------------------------------------------------------
  // Flush implementation
  // ---------------------------------------------------------------------------

  /// Drain unflushed events from the ring buffer to Firebase Analytics.
  ///
  /// Idempotent and re-entrant-safe: concurrent calls are coalesced into one
  /// in-flight flush via the [_flushing] guard.  Failed sends leave events
  /// with `flushed = 0` so the next cycle retries.
  Future<void> _flush() async {
    if (_flushing) return;
    _flushing = true;
    try {
      final rows = await _persistence.exportUnflushedEvents();
      if (rows.isEmpty) return;

      final flushedIds = <int>[];

      for (final row in rows) {
        final id = row['id'] as int;
        final name = row['event_name'] as String;
        final propsRaw = jsonDecode(row['props_json'] as String) as Map<String, dynamic>;
        final ts = row['ts'] as int;

        // Normalise: attach day derived from stored timestamp.
        final day = DateFormat('yyyy-MM-dd').format(
          DateTime.fromMillisecondsSinceEpoch(ts),
        );
        final params = _normaliseParams(propsRaw, day: day);

        try {
          await _client.logEvent(name, params);
          flushedIds.add(id);
        } catch (e) {
          // One event fails → stop this batch; mark already-sent ones as flushed.
          dev.log(
            'FirebaseExporter: failed to send event "$name" (id=$id): $e',
            name: 'FirebaseExporter',
          );
          break;
        }
      }

      if (flushedIds.isNotEmpty) {
        await _persistence.markEventsFlushed(flushedIds);
      }
    } catch (e) {
      dev.log('FirebaseExporter._flush error: $e', name: 'FirebaseExporter');
    } finally {
      _flushing = false;
    }
  }

  /// Convert raw props to a [Map<String, Object>] suitable for Firebase.
  ///
  /// Firebase Analytics only accepts [String] and [num] parameter values.
  /// Booleans are coerced to int (1/0) — Firebase does not natively support bool.
  /// The [day] param is injected if not already present.
  static Map<String, Object> _normaliseParams(
    Map<String, dynamic> raw, {
    required String day,
  }) {
    final out = <String, Object>{};

    for (final entry in raw.entries) {
      final v = entry.value;
      if (v is String) {
        out[entry.key] = v;
      } else if (v is num) {
        out[entry.key] = v;
      } else if (v is bool) {
        // Firebase does not accept bool — coerce to 0/1.
        out[entry.key] = v ? 1 : 0;
      } else if (v != null) {
        // Fallback: stringify complex values (lists, maps).
        out[entry.key] = v.toString();
      }
    }

    // Always attach day; caller-supplied value wins if present.
    out.putIfAbsent('day', () => day);

    return out;
  }
}

// ---------------------------------------------------------------------------
// No-op exporter (analyticsEnabled = false)
// ---------------------------------------------------------------------------

/// [AnalyticsExporter] that writes to the local ring buffer only.
///
/// Returned by [buildAnalyticsExporter] when [AppConfig.analyticsEnabled] is
/// false.  Zero Firebase SDK calls are made in this path.
class _NoOpExporter implements AnalyticsExporter {
  const _NoOpExporter(this._persistence);

  final AppPersistence _persistence;

  @override
  Future<void> init() async {}

  @override
  Future<void> onResume() async {}

  @override
  Future<void> logEvent(String name, [Map<String, dynamic>? props]) async {
    await _persistence.logEvent(name, props ?? {});
  }

  @override
  Future<void> recordError(
    Object error,
    StackTrace? stack, {
    bool fatal = false,
  }) async {
    // No-op: Crashlytics not wired when analyticsEnabled=false.
  }
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/// Construct the appropriate [AnalyticsExporter] for the current build
/// configuration.
///
/// - [AppConfig.analyticsEnabled] = true  → [FirebaseExporter]
/// - [AppConfig.analyticsEnabled] = false → [_NoOpExporter] (ring-buffer only)
///
/// The optional [client] and [persistence] parameters allow tests to inject
/// fakes without touching dart-defines.
AnalyticsExporter buildAnalyticsExporter({
  AnalyticsClient? client,
  AppPersistence? persistence,
}) {
  final db = persistence ?? AppPersistence.instance;
  if (AppConfig.analyticsEnabled) {
    return FirebaseExporter(persistence: db, client: client);
  }
  return _NoOpExporter(db);
}
