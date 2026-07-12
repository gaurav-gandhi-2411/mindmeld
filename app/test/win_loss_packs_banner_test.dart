/// Regression coverage for the "packs unreachable from the result screen"
/// bug: a player who opens the app after already winning/losing today's
/// daily lands directly on [WinScreen]/[LossScreen] (via main.dart's
/// `_WinShell`/`_LossShell`), which previously had no packs entry point at
/// all — packs were only reachable after an extra "Back" tap to reach the
/// finished puzzle board. Fix: both screens now show the same
/// [PacksEntryBanner] used on [PuzzleScreen], gated off in pack mode
/// (`packName != null`) to avoid recursion into the pack system from within
/// a pack puzzle's own result screen.
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
import 'package:mindmeld/features/packs/pack_selector_screen.dart';
import 'package:mindmeld/features/packs/packs_entry_banner.dart';
import 'package:mindmeld/features/win/win_screen.dart';
import 'package:mindmeld/main.dart';
import 'package:path/path.dart' as p;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

// ---------------------------------------------------------------------------
// Shared helpers — copied from daily_win_navigation_test.dart, which already
// exercises this exact _FixedClient/_buildOceanPayload/_settle/_appBarTitle
// combination for daily win/loss screen reachability.
// ---------------------------------------------------------------------------

/// Builds a minimal single-word payload where "ocean" is the rank-1 secret.
DailyPayload _buildOceanPayload() {
  const salt = '7ca5996a071e2723';
  final hash = PayloadCodec.hashWord('ocean', salt);
  const date = '2099-01-01';
  final json = '''{
    "v":3,"lang":"en","date":"$date",
    "model":"test","n":1,"salt":"$salt",
    "words":{"$hash":[1,65535]},
    "hints":[[2,"sea"]],
    "s":"TbCpaqQ=",
    "maxGuesses":10
  }''';
  final bytes = Uint8List.fromList(GZipCodec().encode(utf8.encode(json)));
  return PayloadCodec.decode(bytes);
}

/// [PayloadClient] that serves a fixed payload for both [fetch] (daily) and
/// [fetchPack] (themed packs, phase 6c) without any network/asset I/O.
class _FixedClient extends PayloadClient {
  _FixedClient(this._payload);
  final DailyPayload _payload;

  @override
  Future<PayloadResult> fetch(String lang, String date) => Future.value(
        PayloadResult(payload: _payload, source: PayloadSource.bundledAsset),
      );

  @override
  Future<PayloadResult> fetchPack(String packId, int idx, String lang) =>
      Future.value(
        PayloadResult(payload: _payload, source: PayloadSource.bundledAsset),
      );
}

/// Pumps until the pending chain of real async work (sqflite I/O, the
/// payload fetch, the resulting setState calls) has drained.
Future<void> _settle(WidgetTester tester) async {
  await tester.runAsync(() async {
    await Future<void>.delayed(const Duration(milliseconds: 200));
  });
  await tester.pump();
}

/// Finds [text] rendered specifically inside an [AppBar].
Finder _appBarTitle(String text) =>
    find.descendant(of: find.byType(AppBar), matching: find.text(text));

void main() {
  late Directory tmpDir;
  late String dbPath;

  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    AppPersistence.resetForTest();
    tmpDir = await Directory.systemTemp.createTemp('mindmeld_win_loss_packs_');
    dbPath = p.join(tmpDir.path, 'test.db');
    await AppPersistence.instance.init(dbPath: dbPath);
  });

  tearDown(() async {
    await AppPersistence.instance.close();
    AppPersistence.resetForTest();
    await tmpDir.delete(recursive: true);
  });

  testWidgets(
    'daily win screen shows the packs banner and tapping it opens PackSelectorScreen',
    (tester) async {
      const date = '2099-01-01';
      final payload = _buildOceanPayload();
      final wonState = DayState(
        date: date,
        lang: 'en',
        guesses: [
          Guess(word: 'ocean', rank: 1, similarity: 1.0, band: TemperatureBand.win),
        ],
        hintsUsed: 0,
        won: true,
        gaveUp: false,
      );
      await tester.runAsync(() => AppPersistence.instance.saveDayState(wonState));

      await tester.pumpWidget(WarmerApp(
        overrides: AppOverrides(
          fixedDate: date,
          lang: 'en',
          dbPath: dbPath,
          skipOnboarding: true,
          payloadClient: _FixedClient(payload),
        ),
      ));
      await _settle(tester);
      await _settle(tester);

      expect(_appBarTitle('You got it!'), findsOneWidget,
          reason: 'sanity: must land directly on the win screen');
      expect(find.byType(PacksEntryBanner), findsOneWidget,
          reason: 'packs must be discoverable directly from the win screen, '
              'without an extra Back tap');

      await tester.tap(find.byType(PacksEntryBanner));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));

      expect(find.byType(PackSelectorScreen), findsOneWidget,
          reason: 'tapping the banner must navigate to the pack selector');
    },
  );

  testWidgets(
    'daily loss screen shows the packs banner',
    (tester) async {
      const date = '2099-01-01';
      final payload = _buildOceanPayload();
      final lostState = DayState(
        date: date,
        lang: 'en',
        guesses: [],
        hintsUsed: 0,
        won: false,
        gaveUp: true,
      );
      await tester.runAsync(() => AppPersistence.instance.saveDayState(lostState));

      await tester.pumpWidget(WarmerApp(
        overrides: AppOverrides(
          fixedDate: date,
          lang: 'en',
          dbPath: dbPath,
          skipOnboarding: true,
          payloadClient: _FixedClient(payload),
        ),
      ));
      await _settle(tester);
      await _settle(tester);

      expect(_appBarTitle('Better luck next time 🌙'), findsOneWidget,
          reason: 'sanity: must land directly on the loss screen');
      expect(find.byType(PacksEntryBanner), findsOneWidget,
          reason: 'packs must be discoverable directly from the loss screen, '
              'without an extra Back tap');
    },
  );

  testWidgets(
    'pack-mode win screen (packName non-null) does not show the packs banner',
    (tester) async {
      await tester.pumpWidget(MaterialApp(
        home: WinScreen(
          secret: 'ocean',
          guesses: [
            Guess(word: 'ocean', rank: 1, similarity: 1.0, band: TemperatureBand.win),
          ],
          lang: 'en',
          date: 'bollywood-001',
          onPlayAgain: () {},
          packName: 'Bollywood',
          packPuzzleNumber: 1,
        ),
      ));
      await tester.pump();

      expect(find.byType(PacksEntryBanner), findsNothing,
          reason: 'a pack-mode result screen must not link back into the pack '
              'system — that would be recursion into its own destination');
    },
  );
}
