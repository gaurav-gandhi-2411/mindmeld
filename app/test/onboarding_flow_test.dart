/// Widget tests for the first-session onboarding puzzle (first-session-hook
/// wave): PuzzleScreen's `isOnboarding` mode (pre-seeded example tile,
/// coaching lines, dismissible nudge, skip) and OnboardingFlow's win/skip
/// analytics + graduation handoff. See spec-first-session-hook.md.
///
/// Reuses the salt/secret pairing verified in payload_codec_test.dart /
/// pack_isolation_test.dart (secret "ocean") and the
/// `_FakeExporter`/pump-helper conventions from
/// puzzle_completed_analytics_test.dart and pack_isolation_test.dart.
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
import 'package:mindmeld/features/onboarding/onboarding_config.dart';
import 'package:mindmeld/features/onboarding/onboarding_flow.dart';
import 'package:mindmeld/features/puzzle/puzzle_screen.dart';
import 'package:mindmeld/stubs/analytics_stub.dart';
import 'package:path/path.dart' as p;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

// ---------------------------------------------------------------------------
// Fakes
// ---------------------------------------------------------------------------

/// Records every logged event without touching AppPersistence/SQLite.
/// Copied from puzzle_completed_analytics_test.dart's `_FakeExporter`.
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

  Map<String, dynamic>? propsFor(String name) =>
      events.firstWhere((e) => e.$1 == name).$2;
}

/// [PayloadClient] serving a fixed onboarding payload with no I/O.
class _OnboardingPreloadedClient extends PayloadClient {
  _OnboardingPreloadedClient(this._payload);
  final DailyPayload _payload;

  @override
  Future<PayloadResult> fetchOnboarding(String lang) => Future.value(
        PayloadResult(payload: _payload, source: PayloadSource.bundledAsset),
      );
}

// ---------------------------------------------------------------------------
// Synthetic onboarding payload
// ---------------------------------------------------------------------------

/// Builds a synthetic onboarding-shaped payload with words at controlled
/// bands so coaching-copy assertions don't depend on the real (large, opaque
/// hash-only) generated payload. Reuses the salt/secret pairing verified in
/// payload_codec_test.dart / pack_isolation_test.dart's `_buildOceanPayload`
/// (secret "ocean").
///
/// Word -> rank -> band (n = 100000):
///   ocean       -> 1     -> win
///   bone        -> 3000  -> warm  (the real EXAMPLE word for 'en', see
///                            onboarding_config.dart's kOnboardingExampleWord)
///   nearish     -> 4000  -> warm
///   closeish    -> 500   -> hot
///   almost      -> 50    -> scorching
///   faraway     -> 90000 -> freezing
DailyPayload _buildOnboardingPayload({int maxGuesses = kOnboardingMaxGuesses}) {
  const salt = '7ca5996a071e2723';
  const secretS = 'TbCpaqQ='; // decodes to "ocean" with this salt
  const n = 100000;

  final words = <String, List<dynamic>>{
    PayloadCodec.hashWord('ocean', salt): [1, 65535],
    PayloadCodec.hashWord('bone', salt): [3000, 40000],
    PayloadCodec.hashWord('nearish', salt): [4000, 39000],
    PayloadCodec.hashWord('closeish', salt): [500, 50000],
    PayloadCodec.hashWord('almost', salt): [50, 60000],
    PayloadCodec.hashWord('faraway', salt): [90000, 5000],
  };

  final json = jsonEncode({
    'v': 3,
    'lang': 'en',
    'date': kOnboardingDate,
    'model': 'test',
    'n': n,
    'salt': salt,
    'words': words,
    'hints': const <List<dynamic>>[],
    's': secretS,
    'pack': kOnboardingPackId,
    'idx': kOnboardingPackIdx,
    'clue': 'A large body of salt water.',
    'maxGuesses': maxGuesses,
  });

  final bytes = Uint8List.fromList(GZipCodec().encode(utf8.encode(json)));
  return PayloadCodec.decode(bytes);
}

// ---------------------------------------------------------------------------
// Pump helpers (mirror pack_isolation_test.dart / puzzle_completed_analytics_test.dart)
// ---------------------------------------------------------------------------

