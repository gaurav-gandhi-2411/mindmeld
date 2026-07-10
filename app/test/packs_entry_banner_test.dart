/// Regression coverage for the pack-discoverability fix: packs must be
/// reachable directly from the primary daily play surface ([PuzzleScreen]),
/// not just from a card buried under the Practice tab — see
/// spec-warmer-rename.md workstream 3 ("couldn't find Bollywood" bug).
library;

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
import 'package:mindmeld/features/puzzle/puzzle_screen.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

/// [PayloadClient] that returns a pre-loaded [DailyPayload] without any I/O —
/// mirrors widget_test.dart's helper.
class _PreloadedClient extends PayloadClient {
  _PreloadedClient(this._preloaded);

  final DailyPayload _preloaded;

  @override
  Future<PayloadResult> fetch(String lang, String date) => Future.value(
        PayloadResult(payload: _preloaded, source: PayloadSource.bundledAsset),
      );

  @override
  Future<PayloadResult> fetchPack(String packId, int idx, String lang) =>
      Future.value(
        PayloadResult(payload: _preloaded, source: PayloadSource.bundledAsset),
      );
}

DailyPayload _loadPayload(String lang, String date) {
  final bytes = File('assets/payloads/$lang/$date.json.gz').readAsBytesSync();
  return PayloadCodec.decode(Uint8List.fromList(bytes));
}

void main() {
  late Directory tmpDir;

  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  setUp(() async {
    AppPersistence.resetForTest();
    tmpDir = await Directory.systemTemp.createTemp('mindmeld_packs_entry_');
    await AppPersistence.instance
        .init(dbPath: p.join(tmpDir.path, 'test.db'));
  });

  tearDown(() async {
    await AppPersistence.instance.close();
    AppPersistence.resetForTest();
    await tmpDir.delete(recursive: true);
  });

  Future<void> pumpPuzzle(
    WidgetTester tester, {
    bool isPractice = false,
    String? packId,
    int? packIdx,
    String? packTitle,
  }) async {
    final payload = _loadPayload('en', '2026-06-12');
    final client = _PreloadedClient(payload);

    await tester.pumpWidget(
      MaterialApp(
        home: PuzzleScreen(
          lang: 'en',
          date: '2026-06-12',
          onWin: () {},
          onLoss: () {},
          payloadClient: client,
          isPractice: isPractice,
          packId: packId,
          packIdx: packIdx,
          packTitle: packTitle,
        ),
      ),
    );
    await tester.runAsync(() async {
      await Future<void>.delayed(const Duration(milliseconds: 200));
    });
    await tester.pump();
  }

  testWidgets(
      'daily play surface shows the packs banner and it opens PackSelectorScreen',
      (tester) async {
    await pumpPuzzle(tester);

    expect(find.byType(PacksEntryBanner), findsOneWidget,
        reason: 'packs must be discoverable directly from the daily puzzle screen');

    await tester.tap(find.byType(PacksEntryBanner));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    expect(find.byType(PackSelectorScreen), findsOneWidget,
        reason: 'tapping the banner must navigate to the pack selector');
  });

  testWidgets('practice-mode puzzle does not show the packs banner',
      (tester) async {
    await pumpPuzzle(tester, isPractice: true);

    expect(find.byType(PacksEntryBanner), findsNothing,
        reason: 'the banner is the daily-surface entry point, not needed inside practice play');
  });

  testWidgets('pack-mode puzzle does not show the packs banner (no recursion)',
      (tester) async {
    await pumpPuzzle(tester, packId: 'bollywood', packIdx: 1, packTitle: 'Bollywood');

    expect(find.byType(PacksEntryBanner), findsNothing,
        reason: 'already inside pack play — must not link back into the pack selector');
  });
}
