/// WarmerApp-level boot-routing tests for the first-run gate
/// (first-session-hook wave): an existing user (legacy `onboarding_done`
/// pref) boots straight to the daily, and an interrupted onboarding
/// (`onboarding_puzzle_state == started`) resumes without re-firing
/// `onboarding_started`. Complements first_run_test.dart's pure-logic unit
/// tests and flow_hardening_test.dart's S1 (genuinely-new-player) case.
library;

import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/analytics/firebase_exporter.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/payload_client.dart';
import 'package:mindmeld/core/payload_codec.dart';
import 'package:mindmeld/core/persistence.dart';
import 'package:mindmeld/features/onboarding/first_run.dart';
import 'package:mindmeld/main.dart';
import 'package:mindmeld/stubs/analytics_stub.dart';
import 'package:path/path.dart' as p;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

class _FakeExporter implements AnalyticsExporter {
  final List<(String, Map<String, dynamic>?)> events = [];

  @override
  Future<void> logEvent(String name, [Map<String, dynamic>? props]) async {
    events.add((name, props));
  }

  @override
  Future<void> recordError(Object error, StackTrace? stack, {bool fatal = false}) async {}

  @override
  Future<void> init() async {}

  @override
  Future<void> onResume() async {}

  bool has(String name) => events.any((e) => e.$1 == name);
}

/// [PayloadClient] serving a fixed real daily/onboarding payload with no I/O.
class _FixedClient extends PayloadClient {
  _FixedClient(this._daily, this._onboarding);
  final DailyPayload _daily;
  final DailyPayload _onboarding;

  @override
  Future<PayloadResult> fetch(String lang, String date) => Future.value(
        PayloadResult(payload: _daily, source: PayloadSource.bundledAsset),
      );

  @override
  Future<PayloadResult> fetchOnboarding(String lang) => Future.value(
        PayloadResult(payload: _onboarding, source: PayloadSource.bundledAsset),
      );
}

DailyPayload _loadDailyPayload() {
  final bytes = File('assets/payloads/en/2026-06-12.json.gz').readAsBytesSync();
  return PayloadCodec.decode(Uint8List.fromList(bytes));
}

void main() {
  late Directory tmpDir;
  late String dbPath;
  late DailyPayload dailyPayload;

  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
    dailyPayload = _loadDailyPayload();
  });

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    AppPersistence.resetForTest();
    tmpDir = await Directory.systemTemp.createTemp('mindmeld_onboarding_boot_');
    dbPath = p.join(tmpDir.path, 'test.db');
    await AppPersistence.instance.init(dbPath: dbPath);
  });

  tearDown(() async {
    await AppPersistence.instance.close();
    AppPersistence.resetForTest();
    await tmpDir.delete(recursive: true);
  });

  testWidgets(
    'existing user (legacy onboarding_done=true) boots straight to the daily — '
    'never shown the onboarding puzzle',
    (tester) async {
      SharedPreferences.setMockInitialValues({kLegacyOnboardingDonePref: true});
      final exporter = _FakeExporter();

      await tester.pumpWidget(WarmerApp(
        overrides: AppOverrides(
          fixedDate: '2026-06-12',
          lang: 'en',
          dbPath: dbPath,
          payloadClient: _FixedClient(dailyPayload, dailyPayload),
        ),
        exporter: exporter,
      ));
      await tester.pump();
      await tester.runAsync(() async {
        await Future<void>.delayed(const Duration(milliseconds: 300));
      });
      await tester.pump();
      await tester.runAsync(() async {
        await Future<void>.delayed(const Duration(milliseconds: 300));
      });
      await tester.pump();

      expect(find.text('Learn to play'), findsNothing,
          reason: 'an existing user must never see the onboarding puzzle');
      expect(find.text('Enter a word…'), findsOneWidget,
          reason: 'an existing user must land directly on the live daily board');
      expect(exporter.has(AnalyticsEvent.onboardingStarted), isFalse);

      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString(kOnboardingStateKey), equals('done'),
          reason: 'the legacy grandfather check must persist done going forward');
    },
  );

  testWidgets(
    'interrupted onboarding (state == started) resumes the onboarding puzzle '
    'without re-firing onboarding_started',
    (tester) async {
      SharedPreferences.setMockInitialValues({kOnboardingStateKey: 'started'});
      final exporter = _FakeExporter();

      await tester.pumpWidget(WarmerApp(
        overrides: AppOverrides(
          fixedDate: '2026-06-12',
          lang: 'en',
          dbPath: dbPath,
          payloadClient: _FixedClient(dailyPayload, dailyPayload),
        ),
        exporter: exporter,
      ));
      await tester.pump();
      await tester.runAsync(() async {
        await Future<void>.delayed(const Duration(milliseconds: 300));
      });
      await tester.pump();
      await tester.runAsync(() async {
        await Future<void>.delayed(const Duration(milliseconds: 300));
      });
      await tester.pump();

      expect(find.text('Learn to play'), findsOneWidget,
          reason: 'an interrupted onboarding must resume, never strand the player');
      expect(exporter.has(AnalyticsEvent.onboardingStarted), isFalse,
          reason: 'onboarding_started must fire exactly once, not on every resume');

      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString(kOnboardingStateKey), equals('started'),
          reason: 'resuming must not mutate the stored state to done prematurely');
    },
  );
}
