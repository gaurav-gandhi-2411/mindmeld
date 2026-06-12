/// Widget tests for the hint flow (acceptance criterion 3, part A):
/// "Hint flow works end-to-end via stub."
///
/// These tests verify:
///   1. Tapping the hint button opens the RewardedAdStub's simulated-ad modal.
///   2. After the stub delay resolves, the modal is dismissed.
///   3. The hint word from the payload appears in a snackbar in the UI.
///   4. Second hint has a lower (closer-to-secret) rank than the first.
///   5. Analytics: after hint flow completes, the ring buffer contains a
///      hint_used event.
///
/// Pump strategy
/// -------------
/// Widget tests run inside fake_async; [WidgetTester.pump(duration)] advances
/// the fake clock instantly without consuming real wall-clock time.
/// The [RewardedAdStub] delay is injected as [Duration(seconds: 1)] so a
/// single [pump(Duration(seconds: 4))] fires the timer with margin.
/// SQLite I/O (sqflite_common_ffi) runs on OS threads and must be awaited
/// via [tester.runAsync]; a subsequent [pump()] then flushes any resulting
/// [setState] calls.
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
import 'package:mindmeld/stubs/analytics_stub.dart';
import 'package:mindmeld/stubs/rewarded_ad_stub.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Short delay injected into [RewardedAdStub] for these widget tests.
///
/// Must be shorter than the pump duration used in tests so the timer fires
/// when [WidgetTester.pump(const Duration(seconds: 4))] is called.
const _kAdDelay = Duration(seconds: 1);

/// Builds a gzip-compressed minimal puzzle payload with two hints.
///
/// Hint ranks are ordered so that hint 0 has a higher rank (farther from
/// secret) than hint 1 (closer to secret), verifying progressive improvement.
///
/// [salt] is reused from the known en payload so [hashWord] computes correctly
/// and so [decodeSecret] decodes to "ocean" (the real s field is borrowed too).
///
/// The vocab contains only one word (ocean at rank 1), which is sufficient
/// for testing hint delivery — hints are shown via snackbar and do not require
/// the hint word to be in the vocab lookup table.
Uint8List _buildHintPayloadBytes() {
  // Known values from the en/2026-06-12 payload.
  const salt = '7ca5996a071e2723';
  const secretS = 'TbCpaqQ='; // decodes to "ocean" with this salt

  final oceanHash = PayloadCodec.hashWord('ocean', salt);

  // n=10 lets bandForRank produce non-trivial bands without a huge vocab.
  const n = 10;

  final json = jsonEncode({
    'v': 1,
    'lang': 'en',
    'date': '2099-01-01', // fictional date; avoids collision with real assets
    'model': 'test',
    'n': n,
    'salt': salt,
    'words': {
      oceanHash: [1, 65535],
    },
    // Two hints: rank 8 (far) then rank 4 (closer) — second is lower rank.
    'hints': [
      [8, 'wave'],
      [4, 'shore'],
    ],
    's': secretS,
  });

  return Uint8List.fromList(GZipCodec().encode(utf8.encode(json)));
}

/// [PayloadClient] that returns a pre-built [DailyPayload] without any I/O.
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

/// Pump the PuzzleScreen until it has finished its async [_load] call.
///
/// Uses [tester.runAsync] to allow the SQLite FFI operations on OS threads,
/// then pumps to flush any resulting [setState] calls.
Future<void> _pumpUntilLoaded(WidgetTester tester) async {
  await tester.runAsync(() async {
    await Future<void>.delayed(const Duration(milliseconds: 200));
  });
  await tester.pump();
}

/// Build and pump the PuzzleScreen with a synthetic hint payload.
Future<void> _pumpPuzzleScreen(
  WidgetTester tester,
  DailyPayload payload,
) async {
  await tester.pumpWidget(
    MaterialApp(
      home: PuzzleScreen(
        lang: 'en',
        date: '2099-01-01',
        onWin: () {},
        payloadClient: _PreloadedClient(payload),
        adStub: const RewardedAdStub(simulatedDelay: _kAdDelay),
      ),
    ),
  );
  await _pumpUntilLoaded(tester);
}

