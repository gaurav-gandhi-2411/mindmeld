/// Coverage for the launch-1 design-reviewer findings fixed in
/// puzzle_screen.dart:
///   - the guess [TextField] carries a persistent [InputDecoration.labelText]
///     (a [hintText] alone disappears once the user types, leaving no
///     accessible label for screen readers);
///   - a fresh puzzle (zero guesses, zero hints) shows an empty-state nudge
///     instead of blank space below the input row, and it disappears again
///     the moment the player makes a guess;
///   - a failed load shows a "Retry" button that re-invokes the same load
///     path rather than stranding the player with no way forward short of
///     restarting the app.
///
/// Reuses the `_FixedClient`/`_buildOceanPayload`/`_settle` scaffolding
/// pattern from daily_win_navigation_test.dart and widget_test.dart.
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
import 'package:mindmeld/features/puzzle/guess_tile.dart';
import 'package:mindmeld/features/puzzle/puzzle_screen.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

/// Builds a two-word payload where "ocean" is the rank-1 secret and "sea" is
/// rank 2 — a valid, non-winning guess that keeps the puzzle active. Adapted
/// from daily_win_navigation_test.dart's `_buildOceanPayload` (same
/// salt/hash pairing for "ocean", verified there and in
/// payload_codec_test.dart / pack_isolation_test.dart) with "sea" added to
/// the vocabulary so it resolves instead of hitting "Not in word list".
DailyPayload _buildOceanPayload() {
  const salt = '7ca5996a071e2723';
  final oceanHash = PayloadCodec.hashWord('ocean', salt);
  final seaHash = PayloadCodec.hashWord('sea', salt);
  const date = '2099-01-01';
  final json = '''{
    "v":3,"lang":"en","date":"$date",
    "model":"test","n":5000,"salt":"$salt",
    "words":{"$oceanHash":[1,65535],"$seaHash":[2,60000]},
    "hints":[[2,"sea"]],
    "s":"TbCpaqQ=",
    "maxGuesses":10
  }''';
  final bytes = Uint8List.fromList(GZipCodec().encode(utf8.encode(json)));
  return PayloadCodec.decode(bytes);
}

/// [PayloadClient] that serves a fixed payload with no network/asset I/O.
class _FixedClient extends PayloadClient {
  _FixedClient(this._payload);
  final DailyPayload _payload;

  @override
  Future<PayloadResult> fetch(String lang, String date) => Future.value(
        PayloadResult(payload: _payload, source: PayloadSource.bundledAsset),
      );
}

/// [PayloadClient] that serves [_payload] as the puzzle for [servedDate]
/// regardless of the requested date (models the B2 lookback result).
class _ServedDateClient extends PayloadClient {
  _ServedDateClient(this._payload, this.servedDate);
  final DailyPayload _payload;
  final String servedDate;

  @override
  Future<PayloadResult> fetch(String lang, String date) => Future.value(
        PayloadResult(
          payload: _payload,
          source: PayloadSource.network,
          servedDate: servedDate,
          requestedDate: date,
        ),
      );
}

/// [PayloadClient] whose [fetch] throws on its first call and succeeds with
/// [_payload] on every subsequent call — models a transient network failure
/// that a "Retry" tap resolves.
class _FailOnceThenSucceedClient extends PayloadClient {
  _FailOnceThenSucceedClient(this._payload);
  final DailyPayload _payload;
  int callCount = 0;

  @override
  Future<PayloadResult> fetch(String lang, String date) async {
    callCount++;
    if (callCount == 1) {
      throw Exception('simulated network failure');
    }
    return PayloadResult(payload: _payload, source: PayloadSource.bundledAsset);
  }
}

