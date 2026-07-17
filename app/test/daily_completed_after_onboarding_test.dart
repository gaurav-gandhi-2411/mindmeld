/// Tests the `daily_completed_after_onboarding` funnel-closing event
/// (first-session-hook wave): puzzle_screen.dart's `_logPuzzleCompleted`
/// fires it exactly when a player who graduated from onboarding via a WIN
/// THAT SAME DAY (tracked via the `onboarding_graduated_date` pref) then
/// completes today's real daily — and clears the pref afterward so it can
/// never double-fire.
///
/// Reuses the payload-builder/pump-helper conventions from
/// puzzle_completed_analytics_test.dart.
library;

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/analytics/firebase_exporter.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/payload_client.dart';
import 'package:mindmeld/core/payload_codec.dart';
import 'package:mindmeld/core/persistence.dart';
import 'package:mindmeld/features/onboarding/first_run.dart';
import 'package:mindmeld/features/puzzle/puzzle_screen.dart';
import 'package:mindmeld/stubs/analytics_stub.dart';
import 'package:path/path.dart' as p;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

const String _kDate = '2099-03-01';

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

/// Builds a gzip-compressed daily payload with a winning word ("ocean",
/// rank 1) and a losing word ("wrongword", rank 500) — reused verbatim from
/// puzzle_completed_analytics_test.dart's `_buildPayloadBytes`.
Uint8List _buildPayloadBytes({required int maxGuesses}) {
  const salt = '7ca5996a071e2723';
  const secretS = 'TbCpaqQ=';
  final oceanHash = PayloadCodec.hashWord('ocean', salt);
  final wrongHash = PayloadCodec.hashWord('wrongword', salt);

  final json = jsonEncode({
    'v': 3,
    'lang': 'en',
    'date': _kDate,
    'model': 'test',
    'n': 10000,
    'salt': salt,
    'words': {
      oceanHash: [1, 65535],
      wrongHash: [500, 30000],
    },
    'hints': const <List<dynamic>>[],
    's': secretS,
    'maxGuesses': maxGuesses,
  });

  return Uint8List.fromList(GZipCodec().encode(utf8.encode(json)));
}

class _PreloadedClient extends PayloadClient {
  _PreloadedClient(this._payload);
  final DailyPayload _payload;

  @override
  Future<PayloadResult> fetch(String lang, String date) => Future.value(
        PayloadResult(payload: _payload, source: PayloadSource.bundledAsset),
      );
}

Future<void> _pumpPuzzleScreen(
  WidgetTester tester, {
  required DailyPayload payload,
  required AnalyticsExporter exporter,
}) async {
  await tester.pumpWidget(
    MaterialApp(
      home: PuzzleScreen(
        lang: 'en',
        date: _kDate,
        onWin: () {},
        onLoss: () {},
        payloadClient: _PreloadedClient(payload),
        exporter: exporter,
      ),
    ),
  );
  await tester.runAsync(() async {
    await Future<void>.delayed(const Duration(milliseconds: 300));
  });
  await tester.pump();
}

Future<void> _drainRealAndFakeAsync(WidgetTester tester,
    {int rounds = 6, int roundMs = 150}) async {
  for (var i = 0; i < rounds; i++) {
    await tester.runAsync(() async {
      await Future<void>.delayed(Duration(milliseconds: roundMs));
    });
    await tester.pump(Duration(milliseconds: roundMs));
  }
}

Future<void> _submitGuessAndAwaitOutcome(WidgetTester tester, String word) async {
  await tester.enterText(find.byType(TextField), word);
  await tester.tap(find.text('Guess'));
  await tester.pump();
  await _drainRealAndFakeAsync(tester);
}

void main() {
  late Directory tmpDir;

  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    AppPersistence.resetForTest();
    tmpDir = await Directory.systemTemp.createTemp('mindmeld_daily_after_onboarding_');
    await AppPersistence.instance.init(dbPath: p.join(tmpDir.path, 'test.db'));
  });

  tearDown(() async {
    await AppPersistence.instance.close();
    AppPersistence.resetForTest();
    await tmpDir.delete(recursive: true);
  });

  testWidgets(
    'graduated_date == today: winning the daily fires daily_completed_after_onboarding '
    'with outcome=win, then clears the pref',
    (tester) async {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(kOnboardingGraduatedDateKey, _kDate);

      final payload = PayloadCodec.decode(_buildPayloadBytes(maxGuesses: 10));
      final exporter = _FakeExporter();

      await _pumpPuzzleScreen(tester, payload: payload, exporter: exporter);
      await _submitGuessAndAwaitOutcome(tester, 'ocean');

      expect(
        exporter.events.any((e) =>
            e.$1 == AnalyticsEvent.dailyCompletedAfterOnboarding &&
            e.$2?['outcome'] == 'win'),
        isTrue,
        reason: 'a daily win on the graduated date must close the funnel with '
            'daily_completed_after_onboarding',
      );

      expect(prefs.getString(kOnboardingGraduatedDateKey), isNull,
          reason: 'the pref must be cleared after firing so it never double-fires');
    },
  );

  testWidgets(
    'graduated_date != today: winning the daily does NOT fire daily_completed_after_onboarding',
    (tester) async {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(kOnboardingGraduatedDateKey, '2099-01-01'); // different date

      final payload = PayloadCodec.decode(_buildPayloadBytes(maxGuesses: 10));
      final exporter = _FakeExporter();

      await _pumpPuzzleScreen(tester, payload: payload, exporter: exporter);
      await _submitGuessAndAwaitOutcome(tester, 'ocean');

      expect(exporter.has(AnalyticsEvent.dailyCompletedAfterOnboarding), isFalse,
          reason: 'a stale/unrelated graduated_date must never trigger the funnel event');
    },
  );

  testWidgets(
    'no graduated_date pref set: winning the daily does NOT fire daily_completed_after_onboarding '
    '(the common case — most players never went through onboarding on a given day)',
    (tester) async {
      final payload = PayloadCodec.decode(_buildPayloadBytes(maxGuesses: 10));
      final exporter = _FakeExporter();

      await _pumpPuzzleScreen(tester, payload: payload, exporter: exporter);
      await _submitGuessAndAwaitOutcome(tester, 'ocean');

      expect(exporter.has(AnalyticsEvent.dailyCompletedAfterOnboarding), isFalse);
      // Sanity: the underlying puzzle_completed event still fires as normal.
      expect(exporter.has(AnalyticsEvent.puzzleCompleted), isTrue);
    },
  );

  testWidgets(
    'graduated_date == today: a loss on the daily also fires '
    'daily_completed_after_onboarding with outcome=loss_budget',
    (tester) async {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(kOnboardingGraduatedDateKey, _kDate);

      final payload = PayloadCodec.decode(_buildPayloadBytes(maxGuesses: 1));
      final exporter = _FakeExporter();

      await _pumpPuzzleScreen(tester, payload: payload, exporter: exporter);
      await _submitGuessAndAwaitOutcome(tester, 'wrongword');

      expect(
        exporter.events.any((e) =>
            e.$1 == AnalyticsEvent.dailyCompletedAfterOnboarding &&
            e.$2?['outcome'] == 'loss_budget'),
        isTrue,
      );
    },
  );
}
