/// Screenshot-capture integration test for Play Store visual assets.
///
/// Produces 8 PNGs in docs/store-assets/ via the onScreenshot driver callback.
/// Run via:
///   flutter drive \
///     --driver=test_driver/integration_test.dart \
///     --target=integration_test/screenshots_test.dart \
///     -d emulator-5554
///
/// The AVD must be booted (headless) before invoking flutter drive.
/// Each screenshot name maps to a file: `docs/store-assets/&lt;name&gt;.png`
///
/// ## State reached per screenshot
///
/// 01-onboarding      : First onboarding page (skipOnboarding=false)
/// 02-midgame-en      : EN puzzle with 6 varied guesses spanning Hot & Warm bands
/// 03-hint-tile       : Same EN session after one hint reveal (HintTile visible)
/// 04-win-en          : EN win screen after guessing "ocean"
/// 05-stats           : Stats screen with streak from EN win
/// 06-settings        : Settings screen showing EN/Hinglish toggle
/// 07-midgame-hien    : HI-EN puzzle mid-game with 5 guesses spanning bands
/// 08-win-hien        : HI-EN win screen after guessing "samunder"
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:mindmeld/ads/rewarded_ad_service.dart';
import 'package:mindmeld/core/payload_client.dart';
import 'package:mindmeld/core/payload_codec.dart';
import 'package:mindmeld/core/persistence.dart';
import 'package:mindmeld/main.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const String _kDate = '2026-06-12';

/// EN puzzle words across rank bands (from bundled payload, pre-decoded).
///
/// Band thresholds for EN n=55000:
///   scorching: rank ≤ 55
///   hot:       rank ≤ 550
///   warm:      rank ≤ 2750
///   cold:      rank ≤ 13750
///   freezing:  rank > 13750
///
/// These words come from the bundled payload hints — guaranteed in-vocab.
/// Ordered so the list shows a mix of Hot & Warm bands for visual variety.
const List<String> _kEnMidgameWords = [
  'marshes',    // rank 500  — Hot
  'typhoons',   // rank 300  — Hot
  'lakeshore',  // rank 200  — Hot
  'herrings',   // rank 750  — Warm
  'jamaica',    // rank 1000 — Warm
  'stillwater', // rank 100  — Hot
];

/// HI-EN puzzle words for screenshot 07 (5 guesses spanning bands).
///
/// Band thresholds for HI-EN n=10439:
///   scorching: rank ≤ 50
///   hot:       rank ≤ 500
///   cold:      rank ≤ 2609
///   freezing:  rank > 2609
const List<String> _kHiEnMidgameWords = [
  'usd',      // rank 1000 — Cold
  'saans',    // rank 750  — Cold
  'chaar',    // rank 500  — Hot
  'mez',      // rank 100  — Hot
  'namkeen',  // rank 50   — Scorching
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// [PayloadClient] that always serves the bundled asset (no network).
class _BundleClient extends PayloadClient {
  _BundleClient() : super(assetBundle: rootBundle);

  @override
  Future<PayloadResult> fetch(String lang, String date) =>
      loadBundled(lang, date);
}

/// Instant-grant hint gate: no ad dialog, zero delay.
///
/// Used in screenshots so hint reveals happen synchronously without requiring
/// the tester to pump through a simulated-ad timer.
class _InstantHintGate implements HintGate {
  const _InstantHintGate();

  @override
  Future<HintGateResult> requestHint(BuildContext context) async =>
      const HintGateResult(granted: true, fallback: true);
}

/// Initialise sqflite for the platform (no-op on Android).
void _initSqflite() {
  if (!Platform.isAndroid && !Platform.isIOS) {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  }
}

/// Create a temporary directory + isolated DB path for one test session.
Future<(Directory, String)> _tempDb() async {
  final dir = await Directory.systemTemp.createTemp('mindmeld_ss_');
  return (dir, p.join(dir.path, 'test.db'));
}

/// Decode the secret for [lang] / [_kDate] from bundled assets.
Future<String> _decodeSecret(String lang) async {
  final client = _BundleClient();
  final result = await client.fetch(lang, _kDate);
  return PayloadCodec.decodeSecret(result.payload);
}

/// Wait for the puzzle screen to fully load (spinner gone, TextField visible).
Future<void> _awaitPuzzleReady(WidgetTester tester) async {
  await tester.pumpAndSettle(const Duration(seconds: 10));
}

/// Enter a word in the guess field and submit; settle afterward.
Future<void> _guess(WidgetTester tester, String word) async {
  await tester.enterText(find.byType(TextField), word);
  await tester.tap(find.text('Guess'));
  await tester.pumpAndSettle(const Duration(seconds: 3));
}

/// Tear down the current app widget and reset persistence singleton.
Future<void> _teardownSession(WidgetTester tester, Directory dir) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pumpAndSettle();
  await AppPersistence.instance.close();
  AppPersistence.resetForTest();
  await dir.delete(recursive: true);
}