/// Pumps until the pending chain of real async work (sqflite I/O, the
/// payload fetch, the resulting setState calls) has drained. Mirrors the
/// `_settle` helper in daily_win_navigation_test.dart.
Future<void> _settle(WidgetTester tester) async {
  await tester.runAsync(() async {
    await Future<void>.delayed(const Duration(milliseconds: 200));
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
    tmpDir = await Directory.systemTemp.createTemp('mindmeld_puzzle_states_');
    final dbPath = p.join(tmpDir.path, 'test.db');
    await AppPersistence.instance.init(dbPath: dbPath);
  });

  tearDown(() async {
    await AppPersistence.instance.close();
    AppPersistence.resetForTest();
    await tmpDir.delete(recursive: true);
  });

  testWidgets('guess TextField carries a persistent labelText', (tester) async {
    final payload = _buildOceanPayload();

    await tester.pumpWidget(
      MaterialApp(
        home: PuzzleScreen(
          lang: 'en',
          date: '2099-01-01',
          onWin: () {},
          onLoss: () {},
          payloadClient: _FixedClient(payload),
        ),
      ),
    );
    await _settle(tester);

    final textField = tester.widget<TextField>(find.byType(TextField));
    expect(textField.decoration?.labelText, equals('Your guess'),
        reason: 'a hintText alone disappears once the user types — the field needs a '
            'persistent accessible labelText too');
  });

  testWidgets(
    'empty-state nudge shows on a fresh puzzle and disappears after one guess',
    (tester) async {
      final payload = _buildOceanPayload();

      await tester.pumpWidget(
        MaterialApp(
          home: PuzzleScreen(
            lang: 'en',
            date: '2099-01-01',
            onWin: () {},
            onLoss: () {},
            payloadClient: _FixedClient(payload),
          ),
        ),
      );
      await _settle(tester);

      expect(find.text('Make your first guess above'), findsOneWidget,
          reason: 'a totally fresh puzzle (no guesses, no hints) must not render blank '
              'space below the input row');
      expect(find.byType(GuessTile), findsNothing);

      // A non-winning guess ("sea" resolves to rank 2, not the rank-1 secret
      // "ocean") keeps the puzzle active while still exercising the
      // guesses.isNotEmpty transition.
      await tester.enterText(find.byType(TextField), 'sea');
      await tester.tap(find.text('Guess'));
      await _settle(tester);

      expect(find.text('Make your first guess above'), findsNothing,
          reason: 'the empty-state nudge must disappear once a guess has been made');
      expect(find.byType(GuessTile), findsOneWidget);
    },
  );

  testWidgets(
    'Retry button on a failed load re-invokes the load path and recovers',
    (tester) async {
      final payload = _buildOceanPayload();
      final client = _FailOnceThenSucceedClient(payload);

      await tester.pumpWidget(
        MaterialApp(
          home: PuzzleScreen(
            lang: 'en',
            date: '2099-01-01',
            onWin: () {},
            onLoss: () {},
            payloadClient: client,
          ),
        ),
      );
      await _settle(tester);

      expect(find.textContaining('Failed to load puzzle'), findsOneWidget,
          reason: 'sanity: the simulated first-fetch failure must surface the error state');
      final retryButton = find.widgetWithText(FilledButton, 'Retry');
      expect(retryButton, findsOneWidget,
          reason: 'the failed-load state must offer a way to retry short of restarting the app');

      await tester.tap(retryButton);
      await _settle(tester);

      expect(client.callCount, equals(2),
          reason: 'tapping Retry must re-invoke the same load path');
      expect(find.textContaining('Failed to load puzzle'), findsNothing);
      expect(find.text('Enter a word…'), findsOneWidget,
          reason: 'the second (successful) fetch must render the live puzzle board');
    },
  );

  testWidgets(
    'fallback-date puzzle shows a "Puzzle from <date>" label; same-day does not',
    (tester) async {
      final payload = _buildOceanPayload();

      Future<void> pumpWith(String servedDate) async {
        await tester.pumpWidget(
          MaterialApp(
            key: UniqueKey(),
            home: PuzzleScreen(
              lang: 'en',
              date: '2099-01-02',
              onWin: () {},
              onLoss: () {},
              payloadClient: _ServedDateClient(payload, servedDate),
            ),
          ),
        );
        await _settle(tester);
      }

      await pumpWith('2099-01-01');
      expect(find.byKey(const Key('fallback-puzzle-label')), findsOneWidget);
      expect(find.text('Puzzle from Jan 1'), findsOneWidget);

      await pumpWith('2099-01-02');
      expect(find.byKey(const Key('fallback-puzzle-label')), findsNothing);
      expect(find.textContaining('Puzzle from'), findsNothing);
    },
  );
}
