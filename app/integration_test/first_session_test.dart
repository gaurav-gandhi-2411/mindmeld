/// Integration tests for the first-session onboarding funnel
/// (first-session-hook wave): a brand-new player is routed into a dedicated
/// onboarding puzzle before their first daily, in both supported languages,
/// with resume-not-strand and skip-escape behaviour, while an existing
/// (legacy-onboarded) player is never shown it.
///
/// See features/onboarding/first_run.dart for the gate's exact resolution
/// order and onboarding_config.dart for the onboarding puzzle's identity
/// (secrets: EN "dog", hi-en "paani"; example word: EN "bone", hi-en "nadi").
/// Companion to app_test.dart (guess -> win loop against the live daily
/// host) — this file additionally exercises the onboarding gate, the
/// bundled-asset onboarding puzzle (no network required), and graduation
/// into the live daily. See app_test.dart's own header for CI invocation /
/// network prerequisites, which this file shares.
///
/// Note on host execution: `flutter test integration_test/first_session_test.dart`
/// requires a connected device (or the `windows`/`chrome` desktop/web
/// devices on the host). The file compiles cleanly under `flutter analyze`
/// and is covered by static analysis on the host without a device.
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:mindmeld/core/config.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/payload_client.dart';
import 'package:mindmeld/core/payload_codec.dart';
import 'package:mindmeld/core/persistence.dart';
import 'package:mindmeld/features/onboarding/first_run.dart';
import 'package:mindmeld/features/onboarding/onboarding_config.dart';
import 'package:mindmeld/main.dart';
import 'package:path/path.dart' as p;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

// ---------------------------------------------------------------------------
// Helpers (mirrors app_test.dart's conventions)
// ---------------------------------------------------------------------------

/// Initialise sqflite for the desktop/host environment (no-op on Android).
void _initSqfliteForPlatform() {
  if (!Platform.isAndroid && !Platform.isIOS) {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  }
}

/// Create a per-test temporary directory for an isolated SQLite database.
///
/// Prevents state written in one test from bleeding into the next when
/// [AppPersistence] re-opens the same on-disk file.
Future<(Directory, String)> _createTestDbPath(String prefix) async {
  final dir = await Directory.systemTemp.createTemp(prefix);
  final path = p.join(dir.path, 'test.db');
  return (dir, path);
}

/// Loads the bundled onboarding payload for [lang] directly (no network) so
/// secret/clue/example-word assertions never hardcode blindly.
Future<PayloadResult> _loadOnboardingPayload(String lang) =>
    PayloadClient().loadBundledOnboarding(lang);

/// Submits [word] as a guess via the visible guess input and waits for the
/// resulting state update to settle.
Future<void> _submitGuess(WidgetTester tester, String word) async {
  await tester.enterText(find.byType(TextField), word);
  await tester.tap(find.text('Guess'));
  await tester.pumpAndSettle(const Duration(seconds: 3));
}

/// Submits [word] (expected to win) and waits for the win-flash animation
/// plus the onboarding graduation view's secret-decode fetch to settle.
Future<void> _submitWinningGuess(WidgetTester tester, String word) async {
  await tester.enterText(find.byType(TextField), word);
  await tester.tap(find.text('Guess'));
  await tester.pumpAndSettle(const Duration(seconds: 5));
}