// ---------------------------------------------------------------------------
// Test body
// ---------------------------------------------------------------------------

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  setUpAll(_initSqflite);

  // ──────────────────────────────────────────────────────────────────────────
  // Screenshot 01: Onboarding (separate session, skipOnboarding=false)
  // ──────────────────────────────────────────────────────────────────────────
  testWidgets('screenshot-01: onboarding first page', (tester) async {
    await binding.convertFlutterSurfaceToImage();

    final (dir, dbPath) = await _tempDb();
    AppPersistence.resetForTest();

    await tester.pumpWidget(
      MindmeldApp(
        overrides: AppOverrides(
          payloadClient: _BundleClient(),
          fixedDate: _kDate,
          skipOnboarding: false,
          lang: 'en',
          dbPath: dbPath,
        ),
      ),
    );
    // Allow the async init + SharedPreferences to settle.
    await tester.pumpAndSettle(const Duration(seconds: 5));

    await binding.takeScreenshot('screenshot-01-onboarding');

    await _teardownSession(tester, dir);
  });

  // ──────────────────────────────────────────────────────────────────────────
  // Screenshots 02–04: EN game flow (mid-game → hint → win)
  // ──────────────────────────────────────────────────────────────────────────
  testWidgets('screenshots 02–04: EN mid-game, hint, win', (tester) async {
    await binding.convertFlutterSurfaceToImage();

    final (dir, dbPath) = await _tempDb();
    AppPersistence.resetForTest();

    await tester.pumpWidget(
      MindmeldApp(
        overrides: AppOverrides(
          payloadClient: _BundleClient(),
          fixedDate: _kDate,
          skipOnboarding: true,
          lang: 'en',
          dbPath: dbPath,
          hintGate: const _InstantHintGate(),
        ),
      ),
    );
    await _awaitPuzzleReady(tester);

    // Make 6 mid-game guesses spanning Hot & Warm bands.
    for (final word in _kEnMidgameWords) {
      await _guess(tester, word);
    }

    // Screenshot 02: EN mid-game with multi-band guess history.
    await binding.takeScreenshot('screenshot-02-midgame-en');

    // Tap the Hint button (instant gate → no dialog).
    await tester.tap(find.textContaining('Hint'));
    await tester.pumpAndSettle(const Duration(seconds: 2));

    // Screenshot 03: EN game after one hint tile is pinned.
    await binding.takeScreenshot('screenshot-03-hint-tile');

    // Guess the EN secret to trigger win flow.
    final enSecret = await _decodeSecret('en');
    assert(enSecret == 'ocean', 'EN secret mismatch: $enSecret');
    await _guess(tester, enSecret);
    // Win animation: ~600 ms delay then shell routes to WinScreen.
    await tester.pumpAndSettle(const Duration(seconds: 3));

    // Screenshot 04: EN win screen (trophy + OCEAN + share card).
    await binding.takeScreenshot('screenshot-04-win-en');

    await _teardownSession(tester, dir);
  });

  // ──────────────────────────────────────────────────────────────────────────
  // Screenshots 05–06: Stats & Settings
  //
  // Strategy: pre-seed a fresh DB with one win (streak=1) by opening
  // AppPersistence directly, close it properly, then boot the app with
  // fixedDate=2026-06-13 (no won state for that date) so the main shell
  // with NavigationBar is visible — then tap Stats and Settings.
  // ──────────────────────────────────────────────────────────────────────────
  testWidgets('screenshots 05–06: stats screen and settings screen',
      (tester) async {
    await binding.convertFlutterSurfaceToImage();

    final (dir, dbPath) = await _tempDb();

    // Pre-seed: open the DB, record one EN win on 2026-06-12, close it.
    // We close explicitly so the file lock is released before the app opens
    // a second connection to the same path.
    AppPersistence.resetForTest();
    await AppPersistence.instance.init(dbPath: dbPath);
    await AppPersistence.instance.recordWin(
      lang: 'en',
      guessCount: 7,
      today: DateTime(2026, 6, 12),
    );
    await AppPersistence.instance.close();
    AppPersistence.resetForTest();

    // Boot the app with fixedDate=2026-06-13 → no won state for "today",
    // so the main shell with the NavigationBar is the active widget.
    // Stats screen will show streak=1 from the seeded 2026-06-12 win.
    await tester.pumpWidget(
      MindmeldApp(
        overrides: AppOverrides(
          payloadClient: _BundleClient(),
          fixedDate: '2026-06-13',
          skipOnboarding: true,
          lang: 'en',
          dbPath: dbPath,
          hintGate: const _InstantHintGate(),
        ),
      ),
    );
    await _awaitPuzzleReady(tester);

    // Navigate to Stats tab (index 1 in NavigationBar).
    await tester.tap(find.byIcon(Icons.bar_chart));
    await tester.pumpAndSettle(const Duration(seconds: 3));

    // Screenshot 05: Stats screen with streak=1 from the seeded win.
    await binding.takeScreenshot('screenshot-05-stats');

    // Navigate to Settings tab (index 2).
    await tester.tap(find.byIcon(Icons.settings));
    await tester.pumpAndSettle(const Duration(seconds: 2));

    // Screenshot 06: Settings screen with English/Hinglish language toggle.
    await binding.takeScreenshot('screenshot-06-settings');

    await _teardownSession(tester, dir);
  });

  // ──────────────────────────────────────────────────────────────────────────
  // Screenshots 07–08: HI-EN game flow (mid-game → win)
  // ──────────────────────────────────────────────────────────────────────────
  testWidgets('screenshots 07–08: HI-EN mid-game and win', (tester) async {
    await binding.convertFlutterSurfaceToImage();

    final (dir, dbPath) = await _tempDb();
    AppPersistence.resetForTest();

    await tester.pumpWidget(
      MindmeldApp(
        overrides: AppOverrides(
          payloadClient: _BundleClient(),
          fixedDate: _kDate,
          skipOnboarding: true,
          lang: 'hi-en',
          dbPath: dbPath,
          hintGate: const _InstantHintGate(),
        ),
      ),
    );
    await _awaitPuzzleReady(tester);

    // Make 5 mid-game guesses spanning Scorching / Hot / Cold bands.
    for (final word in _kHiEnMidgameWords) {
      await _guess(tester, word);
    }

    // Screenshot 07: HI-EN mid-game with multi-band guess list.
    await binding.takeScreenshot('screenshot-07-midgame-hien');

    // Guess the HI-EN secret.
    final hiSecret = await _decodeSecret('hi-en');
    assert(hiSecret == 'samunder', 'HI-EN secret mismatch: $hiSecret');
    await _guess(tester, hiSecret);
    await tester.pumpAndSettle(const Duration(seconds: 3));

    // Screenshot 08: HI-EN win screen (trophy + SAMUNDER + share card).
    await binding.takeScreenshot('screenshot-08-win-hien');

    await _teardownSession(tester, dir);
  });
}