Future<void> _settle(WidgetTester tester) async {
  await tester.runAsync(() async {
    await Future<void>.delayed(const Duration(milliseconds: 250));
  });
  await tester.pump();
}

Future<void> _submitAndSettle(WidgetTester tester, String word) async {
  await tester.enterText(find.byType(TextField), word);
  await tester.tap(find.text('Guess'));
  await tester.pump();
  await _settle(tester);
}

/// Submits [word] (expected to win) and drains both the real I/O and the
/// 600ms win-flash fake timer, then drains the async graduation-view fetch
/// that follows `widget.onWin()` in OnboardingFlow.
Future<void> _submitWinAndSettle(WidgetTester tester, String word) async {
  await tester.enterText(find.byType(TextField), word);
  await tester.tap(find.text('Guess'));
  await tester.pump();
  await tester.runAsync(() async {
    await Future<void>.delayed(const Duration(milliseconds: 300));
  });
  await tester.pump(const Duration(milliseconds: 700));
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
    SharedPreferences.setMockInitialValues({});
    AppPersistence.resetForTest();
    tmpDir = await Directory.systemTemp.createTemp('mindmeld_onboarding_flow_');
    await AppPersistence.instance.init(dbPath: p.join(tmpDir.path, 'test.db'));
  });

  tearDown(() async {
    await AppPersistence.instance.close();
    AppPersistence.resetForTest();
    await tmpDir.delete(recursive: true);
  });

  // ---------------------------------------------------------------------------
  // PuzzleScreen(isOnboarding: true) — presentation-layer behaviour
  // ---------------------------------------------------------------------------

  group('PuzzleScreen isOnboarding presentation', () {
    testWidgets('pre-seeded example tile is visible before any input and '
        'never counted toward the guess budget', (tester) async {
      final payload = _buildOnboardingPayload();
      await tester.pumpWidget(MaterialApp(
        home: PuzzleScreen(
          lang: 'en',
          date: kOnboardingDate,
          packId: kOnboardingPackId,
          packIdx: kOnboardingPackIdx,
          isOnboarding: true,
          payloadClient: _OnboardingPreloadedClient(payload),
          onWin: () {},
          onLoss: () {},
          onSkip: () {},
        ),
      ));
      await _settle(tester);

      expect(find.text('EXAMPLE'), findsOneWidget,
          reason: 'the pre-seeded example guess must be visible before any player input');
      expect(find.text('bone'), findsOneWidget,
          reason: 'the example word for lang=en must be rendered');
      expect(find.text('0/20 · 20 left'), findsOneWidget,
          reason: 'the example guess must NOT count toward the guess budget');
    });

    testWidgets('coaching line shows the correct copy for guesses 1-3 '
        '(freezing, warm, hot) and disappears from guess 4', (tester) async {
      final payload = _buildOnboardingPayload();
      await tester.pumpWidget(MaterialApp(
        home: PuzzleScreen(
          lang: 'en',
          date: kOnboardingDate,
          packId: kOnboardingPackId,
          packIdx: kOnboardingPackIdx,
          isOnboarding: true,
          payloadClient: _OnboardingPreloadedClient(payload),
          onWin: () {},
          onLoss: () {},
          onSkip: () {},
        ),
      ));
      await _settle(tester);

      // Guess 1: "faraway" -> freezing band -> the shared encouraging
      // freezing/cold line (an early Freezing must not read as failure).
      await _submitAndSettle(tester, 'faraway');
      expect(
        find.text("Far off — no problem, that's a clue too. Think about what the "
            'clue is about.'),
        findsOneWidget,
        reason: 'guess 1 (freezing) must show the encouraging shared freezing/cold line',
      );

      // Guess 2: "nearish" -> warm band.
      await _submitAndSettle(tester, 'nearish');
      expect(
        find.text('Warm! Related — try something closer in meaning.'),
        findsOneWidget,
        reason: 'guess 2 (warm) must show the warm coaching line',
      );
      expect(
        find.text("Far off — no problem, that's a clue too. Think about what the "
            'clue is about.'),
        findsNothing,
        reason: 'only the LATEST guess coaching line should be visible',
      );

      // Guess 3: "closeish" -> hot band.
      await _submitAndSettle(tester, 'closeish');
      expect(
        find.text('Hot! Very close now.'),
        findsOneWidget,
        reason: 'guess 3 (hot) must show the hot coaching line',
      );

      // Guess 4: "almost" -> scorching band, but guess 4 is beyond
      // kOnboardingCoachedGuesses (3) — coaching must revert to nothing.
      await _submitAndSettle(tester, 'almost');
      expect(
        find.text("Scorching — you're almost there!"),
        findsNothing,
        reason: 'coaching must disappear from guess 4 onward, reverting to '
            'the normal terse feedback',
      );
      expect(find.text('Hot! Very close now.'), findsNothing);
    });

    testWidgets('dismissible nudge shows before the first guess and can be dismissed',
        (tester) async {
      final payload = _buildOnboardingPayload();
      await tester.pumpWidget(MaterialApp(
        home: PuzzleScreen(
          lang: 'en',
          date: kOnboardingDate,
          packId: kOnboardingPackId,
          packIdx: kOnboardingPackIdx,
          isOnboarding: true,
          payloadClient: _OnboardingPreloadedClient(payload),
          onWin: () {},
          onLoss: () {},
          onSkip: () {},
        ),
      ));
      await _settle(tester);

      expect(
        find.text(kOnboardingNudge),
        findsOneWidget,
        reason: 'the one-line nudge must be visible before the first guess',
      );

      await tester.tap(find.byIcon(Icons.close));
      await tester.pump();

      expect(find.text(kOnboardingNudge), findsNothing,
          reason: 'the nudge must be dismissible and stay dismissed');
    });

    testWidgets(
      'hides rival strip, hints, give-up, and packs banner; shows Skip action',
      (tester) async {
        final payload = _buildOnboardingPayload();
        await tester.pumpWidget(MaterialApp(
          home: PuzzleScreen(
            lang: 'en',
            date: kOnboardingDate,
            packId: kOnboardingPackId,
            packIdx: kOnboardingPackIdx,
            isOnboarding: true,
            payloadClient: _OnboardingPreloadedClient(payload),
            onWin: () {},
            onLoss: () {},
            onSkip: () {},
          ),
        ));
        await _settle(tester);

        expect(find.textContaining('Hint ('), findsNothing);
        expect(find.text('Give up'), findsNothing);
        expect(find.text("Skip to today's puzzle"), findsOneWidget);
        expect(find.text('Learn to play'), findsOneWidget);
      },
    );
  });

  // ---------------------------------------------------------------------------
  // OnboardingFlow — skip / win / graduation analytics
  // ---------------------------------------------------------------------------

  group('OnboardingFlow analytics + graduation', () {
    testWidgets('skip fires onboarding_skipped and marks state done', (tester) async {
      final payload = _buildOnboardingPayload();
      final exporter = _FakeExporter();
      var doneCalled = false;

      await tester.pumpWidget(MaterialApp(
        home: OnboardingFlow(
          lang: 'en',
          today: '2026-06-12',
          payloadClient: _OnboardingPreloadedClient(payload),
          exporter: exporter,
          onDone: () => doneCalled = true,
        ),
      ));
      await _settle(tester);

      await tester.tap(find.text("Skip to today's puzzle"));
      await tester.pump();
      await tester.runAsync(() async {
        await Future<void>.delayed(const Duration(milliseconds: 200));
      });
      await tester.pump();

      expect(exporter.has(AnalyticsEvent.onboardingSkipped), isTrue);
      expect(exporter.propsFor(AnalyticsEvent.onboardingSkipped)?['lang'], equals('en'));
      expect(exporter.propsFor(AnalyticsEvent.onboardingSkipped)?['guess_count'], equals(0));
      expect(doneCalled, isTrue, reason: 'skip must call onDone immediately');

      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString(kOnboardingStateKey), equals('done'));
      expect(prefs.getString(kOnboardingGraduatedDateKey), isNull,
          reason: 'skip must NOT set onboarding_graduated_date — that is the win-path only');
    });

    testWidgets(
      'win fires onboarding_first_guess + onboarding_won, shows the graduation '
      'view, and the CTA fires graduated_to_daily + sets graduated_date + calls onDone',
      (tester) async {
        final payload = _buildOnboardingPayload();
        final exporter = _FakeExporter();
        var doneCalled = false;

        await tester.pumpWidget(MaterialApp(
          home: OnboardingFlow(
            lang: 'en',
            today: '2026-06-12',
            payloadClient: _OnboardingPreloadedClient(payload),
            exporter: exporter,
            onDone: () => doneCalled = true,
          ),
        ));
        await _settle(tester);

        await _submitWinAndSettle(tester, 'ocean');

        expect(exporter.has(AnalyticsEvent.onboardingFirstGuess), isTrue,
            reason: 'the winning guess is also the first guess');
        expect(exporter.propsFor(AnalyticsEvent.onboardingFirstGuess)?['rank'], equals(1));
        expect(exporter.has(AnalyticsEvent.onboardingWon), isTrue);
        expect(exporter.propsFor(AnalyticsEvent.onboardingWon)?['guesses_used'], equals(1));

        expect(find.text("You've got it!"), findsOneWidget,
            reason: 'winning must show the graduation view');
        expect(find.text('ocean'), findsOneWidget, reason: 'the solved secret must be shown');

        // Onboarding play must never touch daily stats/day_state (same
        // isolation invariant as themed-pack play — pack_isolation_test.dart).
        final dayState = await tester.runAsync(
          () => AppPersistence.instance.loadDayState(kOnboardingDate, 'en'),
        );
        expect(dayState, isNull, reason: 'onboarding play must never write day_state');
        final stats =
            await tester.runAsync(() => AppPersistence.instance.loadStats('en'));
        expect(stats!.played, equals(0), reason: 'onboarding play must never touch daily stats');

        await tester.tap(find.text("Play today's puzzle"));
        await tester.pump();
        await tester.runAsync(() async {
          await Future<void>.delayed(const Duration(milliseconds: 200));
        });
        await tester.pump();

        expect(exporter.has(AnalyticsEvent.graduatedToDaily), isTrue);
        expect(exporter.propsFor(AnalyticsEvent.graduatedToDaily)?['from'], equals('win'));
        expect(doneCalled, isTrue);

        final prefs = await SharedPreferences.getInstance();
        expect(prefs.getString(kOnboardingStateKey), equals('done'));
        expect(prefs.getString(kOnboardingGraduatedDateKey), equals('2026-06-12'),
            reason: 'the win path must stamp graduated_date to widget.today');
      },
    );

    testWidgets('loss shows the gentle graduation view and does NOT set graduated_date',
        (tester) async {
      final payload = _buildOnboardingPayload(maxGuesses: 1);
      final exporter = _FakeExporter();

      await tester.pumpWidget(MaterialApp(
        home: OnboardingFlow(
          lang: 'en',
          today: '2026-06-12',
          payloadClient: _OnboardingPreloadedClient(payload),
          exporter: exporter,
          onDone: () {},
        ),
      ));
      await _settle(tester);

      // maxGuesses=1: a single non-winning guess exhausts the budget -> loss.
      await tester.enterText(find.byType(TextField), 'faraway');
      await tester.tap(find.text('Guess'));
      await tester.pump();
      await tester.runAsync(() async {
        await Future<void>.delayed(const Duration(milliseconds: 300));
      });
      await tester.pump(const Duration(milliseconds: 500));
      await tester.runAsync(() async {
        await Future<void>.delayed(const Duration(milliseconds: 300));
      });
      await tester.pump();

      expect(find.textContaining('no stress, now you know how it works'), findsOneWidget);

      await tester.tap(find.text("Play today's puzzle"));
      await tester.pump();
      await tester.runAsync(() async {
        await Future<void>.delayed(const Duration(milliseconds: 200));
      });
      await tester.pump();

      expect(exporter.has(AnalyticsEvent.graduatedToDaily), isTrue);
      expect(exporter.propsFor(AnalyticsEvent.graduatedToDaily)?['from'], equals('loss'));

      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString(kOnboardingGraduatedDateKey), isNull,
          reason: 'the loss path must NOT stamp graduated_date (win-path only)');
    });
  });
}
