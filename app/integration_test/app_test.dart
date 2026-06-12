/// Integration test: full guess → win loop for both [en] and [hi-en] languages.
///
/// Prerequisites:
///   - Bundled payloads for 2026-06-12 must be present in assets/.
///   - Run on an Android emulator: `flutter test integration_test` with a
///     connected device.
///
/// What this test covers per language:
///   1. App launches with the puzzle screen (onboarding skipped, date pinned).
///   2. A known non-secret in-vocab guess produces a ranked history tile with
///      a temperature band label.
///   3. A garbage non-vocab guess ("zzzqqq") produces the friendly rejection.
///   4. The actual secret (decoded from the bundled payload at test time)
///      produces the win screen showing the revealed word.
///   5. The share card text visible on the win screen does NOT contain the
///      secret word.
///
/// The test uses [AppOverrides] to:
///   - Pin the puzzle date to 2026-06-12 regardless of device clock.
///   - Inject a [_BundleOnlyClient] that throws on network so the app always
///     uses the bundled asset (no network dependency in CI).
///   - Skip the onboarding gate.
///
/// Sanity checks asserted in setUp (not hardcoded blindly):
///   - en  2026-06-12 secret == "ocean"
///   - hi-en 2026-06-12 secret == "samunder"
///
/// Note on host execution:
///   `flutter test integration_test/app_test.dart` requires a connected
///   device or emulator.  The file compiles cleanly under `flutter analyze`
///   and is covered by static analysis on the host without a device.
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/payload_client.dart';
import 'package:mindmeld/core/payload_codec.dart';
import 'package:mindmeld/core/persistence.dart';
import 'package:mindmeld/main.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// [PayloadClient] that always serves the bundled asset, skipping network.
///
/// [fetch] overrides the default network-first strategy with a direct
/// [loadBundled] call so integration tests are fully offline.
class _BundleOnlyClient extends PayloadClient {
  _BundleOnlyClient() : super(assetBundle: rootBundle);

  @override
  Future<PayloadResult> fetch(String lang, String date) =>
      loadBundled(lang, date);
}

/// Decode the secret for [lang]/[date] from the bundled asset at test time.
///
/// Used to sanity-check known secrets and to obtain the winning word without
/// hardcoding it blindly.
Future<String> _decodeSecret(String lang, String date) async {
  final client = _BundleOnlyClient();
  final result = await client.fetch(lang, date);
  return PayloadCodec.decodeSecret(result.payload);
}

/// Return a non-secret in-vocab word for [lang]/[date].
///
/// Uses the first hint word from the payload — hints are guaranteed to be
/// in-vocab and have rank > 1 (i.e. not the secret).
Future<String> _firstHintWord(String lang, String date) async {
  final client = _BundleOnlyClient();
  final result = await client.fetch(lang, date);
  return result.payload.hints.first.word;
}

/// Initialise sqflite for the desktop/host environment (no-op on Android).
void _initSqfliteForPlatform() {
  if (!Platform.isAndroid && !Platform.isIOS) {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  }
}

