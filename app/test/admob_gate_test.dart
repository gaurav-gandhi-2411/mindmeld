/// Unit tests for [AdMobRewardedGate] with injected [AdLoader].
///
/// These tests run as pure host (dart vm) tests — no Flutter platform channel,
/// no google_mobile_ads native code.  The production SDK is kept behind the
/// [AdLoader] injection point so tests can exercise both paths without any
/// real ad infrastructure.
///
///   Test 1 — loader throws → gate falls back to stub → resolves granted=true,
///             fallback=true; analytics ring buffer contains an ad_watched event
///             with fallback=true.
///
///   Test 2 — loader returns [FakeLoadedAd(rewarded: true)] → gate resolves
///             granted=true, fallback=false; analytics contains ad_watched
///             with fallback=false.
///
/// Both tests use `testWidgets` because [AdMobRewardedGate.requestHint]
/// requires a [BuildContext]. A minimal [MaterialApp] is pumped to supply the
/// context. The fallback stub is given [simulatedDelay: Duration(seconds: 1)]
/// so the widget pump can advance past it cleanly.
library;

import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/ads/rewarded_ad_service.dart';
import 'package:mindmeld/core/persistence.dart';
import 'package:mindmeld/stubs/analytics_stub.dart';
import 'package:mindmeld/stubs/rewarded_ad_stub.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

late Directory _tmpDir;

// Short delay for the fallback stub so fake-async pump can advance past it.
const _kStubDelay = Duration(seconds: 1);

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  setUp(() async {
    AppPersistence.resetForTest();
    _tmpDir = await Directory.systemTemp.createTemp('mindmeld_gate_');
    await AppPersistence.instance.init(
      dbPath: p.join(_tmpDir.path, 'gate_test.db'),
    );
  });

  tearDown(() async {
    await AppPersistence.instance.close();
    AppPersistence.resetForTest();
    await _tmpDir.delete(recursive: true);
  });

  // -------------------------------------------------------------------------
  // Test 1: loader throws → fallback path
  // -------------------------------------------------------------------------

  testWidgets(
    'AdMobRewardedGate: loader throws → falls back to stub, '
    'resolves granted=true fallback=true, logs ad_watched with fallback=true',
    (tester) async {
      // Inject a loader that always throws (simulates "no fill" / timeout).
      final gate = AdMobRewardedGate(
        adLoader: (_) async => throw Exception('no fill'),
        fallbackStub: const RewardedAdStub(simulatedDelay: _kStubDelay),
      );

      // Pump a minimal app to obtain a BuildContext.
      late BuildContext capturedCtx;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Builder(builder: (ctx) {
              capturedCtx = ctx;
              return const SizedBox.shrink();
            }),
          ),
        ),
      );
      await tester.pump();

      // Start the hint request — loader throws immediately, so fallback stub
      // is invoked synchronously before the first await.
      final future = gate.requestHint(capturedCtx);

      // One pump: showDialog() inside RewardedAdStub._showSimulated fires.
      await tester.pump();

      // Advance past the stub delay.
      await tester.pump(const Duration(seconds: 4));

      // Allow DB writes (analytics logEvent) to complete on OS threads.
      late HintGateResult result;
      await tester.runAsync(() async {
        result = await future;
        await Future<void>.delayed(const Duration(milliseconds: 200));
      });
      await tester.pump();

      // Gate must report: hint granted, came from fallback.
      expect(result.granted, isTrue);
      expect(result.fallback, isTrue);

      // Analytics ring buffer must contain an ad_watched event with fallback=true.
      final events = await tester.runAsync(() async {
        return AppPersistence.instance.exportAnalyticsBuffer();
      }) ?? [];

      final adWatchedEvents = events
          .where((e) => e['event_name'] == AnalyticsEvent.adWatched)
          .toList();

      expect(adWatchedEvents, isNotEmpty,
          reason: 'ad_watched must be logged after fallback gate pass');

      final props = jsonDecode(
        adWatchedEvents.first['props_json'] as String,
      ) as Map<String, dynamic>;
      expect(props['fallback'], isTrue,
          reason: 'fallback=true expected when loader throws');
    },
  );

  // -------------------------------------------------------------------------
  // Test 2: loader returns rewarding ad → happy path
  // -------------------------------------------------------------------------

  testWidgets(
    'AdMobRewardedGate: fake ad rewards immediately → '
    'granted=true fallback=false, logs ad_watched with fallback=false',
    (tester) async {
      // Inject a loader that returns a FakeLoadedAd that immediately rewards.
      final gate = AdMobRewardedGate(
        adLoader: (_) async => const FakeLoadedAd(rewarded: true),
      );

      // Pump a minimal app to obtain a BuildContext.
      late BuildContext capturedCtx;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Builder(builder: (ctx) {
              capturedCtx = ctx;
              return const SizedBox.shrink();
            }),
          ),
        ),
      );
      await tester.pump();

      // No dialog is shown for a successful real ad — just await the result.
      late HintGateResult result;
      await tester.runAsync(() async {
        result = await gate.requestHint(capturedCtx);
        await Future<void>.delayed(const Duration(milliseconds: 200));
      });
      await tester.pump();

      // Gate must report: hint granted, NOT from fallback.
      expect(result.granted, isTrue);
      expect(result.fallback, isFalse);

      // Analytics ring buffer must contain an ad_watched event with fallback=false.
      final events = await tester.runAsync(() async {
        return AppPersistence.instance.exportAnalyticsBuffer();
      }) ?? [];

      final adWatchedEvents = events
          .where((e) => e['event_name'] == AnalyticsEvent.adWatched)
          .toList();

      expect(adWatchedEvents, isNotEmpty,
          reason: 'ad_watched must be logged after successful gate pass');

      final props = jsonDecode(
        adWatchedEvents.first['props_json'] as String,
      ) as Map<String, dynamic>;
      expect(props['fallback'], isFalse,
          reason: 'fallback=false expected when ad loads and rewards');
    },
  );

  // -------------------------------------------------------------------------
  // Factory smoke: adsEnabled=false → stub gate
  // -------------------------------------------------------------------------

  test('buildHintGate with adsEnabled=false returns a non-AdMob gate', () {
    // AppConfig.adsEnabled is false in test builds (no dart-define).
    // buildHintGate must return _StubGate (not AdMobRewardedGate).
    final gate = buildHintGate();
    expect(gate, isNot(isA<AdMobRewardedGate>()));
  });
}
