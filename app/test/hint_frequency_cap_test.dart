/// Widget tests for the daily hint frequency cap (Phase 2 requirement).
///
/// The cap [AppConfig.maxHintsPerDay] = 5 is a product rule that applies in
/// all modes (stub and real AdMob). After 5 hints have been revealed:
///   - The hint button must be disabled (onPressed == null).
///   - The button label must read "No more hints today".
///   - Tapping has no effect — no 6th hint can be revealed.
///
/// Strategy: build a [DayState] with [revealedHints.length] == 5 pre-loaded
/// into the persistence layer (bypassing the ad gate entirely) and verify the
/// UI reflects the capped state. A separate test verifies that with 4 revealed
/// hints the button is still enabled, guarding the boundary.
library;

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/core/config.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/payload_client.dart';
import 'package:mindmeld/core/payload_codec.dart';
import 'package:mindmeld/core/persistence.dart';
import 'package:mindmeld/features/puzzle/puzzle_screen.dart';
import 'package:mindmeld/stubs/rewarded_ad_stub.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Builds a gzip-compressed payload with [hintCount] hints.
///
/// Uses 6 hints so the cap (5) can be tested with one hint still in the
/// payload — confirming the cap is a separate gate from "no hints left".
Uint8List _buildPayloadWithHints(int hintCount) {
  const salt = '7ca5996a071e2723';
  const secretS = 'TbCpaqQ='; // decodes to "ocean" with this salt

  final oceanHash = PayloadCodec.hashWord('ocean', salt);

  final hints = List<List<dynamic>>.generate(
    hintCount,
    (i) => [10 + i, 'hint_word_$i'],
  );

  final json = jsonEncode({
    'v': 1,
    'lang': 'en',
    'date': '2099-02-01',
    'model': 'test',
    'n': 10000,
    'salt': salt,
    'words': {
      oceanHash: [1, 65535],
    },
    'hints': hints,
    's': secretS,
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

/// Pump [PuzzleScreen] with a preloaded payload and an optional initial
/// [DayState] saved to persistence.
///
/// [initialState] must be saved BEFORE [pumpWidget] so that [PuzzleScreen._load]
/// can read it. The save is done inside [tester.runAsync] to keep sqflite I/O
/// off the fakeAsync scheduler (which can deadlock on OS-thread futures).
Future<void> _pumpPuzzleScreen(
  WidgetTester tester, {
  required DailyPayload payload,
  DayState? initialState,
}) async {
  // Save the initial state with real async (runAsync exits fakeAsync zone).
  if (initialState != null) {
    await tester.runAsync(() async {
      await AppPersistence.instance.saveDayState(initialState);
    });
  }

  await tester.pumpWidget(
    MaterialApp(
      home: PuzzleScreen(
        lang: 'en',
        date: '2099-02-01',
        onWin: () {},
        payloadClient: _PreloadedClient(payload),
        // Stub with short non-zero delay; Duration.zero can cause fakeAsync
        // timing issues. This stub is only triggered if the cap is NOT reached
        // (it won't be triggered in the cap tests).
        adStub: const RewardedAdStub(simulatedDelay: Duration(milliseconds: 1)),
      ),
    ),
  );

  // Wait for async _load (SQLite + payload decode).
  await tester.runAsync(() async {
    await Future<void>.delayed(const Duration(milliseconds: 300));
  });
  await tester.pump();
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  late Directory tmpDir;
  late DailyPayload payload;

  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;

    // 6 hints in the payload so there is still one left when cap=5 is hit.
    payload = PayloadCodec.decode(_buildPayloadWithHints(6));
  });

  setUp(() async {
    AppPersistence.resetForTest();
    tmpDir = await Directory.systemTemp.createTemp('mindmeld_cap_');
    await AppPersistence.instance.init(
      dbPath: p.join(tmpDir.path, 'cap_test.db'),
    );
  });

  tearDown(() async {
    await AppPersistence.instance.close();
    AppPersistence.resetForTest();
    await tmpDir.delete(recursive: true);
  });

  // -------------------------------------------------------------------------
  // Sanity: cap constant is 5
  // -------------------------------------------------------------------------

  test('AppConfig.maxHintsPerDay is 5', () {
    expect(AppConfig.maxHintsPerDay, equals(5));
  });

  // -------------------------------------------------------------------------
  // At cap: button disabled and labelled "No more hints today"
  // -------------------------------------------------------------------------

  testWidgets(
    'hint button is disabled and shows "No more hints today" when '
    'revealedHints.length == maxHintsPerDay',
    (tester) async {
      // Pre-load day state with exactly maxHintsPerDay revealed hints.
      final cappedState = DayState(
        date: '2099-02-01',
        lang: 'en',
        guesses: [],
        hintsUsed: AppConfig.maxHintsPerDay,
        won: false,
        gaveUp: false,
        revealedHints: List.generate(
          AppConfig.maxHintsPerDay,
          (i) => RevealedHint(rank: 10 + i, word: 'hint_word_$i'),
        ),
      );

      await _pumpPuzzleScreen(tester, payload: payload, initialState: cappedState);

      // Button must show cap message.
      expect(find.text('No more hints today'), findsOneWidget);

      // The OutlinedButton must be disabled (onPressed == null).
      final button = tester.widget<OutlinedButton>(
        find.widgetWithText(OutlinedButton, 'No more hints today'),
      );
      expect(button.onPressed, isNull,
          reason: 'Hint button must be disabled when daily cap is reached');
    },
  );

  // -------------------------------------------------------------------------
  // One below cap: button still enabled
  // -------------------------------------------------------------------------

  testWidgets(
    'hint button is enabled when revealedHints.length == maxHintsPerDay - 1',
    (tester) async {
      final almostCappedState = DayState(
        date: '2099-02-01',
        lang: 'en',
        guesses: [],
        hintsUsed: AppConfig.maxHintsPerDay - 1,
        won: false,
        gaveUp: false,
        revealedHints: List.generate(
          AppConfig.maxHintsPerDay - 1,
          (i) => RevealedHint(rank: 10 + i, word: 'hint_word_$i'),
        ),
      );

      await _pumpPuzzleScreen(
        tester,
        payload: payload,
        initialState: almostCappedState,
      );

      // Should still show the hint button as enabled (one hint remaining today).
      final hintButtons = tester
          .widgetList<OutlinedButton>(find.byType(OutlinedButton))
          .where((b) => b.onPressed != null)
          .toList();

      expect(hintButtons, isNotEmpty,
          reason: 'Hint button must still be enabled at cap - 1 hints');

      // Must NOT show the cap message.
      expect(find.text('No more hints today'), findsNothing);
    },
  );

  // -------------------------------------------------------------------------
  // No 6th hint can be revealed (tapping disabled button has no effect)
  // -------------------------------------------------------------------------

  testWidgets(
    'tapping the disabled hint button at cap does not reveal a 6th hint',
    (tester) async {
      final cappedState = DayState(
        date: '2099-02-01',
        lang: 'en',
        guesses: [],
        hintsUsed: AppConfig.maxHintsPerDay,
        won: false,
        gaveUp: false,
        revealedHints: List.generate(
          AppConfig.maxHintsPerDay,
          (i) => RevealedHint(rank: 10 + i, word: 'hint_word_$i'),
        ),
      );

      await _pumpPuzzleScreen(tester, payload: payload, initialState: cappedState);

      // Attempt to tap the button (it is disabled, Flutter ignores the tap).
      await tester.tap(
        find.widgetWithText(OutlinedButton, 'No more hints today'),
        warnIfMissed: false,
      );
      await tester.pump(Duration.zero);
      await tester.runAsync(() async {
        await Future<void>.delayed(const Duration(milliseconds: 100));
      });
      await tester.pump();

      // Reload day state from DB and confirm hint count did not increase.
      final loaded = await tester.runAsync(() async {
        return AppPersistence.instance.loadDayState('2099-02-01', 'en');
      });

      final finalState = loaded!;
      expect(
        finalState.revealedHints.length,
        equals(AppConfig.maxHintsPerDay),
        reason: 'No 6th hint must be revealed when daily cap is reached',
      );
    },
  );
}
