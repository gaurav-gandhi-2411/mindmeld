/// CRITICAL INVARIANT test (phase 6c): playing a themed-pack puzzle must
/// NEVER write to day_state or stats — the daily streak is provably
/// unaffected by pack play. Then, as a control, winning a DAILY puzzle in the
/// same session must increment the streak normally.
library;

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/payload_client.dart';
import 'package:mindmeld/core/payload_codec.dart';
import 'package:mindmeld/core/persistence.dart';
import 'package:mindmeld/features/puzzle/puzzle_screen.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

/// [PayloadClient] that serves a fixed pack payload for [fetchPack] without
/// any I/O — mirrors _PreloadedClient in widget_test.dart.
class _PackPreloadedClient extends PayloadClient {
  _PackPreloadedClient(this._payload);
  final DailyPayload _payload;

  @override
  Future<PayloadResult> fetchPack(String packId, int idx, String lang) =>
      Future.value(
        PayloadResult(payload: _payload, source: PayloadSource.bundledAsset),
      );
}

/// [PayloadClient] that serves a fixed daily payload for [fetch].
class _DailyPreloadedClient extends PayloadClient {
  _DailyPreloadedClient(this._payload);
  final DailyPayload _payload;

  @override
  Future<PayloadResult> fetch(String lang, String date) => Future.value(
        PayloadResult(payload: _payload, source: PayloadSource.bundledAsset),
      );
}

/// Builds a minimal single-word payload where "ocean" is the rank-1 secret —
/// reuses the exact salt/secret pairing from payload_codec_test.dart's
/// synthetic payload (already verified to decode to "ocean").
DailyPayload _buildOceanPayload({String? pack, int? idx}) {
  const salt = '7ca5996a071e2723';
  final hash = PayloadCodec.hashWord('ocean', salt);
  final packFields =
      pack != null ? '"pack":"$pack","idx":$idx,' : '';
  final date = pack != null ? '$pack-${idx.toString().padLeft(3, '0')}' : '2099-01-01';
  final json = '''{
    "v":3,"lang":"en","date":"$date",
    "model":"test","n":1,"salt":"$salt",
    "words":{"$hash":[1,65535]},
    "hints":[[2,"sea"]],
    "s":"TbCpaqQ=",
    $packFields
    "maxGuesses":10
  }''';
  final bytes = Uint8List.fromList(GZipCodec().encode(utf8.encode(json)));
  return PayloadCodec.decode(bytes);
}

/// Pumps until PuzzleScreen's async _load() and the guess-submit persistence
/// writes complete (mirrors flow_hardening_test.dart's _pumpUntilLoaded).
Future<void> _settle(WidgetTester tester) async {
  await tester.runAsync(() async {
    await Future<void>.delayed(const Duration(milliseconds: 300));
  });
  await tester.pump();
}

/// Taps "Guess" and drives the win flow to completion.
///
/// The winning path does real sqflite I/O (saveState/recordWin/analytics)
/// BEFORE scheduling the 600ms win-flash delay, so a single pump(duration)
/// isn't enough: the fake-timer isn't even created until the real I/O drains.
/// This interleaves runAsync (drain real I/O) with pump(duration) (fire the
/// resulting fake timer) so no timer is left pending when the test ends.
Future<void> _tapGuessAndAwaitWin(WidgetTester tester) async {
  await tester.tap(find.text('Guess'));
  await tester.pump();
  await tester.runAsync(() async {
    await Future<void>.delayed(const Duration(milliseconds: 300));
  });
  await tester.pump(const Duration(milliseconds: 700)); // fires the win-flash timer
  await tester.runAsync(() async {
    await Future<void>.delayed(const Duration(milliseconds: 300));
  });
  await tester.pump();
}

void main() {
  late Directory tmpDir;

  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  setUp(() async {
    AppPersistence.resetForTest();
    tmpDir = await Directory.systemTemp.createTemp('mindmeld_pack_isolation_');
    await AppPersistence.instance.init(dbPath: p.join(tmpDir.path, 'test.db'));
  });

  tearDown(() async {
    await AppPersistence.instance.close();
    AppPersistence.resetForTest();
    await tmpDir.delete(recursive: true);
  });

  testWidgets(
    'winning a pack puzzle never touches day_state/stats; a daily win afterwards '
    'still increments the streak normally',
    (tester) async {
      // ---------------------------------------------------------------------
      // Part 1: play a pack puzzle to a win.
      // ---------------------------------------------------------------------
      final packPayload = _buildOceanPayload(pack: 'bollywood', idx: 1);
      final packClient = _PackPreloadedClient(packPayload);

      await tester.pumpWidget(
        MaterialApp(
          home: PuzzleScreen(
            key: const ValueKey('pack-screen'),
            lang: 'en',
            date: 'bollywood-001',
            packId: 'bollywood',
            packIdx: 1,
            packTitle: 'Bollywood',
            payloadClient: packClient,
            onWin: () {},
            onLoss: () {},
          ),
        ),
      );
      await _settle(tester);

      await tester.enterText(find.byType(TextField), 'ocean');
      await _tapGuessAndAwaitWin(tester);

      // Pack progress WAS recorded...
      final packState = await tester.runAsync(
        () => AppPersistence.instance.loadPackState('bollywood', 1, 'en'),
      );
      expect(packState, isNotNull, reason: 'pack win must be persisted');
      expect(packState!.won, isTrue);

      // ...but day_state and stats were NOT touched by the pack win.
      final dayStateAfterPack = await tester.runAsync(
        () => AppPersistence.instance.loadDayState('bollywood-001', 'en'),
      );
      expect(dayStateAfterPack, isNull,
          reason: 'pack play must never write to day_state');

      final statsAfterPack = await tester.runAsync(
        () => AppPersistence.instance.loadStats('en'),
      );
      expect(statsAfterPack, isNotNull);
      expect(statsAfterPack!.played, equals(0),
          reason: 'pack win must never increment daily played count');
      expect(statsAfterPack.wins, equals(0),
          reason: 'pack win must never increment daily wins count');
      expect(statsAfterPack.currentStreak, equals(0),
          reason: 'pack win must never affect the daily streak');

      // ---------------------------------------------------------------------
      // Part 2 (control): a DAILY win in the same session increments the
      // streak normally — proves the isolation is specific to pack mode, not
      // a general persistence failure.
      // ---------------------------------------------------------------------
      final dailyPayload = _buildOceanPayload();
      final dailyClient = _DailyPreloadedClient(dailyPayload);

      await tester.pumpWidget(
        MaterialApp(
          home: PuzzleScreen(
            key: const ValueKey('daily-screen'),
            lang: 'en',
            date: '2099-01-01',
            payloadClient: dailyClient,
            onWin: () {},
            onLoss: () {},
          ),
        ),
      );
      await _settle(tester);

      await tester.enterText(find.byType(TextField), 'ocean');
      await _tapGuessAndAwaitWin(tester);

      final dayStateAfterDaily = await tester.runAsync(
        () => AppPersistence.instance.loadDayState('2099-01-01', 'en'),
      );
      expect(dayStateAfterDaily, isNotNull);
      expect(dayStateAfterDaily!.won, isTrue);

      final statsAfterDaily = await tester.runAsync(
        () => AppPersistence.instance.loadStats('en'),
      );
      expect(statsAfterDaily, isNotNull);
      expect(statsAfterDaily!.played, equals(1),
          reason: 'daily win must increment played count');
      expect(statsAfterDaily.wins, equals(1),
          reason: 'daily win must increment wins count');
      expect(statsAfterDaily.currentStreak, equals(1),
          reason: 'daily win must start/increment the streak');
    },
  );
}
