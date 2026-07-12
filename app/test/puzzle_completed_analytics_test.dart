/// Widget tests for the `puzzle_completed` analytics event (launch-1 wave).
///
/// [AnalyticsEvent.puzzleCompleted] must fire on every daily-mode terminal
/// state — win, budget exhausted via a guess, budget exhausted via a hint,
/// and explicit give-up — but never in practice/pack mode (`_skipStatsWrites`
/// in puzzle_screen.dart). See analytics_stub.dart's doc comment on
/// [AnalyticsEvent.puzzleCompleted] for the four `outcome` values.
///
/// The `loss_hint_exhausted` case additionally regression-tests a real
/// pre-existing bug fixed in the same edit that added this event: that path
/// recorded the loss to local persistence but never fired the
/// [AnalyticsEvent.loss] custom event at all (only the guess-exhaustion and
/// explicit-give-up paths did).
library;

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/ads/rewarded_ad_service.dart';
import 'package:mindmeld/analytics/firebase_exporter.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/payload_client.dart';
import 'package:mindmeld/core/payload_codec.dart';
import 'package:mindmeld/core/persistence.dart';
import 'package:mindmeld/features/puzzle/puzzle_screen.dart';
import 'package:mindmeld/stubs/analytics_stub.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

// ---------------------------------------------------------------------------
// Fakes
// ---------------------------------------------------------------------------

/// Records every logged event without touching AppPersistence/SQLite.
///
/// Copied from notification_opt_in_card_test.dart's `_FakeExporter` pattern
/// (private per-file, not shared/exported).
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
}

/// Returns true if [events] contains a `puzzle_completed` entry whose
/// `outcome` prop equals [outcome].
bool _hasPuzzleCompleted(List<(String, Map<String, dynamic>?)> events, String outcome) {
  return events.any((e) =>
      e.$1 == AnalyticsEvent.puzzleCompleted && e.$2?['outcome'] == outcome);
}

/// Instant-grant hint gate for tests (no ad modal, no simulated delay).
/// Mirrors flow_hardening_test.dart's `_InstantHintGate`.
class _InstantHintGate implements HintGate {
  @override
  Future<HintGateResult> requestHint(BuildContext context) =>
      Future.value(const HintGateResult(granted: true, fallback: true));
}

// ---------------------------------------------------------------------------
// Payload builder
// ---------------------------------------------------------------------------

