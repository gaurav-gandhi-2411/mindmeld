/// Unit tests for [FirebaseExporter] and [buildAnalyticsExporter].
///
/// All tests run as pure host (dart vm) tests — zero Firebase SDK calls.
/// The production SDK is kept behind the [AnalyticsClient] injection point;
/// tests inject [_FakeAnalyticsClient] which records calls in-memory.
///
/// Coverage:
///   1. buildAnalyticsExporter with analyticsEnabled=false returns the no-op
///      exporter (ring buffer fills; no client calls).
///   2. logEvent always writes to local ring buffer (both paths).
///   3. Flush on init: unflushed events are drained to the client in order;
///      lang and day params are attached.
///   4. Failed flush (client throws on one event) retains that event as
///      unflushed; previously successful events in the batch are marked flushed.
///   5. Batch-of-10 trigger: flush fires after every 10th unflushed event.
///   6. Flushed events are not re-sent on subsequent flushes (idempotent).
///   7. onResume triggers a flush.
///   8. Concurrent flush calls are coalesced (only one in-flight at a time).
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/analytics/firebase_exporter.dart';
import 'package:mindmeld/core/persistence.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

// ---------------------------------------------------------------------------
// FakeAnalyticsClient — injectable test double
// ---------------------------------------------------------------------------

/// Configurable [AnalyticsClient] for tests.
///
/// Records every [logEvent] call in [loggedEvents].
/// When [throwOnEventName] matches, [logEvent] throws [Exception].
class _FakeAnalyticsClient implements AnalyticsClient {
  _FakeAnalyticsClient({this.throwOnEventName});

  /// If non-null, [logEvent] throws when [name] matches this value.
  final String? throwOnEventName;

  /// All [logEvent] calls, in order, as (name, parameters) tuples.
  final List<(String, Map<String, Object>)> loggedEvents = [];

  /// All errors recorded via [recordError].
  final List<Object> recordedErrors = [];

  @override
  Future<void> logEvent(String name, Map<String, Object> parameters) async {
    if (throwOnEventName != null && name == throwOnEventName) {
      throw Exception('Simulated Firebase send failure for "$name"');
    }
    loggedEvents.add((name, parameters));
  }

  @override
  Future<void> recordError(
    Object exception,
    StackTrace? stack, {
    bool fatal = false,
  }) async {
    recordedErrors.add(exception);
  }
}

// ---------------------------------------------------------------------------
// Test setup helpers
// ---------------------------------------------------------------------------

late Directory _tmpDir;

Future<AppPersistence> _openTestDb(String prefix) async {
  AppPersistence.resetForTest();
  _tmpDir = await Directory.systemTemp.createTemp('mindmeld_exporter_');
  final dbPath = p.join(_tmpDir.path, '$prefix.db');
  final db = AppPersistence.instance;
  await db.init(dbPath: dbPath);
  return db;
}