/// Asserts the tabbed daily-board app shell is showing (onboarding surface
/// gone) — the bottom [NavigationBar] only ever exists on that shell, never
/// on [OnboardingFlow]'s own bare [Scaffold].
void _expectDailyBoardShown() {
  expect(find.text('Learn to play'), findsNothing,
      reason: 'the onboarding surface must be gone once the daily board is showing');
  expect(find.byType(NavigationBar), findsOneWidget,
      reason: 'the tabbed app shell (daily board) must be visible');
  expect(find.byType(TextField), findsOneWidget,
      reason: "the daily puzzle's guess input must be visible");
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

// Shared with app_test.dart — payloads for this date are served by the live
// GitHub Pages payload host.
const _dailyTestDate = '2026-06-12';
const _liveBaseUrl = AppConfig.payloadBaseUrl;

// In-vocab, non-secret guess used to exercise the coaching-line copy before
// the player wins — see setUpAll for the dynamically-resolved band/coaching
// line this guess actually produces (never hardcoded blindly).
const _wrongishGuess = 'cat';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  // Sanity-checked once before any test runs — see setUpAll body.
  late String enSecret;
  late String enClue;
  late String enExampleWord;
  late String enCoachingLineForWrongishGuess;
  late String hiEnSecret;
  late String hiEnClue;
  late String hiEnExampleWord;

  setUpAll(() async {
    _initSqfliteForPlatform();

    final enResult = await _loadOnboardingPayload('en');
    final hiEnResult = await _loadOnboardingPayload('hi-en');

    enSecret = PayloadCodec.decodeSecret(enResult.payload);
    enClue = enResult.payload.clue ?? '';
    enExampleWord = exampleWordFor('en');
    hiEnSecret = PayloadCodec.decodeSecret(hiEnResult.payload);
    hiEnClue = hiEnResult.payload.clue ?? '';
    hiEnExampleWord = exampleWordFor('hi-en');

    // Fail fast if the onboarding payload was regenerated with different
    // secrets — this wave's whole design depends on these exact words.
    assert(enSecret == 'dog',
        'onboarding en secret expected "dog", got "$enSecret"');
    assert(hiEnSecret == 'paani',
        'onboarding hi-en secret expected "paani", got "$hiEnSecret"');

    // Dynamically resolve the coaching line the "cat" guess actually
    // produces against the live onboarding payload, rather than hardcoding
    // a band that could silently drift if the payload is regenerated.
    final catEntry = PayloadCodec.lookupWord(_wrongishGuess, enResult.payload);
    assert(catEntry != null,
        '"$_wrongishGuess" must be in-vocab for the en onboarding payload');
    final catBand = bandForRank(catEntry!.rank, enResult.payload.n);
    enCoachingLineForWrongishGuess = coachingLineFor(catBand);
  });

  testWidgets(
    'cold-profile EN: onboarding puzzle -> coaching -> win -> graduate to daily',
    (tester) async {
      SharedPreferences.setMockInitialValues({});
      AppPersistence.resetForTest();
      final (dbDir, dbPath) = await _createTestDbPath('mindmeld_fs_en_');

      final overrides = AppOverrides(
        payloadClient: PayloadClient(baseUrl: _liveBaseUrl),
        fixedDate: _dailyTestDate,
        lang: 'en',
        dbPath: dbPath,
      );

      await tester.pumpWidget(WarmerApp(overrides: overrides));
      await tester.pumpAndSettle(const Duration(seconds: 10));

      // ── Onboarding puzzle shown, example tile visible before any input ──
      expect(find.text('Learn to play'), findsOneWidget);
      expect(find.text(enClue), findsOneWidget,
          reason: 'the onboarding clue must be visible');
      expect(find.text('EXAMPLE'), findsOneWidget);
      expect(find.text(enExampleWord), findsOneWidget,
          reason: 'the pre-seeded example guess must be visible before any input');

      // ── Wrong-ish guess -> coaching line appears ─────────────────────────
      await _submitGuess(tester, _wrongishGuess);
      expect(find.text(_wrongishGuess), findsWidgets,
          reason: 'the guess must appear in the onboarding guess history');
      expect(find.text(enCoachingLineForWrongishGuess), findsOneWidget,
          reason: 'plain-language coaching must appear for guesses 1-3');

      // ── Win with the secret -> graduation view ───────────────────────────
      await _submitWinningGuess(tester, enSecret);
      expect(find.text("You've got it!"), findsOneWidget,
          reason: 'winning must show the graduation view');
      expect(find.text(enSecret), findsOneWidget,
          reason: 'the solved secret must be shown');

      // ── Graduate into today's daily ──────────────────────────────────────
      await tester.tap(find.text("Play today's puzzle"));
      await tester.pumpAndSettle(const Duration(seconds: 10));

      _expectDailyBoardShown();

      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString(kOnboardingStateKey), equals('done'),
          reason: 'graduating must mark the onboarding puzzle done');

      await AppPersistence.instance.close();
      AppPersistence.resetForTest();
      await dbDir.delete(recursive: true);
    },
  );

  testWidgets(
    'cold-profile Hinglish: language toggle swaps the onboarding puzzle, '
    'win -> graduate to the hi-en daily',
    (tester) async {
      SharedPreferences.setMockInitialValues({});
      AppPersistence.resetForTest();
      final (dbDir, dbPath) = await _createTestDbPath('mindmeld_fs_hien_');

      final overrides = AppOverrides(
        payloadClient: PayloadClient(baseUrl: _liveBaseUrl),
        fixedDate: _dailyTestDate,
        lang: 'en',
        dbPath: dbPath,
      );

      await tester.pumpWidget(WarmerApp(overrides: overrides));
      await tester.pumpAndSettle(const Duration(seconds: 10));

      expect(find.text('Learn to play'), findsOneWidget);
      expect(find.text(enClue), findsOneWidget);

      // ── Toggle to Hinglish via the in-flow language switch ───────────────
      await tester.tap(find.text('Hinglish'));
      await tester.pumpAndSettle(const Duration(seconds: 5));

      expect(find.text(hiEnClue), findsOneWidget,
          reason: 'the clue must swap to the hi-en onboarding clue');
      expect(find.text(hiEnExampleWord), findsOneWidget,
          reason: 'the example tile must swap to the hi-en example word');

      // ── Win with the hi-en secret -> graduation view ─────────────────────
      await _submitWinningGuess(tester, hiEnSecret);
      expect(find.text("You've got it!"), findsOneWidget);
      expect(find.text(hiEnSecret), findsOneWidget);

      // ── Graduate into today's hi-en daily ─────────────────────────────────
      await tester.tap(find.text("Play today's puzzle"));
      await tester.pumpAndSettle(const Duration(seconds: 10));

      _expectDailyBoardShown();
      expect(find.textContaining('Hinglish'), findsWidgets,
          reason: 'the daily board must stay on hi-en after graduation');

      await AppPersistence.instance.close();
      AppPersistence.resetForTest();
      await dbDir.delete(recursive: true);
    },
  );

  testWidgets(
    'existing user (legacy onboarding_done=true) boots straight to the '
    'daily — the onboarding puzzle is never shown',
    (tester) async {
      SharedPreferences.setMockInitialValues({kLegacyOnboardingDonePref: true});
      AppPersistence.resetForTest();
      final (dbDir, dbPath) = await _createTestDbPath('mindmeld_fs_existing_');

      final overrides = AppOverrides(
        payloadClient: PayloadClient(baseUrl: _liveBaseUrl),
        fixedDate: _dailyTestDate,
        lang: 'en',
        dbPath: dbPath,
      );

      await tester.pumpWidget(WarmerApp(overrides: overrides));
      await tester.pumpAndSettle(const Duration(seconds: 10));

      _expectDailyBoardShown();

      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString(kOnboardingStateKey), equals('done'),
          reason: 'the legacy grandfather check must persist done going forward');

      await AppPersistence.instance.close();
      AppPersistence.resetForTest();
      await dbDir.delete(recursive: true);
    },
  );

  testWidgets(
    'resume, no strand: an in-progress onboarding guess survives an app '
    'restart instead of being stranded or reset',
    (tester) async {
      SharedPreferences.setMockInitialValues({});
      AppPersistence.resetForTest();
      final (dbDir, dbPath) = await _createTestDbPath('mindmeld_fs_resume_');

      final overrides = AppOverrides(
        payloadClient: PayloadClient(baseUrl: _liveBaseUrl),
        fixedDate: _dailyTestDate,
        lang: 'en',
        dbPath: dbPath,
      );

      await tester.pumpWidget(WarmerApp(overrides: overrides));
      await tester.pumpAndSettle(const Duration(seconds: 10));
      expect(find.text('Learn to play'), findsOneWidget);

      await _submitGuess(tester, _wrongishGuess);
      expect(find.text(_wrongishGuess), findsWidgets);

      // ── "Restart" the app: remount WarmerApp with the same dbPath/prefs ──
      await tester.pumpWidget(WarmerApp(overrides: overrides));
      await tester.pumpAndSettle(const Duration(seconds: 10));

      expect(find.text('Learn to play'), findsOneWidget,
          reason: 'an interrupted onboarding must resume, not fall through to the daily');
      expect(find.text(_wrongishGuess), findsWidgets,
          reason: 'the guess made before restart must still be on the board');

      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString(kOnboardingStateKey), equals('started'),
          reason: 'resuming must not mutate the stored state to done prematurely');

      await AppPersistence.instance.close();
      AppPersistence.resetForTest();
      await dbDir.delete(recursive: true);
    },
  );

  testWidgets(
    'skip escape: "Skip to today\'s puzzle" jumps straight to the daily and '
    'stays there across a restart',
    (tester) async {
      SharedPreferences.setMockInitialValues({});
      AppPersistence.resetForTest();
      final (dbDir, dbPath) = await _createTestDbPath('mindmeld_fs_skip_');

      final overrides = AppOverrides(
        payloadClient: PayloadClient(baseUrl: _liveBaseUrl),
        fixedDate: _dailyTestDate,
        lang: 'en',
        dbPath: dbPath,
      );

      await tester.pumpWidget(WarmerApp(overrides: overrides));
      await tester.pumpAndSettle(const Duration(seconds: 10));
      expect(find.text('Learn to play'), findsOneWidget);

      await tester.tap(find.text("Skip to today's puzzle"));
      await tester.pumpAndSettle(const Duration(seconds: 10));

      _expectDailyBoardShown();

      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString(kOnboardingStateKey), equals('done'),
          reason: 'skipping must mark the onboarding puzzle done');

      // ── "Restart" the app: remount WarmerApp with the same dbPath/prefs ──
      await tester.pumpWidget(WarmerApp(overrides: overrides));
      await tester.pumpAndSettle(const Duration(seconds: 10));

      _expectDailyBoardShown();

      await AppPersistence.instance.close();
      AppPersistence.resetForTest();
      await dbDir.delete(recursive: true);
    },
  );
}