/// Create a per-test temporary directory for an isolated SQLite database.
///
/// Prevents won/gave-up day state written in one test from bleeding into the
/// next test when [AppPersistence] re-opens the same on-disk file.
Future<(Directory, String)> _createTestDbPath() async {
  final dir = await Directory.systemTemp.createTemp('mindmeld_itest_');
  final path = p.join(dir.path, 'test.db');
  return (dir, path);
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const _testDate = '2026-06-12';
const _garbageWord = 'zzzqqq';

// Bundled range for both langs: 2026-06-12..18 — date is within range.

// ---------------------------------------------------------------------------
// Test body
// ---------------------------------------------------------------------------

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  // Sanity-check secrets once before any test runs.
  // These assertions prevent silent regressions if the payload is regenerated.
  late String enSecret;
  late String hiEnSecret;
  late String enHintWord;
  late String hiEnHintWord;

  setUpAll(() async {
    _initSqfliteForPlatform();

    enSecret = await _decodeSecret('en', _testDate);
    hiEnSecret = await _decodeSecret('hi-en', _testDate);
    enHintWord = await _firstHintWord('en', _testDate);
    hiEnHintWord = await _firstHintWord('hi-en', _testDate);

    // Fail fast if the payload was regenerated with a different secret.
    assert(enSecret == 'ocean',
        'en 2026-06-12 secret expected "ocean", got "$enSecret"');
    assert(hiEnSecret == 'samunder',
        'hi-en 2026-06-12 secret expected "samunder", got "$hiEnSecret"');
  });

  // Run each language pass in a separate test for clear CI reporting.
  for (final lang in ['en', 'hi-en']) {
    testWidgets('guess → win loop ($lang)', (tester) async {
      // Each test gets its own isolated SQLite file so won/gave-up state written
      // during the en pass cannot bleed into the hi-en pass.
      final (testDbDir, testDbPath) = await _createTestDbPath();

      // Reset singleton so AppPersistence.init() opens the fresh per-test file.
      AppPersistence.resetForTest();

      final secret = lang == 'en' ? enSecret : hiEnSecret;
      final hintWord = lang == 'en' ? enHintWord : hiEnHintWord;

      // The non-secret in-vocab word must differ from the secret.
      // If somehow they collide (shouldn't happen with hints), skip.
      assert(hintWord != secret,
          'hintWord "$hintWord" must not equal secret "$secret"');

      // Pass lang and dbPath through AppOverrides so:
      //   - lang: the shell uses hi-en even if SharedPreferences holds 'en'.
      //   - dbPath: persistence opens the per-test file, not the shared app DB.
      final overrides = AppOverrides(
        payloadClient: _BundleOnlyClient(),
        fixedDate: _testDate,
        skipOnboarding: true,
        lang: lang,
        dbPath: testDbPath,
      );

      // Persistence is now initialised by _AppShellState._init() using the
      // per-test dbPath from AppOverrides; no separate init() call needed.
      await tester.pumpWidget(MindmeldApp(overrides: overrides));

      // Allow the async app init + puzzle load to complete.
      await tester.pumpAndSettle(const Duration(seconds: 10));

      // ── Step 1: Verify puzzle screen is shown ──────────────────────────────
      expect(find.byType(TextField), findsOneWidget,
          reason: 'Puzzle screen guess input must be visible');
      expect(find.text('Guess'), findsOneWidget);

      // ── Step 2: Enter a known in-vocab non-secret word ─────────────────────
      await tester.enterText(find.byType(TextField), hintWord);
      await tester.tap(find.text('Guess'));
      await tester.pumpAndSettle(const Duration(seconds: 3));

      // The history should now contain the hint word — find it by text
      // somewhere in the list (GuessTile shows the word in a Text widget).
      expect(find.text(hintWord), findsWidgets,
          reason: 'Hint word "$hintWord" should appear in guess history');

      // A temperature band label should be visible for the guess.
      // All band labels are non-empty; check at least one known label appears.
      final bandLabels = TemperatureBand.values
          .where((b) => b != TemperatureBand.win)
          .map((b) => b.label)
          .toList();
      final anyBandVisible =
          bandLabels.any((label) => find.text(label).evaluate().isNotEmpty);
      expect(anyBandVisible, isTrue,
          reason: 'A temperature band label must appear after a valid guess');

      // ── Step 3: Enter a garbage non-vocab word ─────────────────────────────
      await tester.enterText(find.byType(TextField), _garbageWord);
      await tester.tap(find.text('Guess'));
      await tester.pumpAndSettle(const Duration(seconds: 2));

      expect(find.text('Not in word list'), findsOneWidget,
          reason: 'Garbage word must produce friendly rejection');

      // ── Step 4: Enter the secret to win ───────────────────────────────────
      await tester.enterText(find.byType(TextField), secret);
      await tester.tap(find.text('Guess'));

      // The win screen appears after a brief animation delay (~600 ms).
      await tester.pumpAndSettle(const Duration(seconds: 5));

      // Win screen shows the secret word in uppercase.
      expect(find.text(secret.toUpperCase()), findsOneWidget,
          reason: 'Win screen must reveal secret "$secret" in uppercase');

      // ── Step 5: Share card must not contain the secret ─────────────────────
      // The share card text widget is a SelectableText or Text whose content
      // starts with "Mindmeld #".  Find any text that contains "#1" or "#"
      // and does NOT contain the raw secret word.
      final shareCardFinder = find.textContaining('Mindmeld #');
      expect(shareCardFinder, findsWidgets,
          reason: 'Share card text must be visible on the win screen');

      // Extract the share card text and assert the secret is not in it.
      final shareWidgets = tester.widgetList<Text>(shareCardFinder).toList();
      for (final widget in shareWidgets) {
        final text = widget.data ?? '';
        expect(text.contains(secret), isFalse,
            reason:
                'Share card "$text" must not contain the secret "$secret"');
      }

      // Clean up: close DB, reset singleton, delete the per-test temp directory.
      await AppPersistence.instance.close();
      AppPersistence.resetForTest();
      await testDbDir.delete(recursive: true);
    });
  }
}