/// Builds a gzip-compressed payload with a winning word ("ocean", rank 1), a
/// losing word ("wrongword", rank 500), [maxGuesses], and [hints].
///
/// Reuses the salt/secret pairing verified in payload_codec_test.dart and
/// other puzzle_screen tests, so a guess of "ocean" always wins.
Uint8List _buildPayloadBytes({
  required int maxGuesses,
  List<List<dynamic>> hints = const [],
}) {
  const salt = '7ca5996a071e2723';
  const secretS = 'TbCpaqQ='; // decodes to "ocean" with this salt
  final oceanHash = PayloadCodec.hashWord('ocean', salt);
  final wrongHash = PayloadCodec.hashWord('wrongword', salt);

  final json = jsonEncode({
    // v3+ required so DailyPayload.fromJson actually parses maxGuesses (see
    // models.dart fromJson: maxGuesses/clue are only read when v >= 3).
    'v': 3,
    'lang': 'en',
    'date': '2099-03-01',
    'model': 'test',
    'n': 10000,
    'salt': salt,
    'words': {
      oceanHash: [1, 65535],
      wrongHash: [500, 30000],
    },
    'hints': hints,
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

// ---------------------------------------------------------------------------
// Pump / interaction helpers
// ---------------------------------------------------------------------------

/// Pumps [PuzzleScreen] with a preloaded [payload] and the given overrides,
/// then waits for the async `_load()` (payload decode + sqflite read) to
/// complete.
Future<void> _pumpPuzzleScreen(
  WidgetTester tester, {
  required DailyPayload payload,
  bool isPractice = false,
  AnalyticsExporter? exporter,
  HintGate? hintGate,
}) async {
  await tester.pumpWidget(
    MaterialApp(
      home: PuzzleScreen(
        lang: 'en',
        date: '2099-03-01',
        onWin: () {},
        onLoss: () {},
        payloadClient: _PreloadedClient(payload),
        isPractice: isPractice,
        exporter: exporter,
        hintGate: hintGate,
      ),
    ),
  );

  await tester.runAsync(() async {
    await Future<void>.delayed(const Duration(milliseconds: 300));
  });
  await tester.pump();
}

/// Repeatedly interleaves a real-time drain ([WidgetTester.runAsync], letting
/// pending sqflite I/O complete) with a fake-clock advance
/// ([WidgetTester.pump]) for [rounds] iterations of [roundMs] each.
///
/// `_submitGuess` performs TWO sequential real awaits before scheduling its
/// terminal-outcome fake timer (`_saveState` then `recordWin`/`recordLoss`),
/// unlike `_useHint`'s single-real-await-then-timer shape. A single
/// runAsync-then-pump(duration) round (as used in
/// daily_win_navigation_test.dart's `_tapGuessAndAwaitWin`) can leave the
/// fake timer created only *after* the one pump(duration) call has already
/// run, so it's never advanced past — this loop removes the ordering
/// dependency by repeating both halves several times.
Future<void> _drainRealAndFakeAsync(
  WidgetTester tester, {
  int rounds = 6,
  int roundMs = 150,
}) async {
  for (var i = 0; i < rounds; i++) {
    await tester.runAsync(() async {
      await Future<void>.delayed(Duration(milliseconds: roundMs));
    });
    await tester.pump(Duration(milliseconds: roundMs));
  }
}

/// Types [word] into the guess field and taps "Guess", then drains both the
/// real sqflite I/O and the fake-timer delay that follows a terminal guess
/// outcome (win = 600ms, budget-exhausted loss = 400ms) via
/// [_drainRealAndFakeAsync].
Future<void> _submitGuessAndAwaitOutcome(WidgetTester tester, String word) async {
  await tester.enterText(find.byType(TextField), word);
  await tester.tap(find.text('Guess'));
  await tester.pump();
  await _drainRealAndFakeAsync(tester);
}

/// Taps the hint button (matched by its current label) and drains both the
/// real sqflite I/O and the 400ms budget-exhausted-via-hint fake-timer delay.
Future<void> _tapHintAndAwaitOutcome(WidgetTester tester, String hintButtonLabel) async {
  await tester.tap(find.widgetWithText(OutlinedButton, hintButtonLabel));
  await tester.pump();
  await tester.runAsync(() async {
    await Future<void>.delayed(const Duration(milliseconds: 300));
  });
  await tester.pump(const Duration(milliseconds: 500));
  await tester.runAsync(() async {
    await Future<void>.delayed(const Duration(milliseconds: 300));
  });
  await tester.pump();
}

/// Taps "Give up", confirms the "Give up" action in the resulting dialog, and
/// drains the resulting real sqflite write. `_giveUp()` has no fake-timer
/// delay (unlike the guess/hint terminal paths), so only runAsync is needed.
Future<void> _giveUpAndConfirm(WidgetTester tester) async {
  await tester.tap(find.widgetWithText(TextButton, 'Give up'));
  await tester.pump();

  expect(find.byType(AlertDialog), findsOneWidget,
      reason: 'sanity: the give-up confirmation dialog must appear');

  await tester.tap(find.descendant(
    of: find.byType(AlertDialog),
    matching: find.widgetWithText(TextButton, 'Give up'),
  ));
  await tester.pump();
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

  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  setUp(() async {
    AppPersistence.resetForTest();
    tmpDir = await Directory.systemTemp.createTemp('mindmeld_puzzle_completed_');
    await AppPersistence.instance.init(dbPath: p.join(tmpDir.path, 'test.db'));
  });

  tearDown(() async {
    await AppPersistence.instance.close();
    AppPersistence.resetForTest();
    await tmpDir.delete(recursive: true);
  });

  testWidgets('win fires puzzle_completed with outcome=win', (tester) async {
    final payload = PayloadCodec.decode(_buildPayloadBytes(maxGuesses: 10));
    final exporter = _FakeExporter();

    await _pumpPuzzleScreen(tester, payload: payload, exporter: exporter);
    await _submitGuessAndAwaitOutcome(tester, 'ocean');

    expect(_hasPuzzleCompleted(exporter.events, 'win'), isTrue,
        reason: 'a daily win must fire puzzle_completed with outcome=win');
  });

  testWidgets(
    'guess exhausting the budget fires puzzle_completed with outcome=loss_budget',
    (tester) async {
      final payload = PayloadCodec.decode(_buildPayloadBytes(maxGuesses: 1));
      final exporter = _FakeExporter();

      await _pumpPuzzleScreen(tester, payload: payload, exporter: exporter);
      await _submitGuessAndAwaitOutcome(tester, 'wrongword');

      expect(_hasPuzzleCompleted(exporter.events, 'loss_budget'), isTrue,
          reason: 'exhausting the guess budget must fire puzzle_completed '
              'with outcome=loss_budget');
    },
  );

  testWidgets(
    'hint exhausting the budget fires puzzle_completed with outcome=loss_hint_exhausted '
    'AND fires AnalyticsEvent.loss (bug-fix regression)',
    (tester) async {
      // maxGuesses=1 with zero guesses made: using the single available hint
      // immediately exhausts the budget (0 guesses + 1 hint >= 1).
      final payload = PayloadCodec.decode(_buildPayloadBytes(
        maxGuesses: 1,
        hints: [
          [300, 'wave'],
        ],
      ));
      final exporter = _FakeExporter();

      await _pumpPuzzleScreen(
        tester,
        payload: payload,
        exporter: exporter,
        hintGate: _InstantHintGate(),
      );
      await _tapHintAndAwaitOutcome(tester, 'Hint (1 left)');

      // The bug-fix assertion: this path previously recorded the loss to
      // local persistence but never reported it to analytics at all.
      expect(
        exporter.events.any((e) => e.$1 == AnalyticsEvent.loss),
        isTrue,
        reason: 'BUG-FIX REGRESSION: budget exhaustion via a hint must fire '
            'AnalyticsEvent.loss — this path previously recorded the loss '
            'locally but silently dropped the analytics event entirely',
      );
      expect(_hasPuzzleCompleted(exporter.events, 'loss_hint_exhausted'), isTrue,
          reason: 'exhausting the budget via a hint must fire puzzle_completed '
              'with outcome=loss_hint_exhausted');
    },
  );

  testWidgets(
    'explicit give-up fires puzzle_completed with outcome=loss_gave_up',
    (tester) async {
      final payload = PayloadCodec.decode(_buildPayloadBytes(maxGuesses: 10));
      final exporter = _FakeExporter();

      await _pumpPuzzleScreen(tester, payload: payload, exporter: exporter);

      // Submit one non-winning guess first — "Give up" only unlocks after
      // _giveUpMinGuesses (1) guesses, and this guess must not itself exhaust
      // the (generous, 10-slot) budget. No terminal outcome fires here, so
      // the drain is just settling the guess's own real sqflite write.
      await _submitGuessAndAwaitOutcome(tester, 'wrongword');
      expect(find.widgetWithText(TextButton, 'Give up'), findsOneWidget,
          reason: 'sanity: Give up must be unlocked after one guess');

      await _giveUpAndConfirm(tester);

      expect(_hasPuzzleCompleted(exporter.events, 'loss_gave_up'), isTrue,
          reason: 'an explicit give-up must fire puzzle_completed with '
              'outcome=loss_gave_up');
    },
  );

  testWidgets(
    'practice mode does NOT fire puzzle_completed (isPractice gates _skipStatsWrites)',
    (tester) async {
      final payload = PayloadCodec.decode(_buildPayloadBytes(maxGuesses: 10));
      final exporter = _FakeExporter();

      await _pumpPuzzleScreen(
        tester,
        payload: payload,
        isPractice: true,
        exporter: exporter,
      );
      await _submitGuessAndAwaitOutcome(tester, 'ocean');

      expect(
        exporter.events.any((e) => e.$1 == AnalyticsEvent.puzzleCompleted),
        isFalse,
        reason: 'practice mode must never fire puzzle_completed — '
            '_skipStatsWrites must gate it just like win/loss',
      );
      expect(
        exporter.events.any((e) => e.$1 == AnalyticsEvent.win),
        isFalse,
        reason: 'sanity: practice mode must also skip the existing win event',
      );
    },
  );
}