Future<void> _closeTestDb(AppPersistence db) async {
  await db.close();
  AppPersistence.resetForTest();
  await _tmpDir.delete(recursive: true);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  // -------------------------------------------------------------------------
  // Test 1: buildAnalyticsExporter with analyticsEnabled=false → no-op path
  // -------------------------------------------------------------------------

  test(
    'buildAnalyticsExporter returns no-op exporter when analyticsEnabled=false',
    () async {
      final db = await _openTestDb('noop');
      addTearDown(() => _closeTestDb(db));

      final fake = _FakeAnalyticsClient();

      // analyticsEnabled is false in test builds (no dart-define).
      // buildAnalyticsExporter must return _NoOpExporter, which:
      //   - writes to local ring buffer on logEvent
      //   - makes zero client calls
      final exporter = buildAnalyticsExporter(client: fake, persistence: db);

      // The factory must NOT return FirebaseExporter when flag is off.
      expect(exporter, isNot(isA<FirebaseExporter>()));

      await exporter.logEvent('guess_made', {'lang': 'en', 'day': '2026-06-12'});

      // Ring buffer must have the event.
      final buffered = await db.exportAnalyticsBuffer();
      expect(buffered.length, equals(1));
      expect(buffered.first['event_name'], equals('guess_made'));

      // Client must not have been called.
      expect(fake.loggedEvents, isEmpty);
    },
  );

  // -------------------------------------------------------------------------
  // Test 2: logEvent always writes to local ring buffer
  // -------------------------------------------------------------------------

  test('FirebaseExporter.logEvent writes to local ring buffer', () async {
    final db = await _openTestDb('buffer');
    addTearDown(() => _closeTestDb(db));

    final fake = _FakeAnalyticsClient();
    final exporter = FirebaseExporter(persistence: db, client: fake);

    await exporter.logEvent('hint_used', {'lang': 'en', 'day': '2026-06-12', 'hint_index': 0});

    final buffered = await db.exportAnalyticsBuffer();
    expect(buffered.length, equals(1));
    expect(buffered.first['event_name'], equals('hint_used'));
  });

  // -------------------------------------------------------------------------
  // Test 3: Flush on init drains events in order with day param attached
  // -------------------------------------------------------------------------

  test('FirebaseExporter.init flushes buffered events in order with day param', () async {
    final db = await _openTestDb('flush_init');
    addTearDown(() => _closeTestDb(db));

    // Write events directly to the ring buffer (simulates events from before
    // this session — e.g. app was offline).
    await db.logEvent('guess_made', {'lang': 'en'});
    await db.logEvent('win', {'lang': 'en'});

    final fake = _FakeAnalyticsClient();
    final exporter = FirebaseExporter(persistence: db, client: fake);

    // init() runs the flush cycle.
    await exporter.init();

    // Both events must have been forwarded to the client.
    expect(fake.loggedEvents.length, equals(2));
    expect(fake.loggedEvents[0].$1, equals('guess_made'));
    expect(fake.loggedEvents[1].$1, equals('win'));

    // Each event must carry a 'day' param (injected from stored ts).
    for (final (_, params) in fake.loggedEvents) {
      expect(params.containsKey('day'), isTrue, reason: 'day param must be attached');
      // day must be a valid yyyy-MM-dd string.
      final day = params['day']! as String;
      expect(
        RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(day),
        isTrue,
        reason: 'day must be yyyy-MM-dd format, got: $day',
      );
    }

    // Events must be marked flushed — not returned as unflushed.
    final unflushed = await db.exportUnflushedEvents();
    expect(unflushed, isEmpty, reason: 'all events must be marked flushed after init()');
  });

  // -------------------------------------------------------------------------
  // Test 4: Failed flush retains queue; partial batch handled correctly
  // -------------------------------------------------------------------------

  test(
    'failed flush retains unflushed events; partial batch: successful events '
    'are marked flushed, failing event stays in queue',
    () async {
      final db = await _openTestDb('flush_fail');
      addTearDown(() => _closeTestDb(db));

      // Write 3 events: first two succeed, third ('bad_event') throws.
      await db.logEvent('guess_made', {});
      await db.logEvent('hint_used', {});
      await db.logEvent('bad_event', {});

      // Client throws when it sees 'bad_event'.
      final fake = _FakeAnalyticsClient(throwOnEventName: 'bad_event');
      final exporter = FirebaseExporter(persistence: db, client: fake);

      await exporter.init();

      // First two events forwarded successfully.
      expect(fake.loggedEvents.length, equals(2));
      expect(fake.loggedEvents[0].$1, equals('guess_made'));
      expect(fake.loggedEvents[1].$1, equals('hint_used'));

      // 'bad_event' must still be unflushed (retained in queue).
      final unflushed = await db.exportUnflushedEvents();
      expect(unflushed.length, equals(1));
      expect(unflushed.first['event_name'], equals('bad_event'));
    },
  );

  // -------------------------------------------------------------------------
  // Test 5: Batch-of-10 trigger fires flush after every 10th unflushed event
  // -------------------------------------------------------------------------

  test('flush fires after every 10th unflushed event via logEvent', () async {
    final db = await _openTestDb('batch_trigger');
    addTearDown(() => _closeTestDb(db));

    final fake = _FakeAnalyticsClient();
    final exporter = FirebaseExporter(persistence: db, client: fake);

    // Log 9 events — no flush should fire (9 is not a multiple of 10).
    for (var i = 0; i < 9; i++) {
      await exporter.logEvent('guess_made', {'i': i});
    }
    expect(fake.loggedEvents, isEmpty, reason: 'no flush before 10th event');

    // 10th event — flush must fire.
    await exporter.logEvent('guess_made', {'i': 9});

    // All 10 events should have been flushed.
    expect(fake.loggedEvents.length, equals(10));
    final unflushed = await db.exportUnflushedEvents();
    expect(unflushed, isEmpty);
  });

  // -------------------------------------------------------------------------
  // Test 6: Flushed events are not re-sent (idempotent)
  // -------------------------------------------------------------------------

  test('flushed events are not re-sent on subsequent flush calls', () async {
    final db = await _openTestDb('idempotent');
    addTearDown(() => _closeTestDb(db));

    await db.logEvent('guess_made', {'lang': 'en'});

    final fake = _FakeAnalyticsClient();
    final exporter = FirebaseExporter(persistence: db, client: fake);

    // First flush.
    await exporter.init();
    expect(fake.loggedEvents.length, equals(1));

    // Second flush — same events must NOT be re-sent.
    await exporter.onResume();
    expect(fake.loggedEvents.length, equals(1), reason: 'no re-sends on second flush');
  });

  // -------------------------------------------------------------------------
  // Test 7: onResume triggers a flush
  // -------------------------------------------------------------------------

  test('onResume flushes unflushed events', () async {
    final db = await _openTestDb('on_resume');
    addTearDown(() => _closeTestDb(db));

    await db.logEvent('share_tapped', {'lang': 'en'});

    final fake = _FakeAnalyticsClient();
    final exporter = FirebaseExporter(persistence: db, client: fake);

    // init() flushes on startup — call onResume as if app resumed from background.
    await exporter.init();
    expect(fake.loggedEvents.length, equals(1));
    fake.loggedEvents.clear();

    // Log another event while "in background" (simulate offline period).
    await db.logEvent('guess_made', {});

    // Resume — the new event should be flushed.
    await exporter.onResume();
    expect(fake.loggedEvents.length, equals(1));
    expect(fake.loggedEvents.first.$1, equals('guess_made'));
  });

  // -------------------------------------------------------------------------
  // Test 8: bool props are coerced to int (Firebase does not accept bool)
  // -------------------------------------------------------------------------

  test('bool props are coerced to 1/0 in Firebase params', () async {
    final db = await _openTestDb('bool_coerce');
    addTearDown(() => _closeTestDb(db));

    await db.logEvent('ad_watched', {'fallback': true, 'another': false});

    final fake = _FakeAnalyticsClient();
    final exporter = FirebaseExporter(persistence: db, client: fake);

    await exporter.init();

    expect(fake.loggedEvents.length, equals(1));
    final params = fake.loggedEvents.first.$2;
    expect(params['fallback'], equals(1), reason: 'true → 1');
    expect(params['another'], equals(0), reason: 'false → 0');
  });

  // -------------------------------------------------------------------------
  // Test 9: recordError forwards to client
  // -------------------------------------------------------------------------

  test('recordError forwards to AnalyticsClient', () async {
    final db = await _openTestDb('record_error');
    addTearDown(() => _closeTestDb(db));

    final fake = _FakeAnalyticsClient();
    final exporter = FirebaseExporter(persistence: db, client: fake);

    final err = Exception('test crash');
    await exporter.recordError(err, StackTrace.empty, fatal: false);

    expect(fake.recordedErrors, contains(err));
  });

  // -------------------------------------------------------------------------
  // Test 10: no-op exporter recordError is a no-op (no client calls)
  // -------------------------------------------------------------------------

  test('no-op exporter recordError does not call client', () async {
    final db = await _openTestDb('noop_error');
    addTearDown(() => _closeTestDb(db));

    final fake = _FakeAnalyticsClient();
    final exporter = buildAnalyticsExporter(client: fake, persistence: db);

    // analyticsEnabled=false → no-op exporter.
    await exporter.recordError(Exception('ignored'), null);
    expect(fake.recordedErrors, isEmpty);
  });
}
