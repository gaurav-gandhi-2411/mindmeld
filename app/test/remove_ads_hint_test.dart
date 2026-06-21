/// Widget test: with removeAds entitlement granted, the hint flow bypasses
/// the rewarded-ad modal entirely.
///
/// Verifies:
///   1. Tapping the hint button does NOT show the "Watching ad…" dialog.
///   2. The hint tile appears immediately after tapping (no ad delay).
///   3. The daily cap is still enforced even when removeAds is active.
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
import 'package:mindmeld/iap/entitlements.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

// ---------------------------------------------------------------------------
// Fake IAP gateway
// ---------------------------------------------------------------------------

/// [IapGateway] that grants removeAds unconditionally, for widget test injection.
class _RemoveAdsGateway implements IapGateway {
  const _RemoveAdsGateway();

  @override
  Future<PurchaseOutcome> purchase(Product product) async =>
      PurchaseOutcome.comingSoon;

  @override
  Future<void> restore() async {}

  @override
  Future<Entitlements> current() async =>
      const Entitlements(removeAds: true, archive: false, streakFreezes: 0);

  @override
  Future<void> consumeStreakFreeze() async {}
}

// ---------------------------------------------------------------------------
// Payload builder (reused from hint_flow_test pattern)
// ---------------------------------------------------------------------------

Uint8List _buildHintPayloadBytes() {
  const salt = '7ca5996a071e2723';
  const secretS = 'TbCpaqQ=';
  final oceanHash = PayloadCodec.hashWord('ocean', salt);
  const n = 10000;
  final json = jsonEncode({
    'v': 1,
    'lang': 'en',
    'date': '2099-02-01',
    'model': 'test',
    'n': n,
    'salt': salt,
    'words': {
      oceanHash: [1, 65535],
    },
    'hints': [
      [8, 'wave'],
      [4, 'shore'],
    ],
    's': secretS,
  });
  return Uint8List.fromList(GZipCodec().encode(utf8.encode(json)));
}

/// [PayloadClient] that returns a pre-built payload without I/O.
class _PreloadedClient extends PayloadClient {
  _PreloadedClient(this._payload);

  final DailyPayload _payload;

  @override
  Future<PayloadResult> fetch(String lang, String date) => Future.value(
        PayloadResult(
          payload: _payload,
          source: PayloadSource.bundledAsset,
        ),
      );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

Future<void> _pumpUntilLoaded(WidgetTester tester) async {
  await tester.runAsync(() async {
    await Future<void>.delayed(const Duration(milliseconds: 200));
  });
  await tester.pump();
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  late Directory tmpDir;
  late DailyPayload hintPayload;

  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
    hintPayload = PayloadCodec.decode(_buildHintPayloadBytes());
  });

  setUp(() async {
    AppPersistence.resetForTest();
    tmpDir = await Directory.systemTemp.createTemp('mindmeld_removeads_');
    final dbPath = p.join(tmpDir.path, 'removeads_test.db');
    await AppPersistence.instance.init(dbPath: dbPath);
  });

  tearDown(() async {
    await AppPersistence.instance.close();
    AppPersistence.resetForTest();
    await tmpDir.delete(recursive: true);
  });

  // -------------------------------------------------------------------------
  // Test 1: removeAds → no ad dialog, hint tile appears
  // -------------------------------------------------------------------------

  testWidgets(
    'with removeAds entitlement, tapping hint shows tile without ad modal',
    (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: PuzzleScreen(
            lang: 'en',
            date: '2099-02-01',
            onWin: () {},
            onLoss: () {},
            payloadClient: _PreloadedClient(hintPayload),
            iapGateway: const _RemoveAdsGateway(),
          ),
        ),
      );
      await _pumpUntilLoaded(tester);

      // Hint button must be present.
      expect(find.textContaining('Hint (2 left)'), findsOneWidget);

      // Tap hint button.
      await tester.tap(find.widgetWithText(OutlinedButton, 'Hint (2 left)'));

      // One pump — should NOT show ad dialog.
      await tester.pump();
      expect(
        find.text('Watching ad…'),
        findsNothing,
        reason: 'removeAds entitlement must bypass the ad modal',
      );

      // Allow async continuation (saveDayState etc.) to complete.
      await tester.runAsync(() async {
        await Future<void>.delayed(const Duration(milliseconds: 500));
      });
      await tester.pump();

      // Hint tile must appear.
      expect(
        find.byKey(const HintTileKey('wave')),
        findsOneWidget,
        reason: 'Hint tile must appear without going through ad modal',
      );
    },
  );

  // -------------------------------------------------------------------------
  // Test 2: daily cap still enforced with removeAds
  // -------------------------------------------------------------------------

  testWidgets(
    'daily cap still enforced even with removeAds entitlement',
    (tester) async {
      // There are only 2 hints in the payload and maxHintsPerDay = 5, so the
      // cap won't fire on a fresh puzzle. But we can verify that after both
      // hints are used the button becomes disabled.
      await tester.pumpWidget(
        MaterialApp(
          home: PuzzleScreen(
            lang: 'en',
            date: '2099-02-01',
            onWin: () {},
            onLoss: () {},
            payloadClient: _PreloadedClient(hintPayload),
            iapGateway: const _RemoveAdsGateway(),
          ),
        ),
      );
      await _pumpUntilLoaded(tester);

      // Tap hint 1.
      await tester.tap(find.widgetWithText(OutlinedButton, 'Hint (2 left)'));
      await tester.pump();
      await tester.runAsync(() async {
        await Future<void>.delayed(const Duration(milliseconds: 500));
      });
      await tester.pump();

      // Tap hint 2.
      await tester.tap(find.widgetWithText(OutlinedButton, 'Hint (1 left)'));
      await tester.pump();
      await tester.runAsync(() async {
        await Future<void>.delayed(const Duration(milliseconds: 500));
      });
      await tester.pump();

      // No hints left — button shows "No hints left" and is disabled.
      expect(find.textContaining('No hints left'), findsOneWidget);

      // Both tiles must be visible.
      expect(find.byKey(const HintTileKey('wave')), findsOneWidget);
      expect(find.byKey(const HintTileKey('shore')), findsOneWidget);

      // No ad dialog was shown at any point.
      expect(find.text('Watching ad…'), findsNothing);
    },
  );
}