/// Perform a complete hint flow: tap button → drain timer → drain DB writes.
///
/// Returns after the snackbar setState has been flushed.
Future<void> _triggerHint(WidgetTester tester, String buttonLabel) async {
  // 1. Tap the hint button.
  await tester.tap(find.widgetWithText(OutlinedButton, buttonLabel));

  // 2. One pump: the dialog is shown synchronously inside _showSimulated
  //    before the first `await Future.delayed(...)`.
  await tester.pump();

  // 3. Advance fake clock past _kAdDelay (1 s < 4 s → timer fires).
  //    This also processes the Navigator.pop() that dismisses the dialog
  //    and schedules the async continuation in _useHint.
  await tester.pump(const Duration(seconds: 4));

  // 4. The async continuation (_useHint after `granted`) involves SQLite
  //    writes (saveDayState, logEvent) which run on OS threads.
  //    runAsync lets those complete.  Use 800 ms to cover both writes.
  await tester.runAsync(() async {
    await Future<void>.delayed(const Duration(milliseconds: 800));
  });

  // 5. Pump again to flush any setState() calls from the async continuation.
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

    // Decode the synthetic payload once for all tests.
    hintPayload = PayloadCodec.decode(_buildHintPayloadBytes());
  });

  setUp(() async {
    AppPersistence.resetForTest();
    tmpDir = await Directory.systemTemp.createTemp('mindmeld_hint_');
    final dbPath = p.join(tmpDir.path, 'hint_test.db');
    await AppPersistence.instance.init(dbPath: dbPath);
  });

  tearDown(() async {
    await AppPersistence.instance.close();
    AppPersistence.resetForTest();
    await tmpDir.delete(recursive: true);
  });

  // -------------------------------------------------------------------------
  // Payload sanity
  // -------------------------------------------------------------------------

  test('synthetic hint payload has two hints with correct ranks', () {
    expect(hintPayload.hints.length, equals(2));
    expect(hintPayload.hints[0].word, equals('wave'));
    expect(hintPayload.hints[0].rank, equals(8));
    expect(hintPayload.hints[1].word, equals('shore'));
    expect(hintPayload.hints[1].rank, equals(4));

    // Second hint must have a lower (closer-to-secret) rank than the first.
    expect(
      hintPayload.hints[1].rank,
      lessThan(hintPayload.hints[0].rank),
      reason: 'Second hint should be closer to the secret (lower rank)',
    );
  });

  // -------------------------------------------------------------------------
  // Hint button renders
  // -------------------------------------------------------------------------

  testWidgets('hint button is visible after puzzle loads', (tester) async {
    await _pumpPuzzleScreen(tester, hintPayload);

    // The hint button label includes the remaining hint count.
    expect(find.textContaining('Hint'), findsOneWidget);
    expect(find.textContaining('2 left'), findsOneWidget);
  });

  // -------------------------------------------------------------------------
  // Simulated-ad modal appears when hint is tapped
  // -------------------------------------------------------------------------

  testWidgets(
    'tapping hint button shows the simulated-ad dialog',
    (tester) async {
      await _pumpPuzzleScreen(tester, hintPayload);

      // Tap the hint button.
      await tester.tap(find.widgetWithText(OutlinedButton, 'Hint (2 left)'));

      // One pump: showDialog() executes synchronously inside _showSimulated
      // before the first `await Future.delayed(...)`, so the dialog is now
      // present in the tree.
      await tester.pump();

      // The simulated-ad modal should now be visible.
      expect(find.text('Watching ad…'), findsOneWidget);

      // Drain the pending timer before the test tears down; otherwise the
      // fakeAsync assertion fires.  Also let DB writes finish.
      await tester.pump(const Duration(seconds: 4));
      await tester.runAsync(() async {
        await Future<void>.delayed(const Duration(milliseconds: 300));
      });
      await tester.pump();
    },
  );

  // -------------------------------------------------------------------------
  // Modal dismisses and snackbar shows hint word
  // -------------------------------------------------------------------------

  testWidgets(
    'after stub delay resolves, modal is dismissed and hint snackbar appears',
    (tester) async {
      await _pumpPuzzleScreen(tester, hintPayload);

      await _triggerHint(tester, 'Hint (2 left)');

      // The "Watching ad…" dialog must be gone.
      expect(find.text('Watching ad…'), findsNothing);

      // The snackbar with the first hint word ("wave") must be visible.
      // PuzzleScreen._useHint shows: 'Hint: "$word" is ranked #$rank'
      expect(find.textContaining('"wave"'), findsOneWidget);
      expect(find.textContaining('ranked #8'), findsOneWidget);
    },
  );

  // -------------------------------------------------------------------------
  // Second hint has lower (closer) rank
  // -------------------------------------------------------------------------

  testWidgets(
    'second hint has a lower rank than first hint (progressively closer)',
    (tester) async {
      await _pumpPuzzleScreen(tester, hintPayload);

      // Structural assertion on the payload itself.
      final firstRank = hintPayload.hints[0].rank;
      final secondRank = hintPayload.hints[1].rank;
      expect(secondRank, lessThan(firstRank));

      // ── First hint ──
      await _triggerHint(tester, 'Hint (2 left)');

      // Snackbar for hint 1 ("wave", rank 8).
      expect(find.textContaining('"wave"'), findsOneWidget);

      // Advance fake clock past the snackbar's 5-second display duration,
      // then pump through the exit animation (~300 ms).
      await tester.pump(const Duration(seconds: 6));
      await tester.pump(const Duration(milliseconds: 400));
      await tester.pump(const Duration(milliseconds: 400));

      // ── Second hint — inline for precise control ──
      await tester.tap(find.widgetWithText(OutlinedButton, 'Hint (1 left)'));
      // One pump: showDialog() fires, dialog appears.
      await tester.pump();
      // Advance past the _kAdDelay (1 s).
      await tester.pump(const Duration(seconds: 4));
      // DB writes and setState on OS threads.
      await tester.runAsync(() async {
        await Future<void>.delayed(const Duration(milliseconds: 800));
      });
      // Flush setState calls and let the snackbar enter animation start.
      for (var i = 0; i < 5; i++) {
        await tester.pump(const Duration(milliseconds: 100));
      }

      // Snackbar for hint 2 ("shore", rank 4) — lower rank means closer.
      expect(find.textContaining('"shore"'), findsOneWidget);
      expect(find.textContaining('ranked #4'), findsOneWidget);
    },
  );

  // -------------------------------------------------------------------------
  // Analytics ring buffer contains hint_used after hint flow
  // -------------------------------------------------------------------------

  testWidgets(
    'after hint flow the analytics ring buffer contains a hint_used event',
    (tester) async {
      await _pumpPuzzleScreen(tester, hintPayload);

      // Trigger the hint flow.
      await _triggerHint(tester, 'Hint (2 left)');

      // Query the analytics ring buffer directly via the persistence API.
      // exportAnalyticsBuffer() queries the same SQLite DB used during the test.
      final List<Map<String, dynamic>> events = await tester.runAsync(() async {
        return AppPersistence.instance.exportAnalyticsBuffer();
      }) ?? [];

      final hintEvents = events
          .where((e) => e['event_name'] == AnalyticsEvent.hintUsed)
          .toList();

      expect(
        hintEvents,
        isNotEmpty,
        reason: 'At least one hint_used event must be logged after hint flow',
      );

      // The logged event should record the hint index (0-based) and rank.
      final firstHintEvent = hintEvents.first;
      final props = jsonDecode(firstHintEvent['props_json'] as String)
          as Map<String, dynamic>;
      expect(props['hint_index'], equals(0));
      expect(props['hint_rank'], equals(8)); // first hint rank
    },
  );
}
