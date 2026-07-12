/// Regression coverage for the P1 navigation bug: winning (or losing) the
/// daily puzzle used to swap the ENTIRE tabbed Scaffold for a bare win/loss
/// screen (no NavigationBar), and — because PuzzleScreen unconditionally
/// re-fired onWin/onLoss whenever it found an already-finished state on
/// mount — tapping "Back" bounced the player straight back to the result
/// screen, making the bottom nav unreachable for the rest of the day.
///
/// The fix: the tabbed Scaffold (NavigationBar + IndexedStack) is now always
/// the home surface. Only the index-0 IndexedStack child swaps between the
/// win/loss shells and the live puzzle board (see main.dart `_AppShellState`
/// .build()), and PuzzleScreen's already-finished-state redirect is scoped to
/// pack mode only (see puzzle_screen.dart `_load()`); daily-mode restart
/// routing is owned exclusively by `_AppShellState._deriveResultRouting`.
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
import 'package:mindmeld/features/branding/heat_rings_mark.dart';
import 'package:mindmeld/features/puzzle/puzzle_screen.dart';
import 'package:mindmeld/features/stats/stats_screen.dart';
import 'package:mindmeld/main.dart';
import 'package:path/path.dart' as p;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

/// Builds a minimal single-word payload where "ocean" is the rank-1 secret.
///
/// Reuses the exact salt/secret pairing verified in payload_codec_test.dart
/// and pack_isolation_test.dart, so a guess of "ocean" always wins. When
/// [pack]/[idx] are non-null the payload is pack-shaped (phase 6c); otherwise
/// it's a plain daily payload.
DailyPayload _buildOceanPayload({String? pack, int? idx}) {
  const salt = '7ca5996a071e2723';
  final hash = PayloadCodec.hashWord('ocean', salt);
  final packFields = pack != null ? '"pack":"$pack","idx":$idx,' : '';
  final date =
      pack != null ? '$pack-${idx.toString().padLeft(3, '0')}' : '2099-01-01';
  final json = '''{
    "v":3,"lang":"en","date":"$date",
    "model":"test","n":1,"salt":"$salt",
    "words":{"$hash":[1,65535]},
    "hints":[[2,"sea"]],
    "s":"TbCpaqQ=",
    $packFields
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
/// payload fetch, the resulting setState calls) has drained. Mirrors the
/// `_settle`/`_pumpUntilLoaded` helpers in pack_isolation_test.dart and
/// flow_hardening_test.dart: sqflite_common_ffi does real OS-thread I/O that
/// plain `tester.pump()` cannot flush on its own.
Future<void> _settle(WidgetTester tester) async {
  await tester.runAsync(() async {
    await Future<void>.delayed(const Duration(milliseconds: 200));
  });
  await tester.pump();
}

/// Taps "Guess" and drives the win flow (including the 600ms win-flash
/// delay in PuzzleScreen._submitGuess) to completion. Copied from
/// pack_isolation_test.dart's `_tapGuessAndAwaitWin` — the winning path does
/// real sqflite I/O BEFORE scheduling the fake-timer delay, so runAsync and
/// pump(duration) must be interleaved.
Future<void> _tapGuessAndAwaitWin(WidgetTester tester) async {
  await tester.tap(find.text('Guess'));
  await tester.pump();
  await tester.runAsync(() async {
    await Future<void>.delayed(const Duration(milliseconds: 300));
  });
  await tester.pump(const Duration(milliseconds: 700)); // fires the win-flash timer
  await tester.runAsync(() async {
    await Future<void>.delayed(const Duration(milliseconds: 300));
  });
  await tester.pump();
}

/// Finds [text] rendered specifically inside an [AppBar] — used to
/// disambiguate a screen's title from an identically-labelled NavigationBar
/// destination (e.g. both the Settings tab's AppBar title and its nav label
/// read "Settings").
Finder _appBarTitle(String text) =>
    find.descendant(of: find.byType(AppBar), matching: find.text(text));

/// Finds the tappable NavigationBar destination labelled [label].
Finder _navDestination(String label) => find.descendant(
      of: find.byType(NavigationBar),
      matching: find.text(label),
    );

/// Asserts that StatsScreen's `label` stat box (e.g. "Played", "Streak")
/// currently renders `expectedValue`.
///
/// Reads via the nearest ancestor [Column] of the label [Text] — that
/// Column is `_StatBox`'s own layout (private widget, so not addressable by
/// type from a test file) containing exactly [value, label] as its two
/// children — rather than a brittle assumption about text-widget ordering.
void _expectStatValue(String label, String expectedValue) {
  final statBox =
      find.ancestor(of: find.text(label), matching: find.byType(Column)).first;
  expect(find.descendant(of: statBox, matching: find.text(expectedValue)), findsOneWidget,
      reason: 'Stat "$label" must show "$expectedValue"');
}

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
    tmpDir = await Directory.systemTemp.createTemp('mindmeld_win_nav_');
    dbPath = p.join(tmpDir.path, 'test.db');
    await AppPersistence.instance.init(dbPath: dbPath);
  });

  tearDown(() async {
    await AppPersistence.instance.close();
    AppPersistence.resetForTest();
    await tmpDir.delete(recursive: true);
  });

  // ===========================================================================
  // (a) Nav reachable after daily win
  // ===========================================================================

  testWidgets(
    'nav reachable after daily win: win screen and NavigationBar both render; '
    'every other tab is reachable',
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
      // Seeding via a bare `await` (outside tester.runAsync) never completes:
      // testWidgets bodies run inside FakeAsync, and sqflite_common_ffi's real
      // OS-thread I/O only resolves when explicitly drained through runAsync.
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
          reason: 'restarting on an already-won day must route straight to the win screen');
      expect(find.byType(NavigationBar), findsOneWidget,
          reason: 'the bottom nav must stay mounted even when the puzzle tab shows the win screen');

      // Each other destination renders its own distinguishing AppBar title
      // while the puzzle tab is still showing the win screen underneath.
      const tabTitles = {
        'Practice': 'Practice',
        'Stats': 'Statistics',
        'Settings': 'Settings',
        'Friends': 'Play with friends',
      };
      for (final entry in tabTitles.entries) {
        await tester.tap(_navDestination(entry.key));
        await _settle(tester);
        expect(_appBarTitle(entry.value), findsOneWidget,
            reason: '${entry.key} tab must be reachable while the puzzle tab shows the win screen');
      }

      // Tap back to the Puzzle tab — the win screen is still there (still won).
      await tester.tap(_navDestination('Puzzle'));
      await _settle(tester);
      expect(_appBarTitle('You got it!'), findsOneWidget,
          reason: 'returning to the Puzzle tab must show the win screen again');
    },
  );

  // ===========================================================================
  // (b) Back is not a dead end
  // ===========================================================================

  testWidgets(
    'Back on the win screen shows the finished board with nav still present, '
    'and the win screen does not reappear',
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
      // Seeding via a bare `await` (outside tester.runAsync) never completes:
      // testWidgets bodies run inside FakeAsync, and sqflite_common_ffi's real
      // OS-thread I/O only resolves when explicitly drained through runAsync.
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
          reason: 'sanity: win screen must be showing before tapping Back');

      // The Back button sits below the fold in WinScreen's scrollable body at
      // the default 800x600 test viewport size — scroll it into view first so
      // the tap actually hits it instead of landing outside the render tree.
      final backButton = find.widgetWithText(TextButton, 'Back');
      await tester.ensureVisible(backButton);
      await _settle(tester);
      await tester.tap(backButton);
      await _settle(tester);
      await _settle(tester);

      expect(_appBarTitle('You got it!'), findsNothing,
          reason: 'Back must dismiss the win screen');
      expect(find.byType(NavigationBar), findsOneWidget,
          reason: 'nav bar must remain mounted after Back');
      expect(find.text('Enter a word…'), findsNothing,
          reason: 'the daily puzzle is already won, so no active guess input is shown');
      expect(
        find.descendant(
            of: find.byType(AppBar), matching: find.byType(WarmerWordmark)),
        findsOneWidget,
        reason: 'the locked (finished) daily puzzle board renders under the Puzzle tab',
      );

      // The core regression: further settling must NOT bounce back to WinScreen.
      await _settle(tester);
      await _settle(tester);
      expect(_appBarTitle('You got it!'), findsNothing,
          reason: 'Back must not be a dead end — the win screen must not re-fire on remount');
    },
  );

  // ===========================================================================
  // (b2) "View result" re-enters the win/loss screen after Back
  // ===========================================================================

  testWidgets(
    'the finished board shows a "View result" affordance that re-shows the win screen',
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

      final backButton = find.widgetWithText(TextButton, 'Back');
      await tester.ensureVisible(backButton);
      await _settle(tester);
      await tester.tap(backButton);
      await _settle(tester);
      await _settle(tester);

      expect(_appBarTitle('You got it!'), findsNothing,
          reason: 'sanity: Back must dismiss the win screen first');
      final viewResult = find.widgetWithText(OutlinedButton, 'View result');
      expect(viewResult, findsOneWidget,
          reason: 'the finished board must offer a way back to the win/share screen — '
              'previously there was no way back without restarting the app');

      await tester.ensureVisible(viewResult);
      await _settle(tester);
      await tester.tap(viewResult);
      await _settle(tester);
      await _settle(tester);

      expect(_appBarTitle('You got it!'), findsOneWidget,
          reason: 'tapping "View result" must re-show the win screen');
    },
  );

  testWidgets(
    'the finished board shows a "View result" affordance that re-shows the loss screen',
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

      final backButton = find.widgetWithText(TextButton, 'Back');
      await tester.ensureVisible(backButton);
      await _settle(tester);
      await tester.tap(backButton);
      await _settle(tester);
      await _settle(tester);

      expect(_appBarTitle('Better luck next time 🌙'), findsNothing,
          reason: 'sanity: Back must dismiss the loss screen first');
      final viewResult = find.widgetWithText(OutlinedButton, 'View result');
      expect(viewResult, findsOneWidget,
          reason: 'the finished board must offer a way back to the loss/share screen');

      await tester.ensureVisible(viewResult);
      await _settle(tester);
      await tester.tap(viewResult);
      await _settle(tester);
      await _settle(tester);

      expect(_appBarTitle('Better luck next time 🌙'), findsOneWidget,
          reason: 'tapping "View result" must re-show the loss screen');
    },
  );

  // ===========================================================================
  // (c) onWin fires exactly once per completion
  // ===========================================================================

  group('onWin idempotency', () {
    testWidgets(
      '(i) mounting in daily mode with an already-won state does not call onWin',
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
        // Seeding via a bare `await` (outside tester.runAsync) never completes:
        // testWidgets bodies run inside FakeAsync, and sqflite_common_ffi's real
        // OS-thread I/O only resolves when explicitly drained through runAsync.
        await tester.runAsync(() => AppPersistence.instance.saveDayState(wonState));

        var onWinCalls = 0;
        await tester.pumpWidget(MaterialApp(
          home: PuzzleScreen(
            lang: 'en',
            date: date,
            onWin: () => onWinCalls++,
            onLoss: () {},
            payloadClient: _FixedClient(payload),
          ),
        ));
        await _settle(tester);
        await _settle(tester);

        expect(onWinCalls, equals(0),
            reason: 'daily mode must not redirect on an already-recorded win — '
                'the app shell owns that routing');
      },
    );

    testWidgets(
      '(ii) an active win calls onWin exactly once; remounting the finished '
      'state does not call it again',
      (tester) async {
        const date = '2099-01-01';
        final payload = _buildOceanPayload();
        var onWinCalls = 0;

        await tester.pumpWidget(MaterialApp(
          home: PuzzleScreen(
            key: const ValueKey('puz'),
            lang: 'en',
            date: date,
            onWin: () => onWinCalls++,
            onLoss: () {},
            payloadClient: _FixedClient(payload),
          ),
        ));
        await _settle(tester);

        await tester.enterText(find.byType(TextField), 'ocean');
        await _tapGuessAndAwaitWin(tester);

        expect(onWinCalls, equals(1), reason: 'an active win must call onWin exactly once');

        // Remount: a fresh PuzzleScreen instance for the same date/lang, which
        // now loads the just-recorded won state from persistence.
        await tester.pumpWidget(MaterialApp(
          home: PuzzleScreen(
            key: const ValueKey('puz-remount'),
            lang: 'en',
            date: date,
            onWin: () => onWinCalls++,
            onLoss: () {},
            payloadClient: _FixedClient(payload),
          ),
        ));
        await _settle(tester);
        await _settle(tester);

        expect(onWinCalls, equals(1),
            reason: 'remounting after the win must not call onWin again — '
                'this is the exact bounce bug being fixed');
      },
    );

    testWidgets(
      '(iii) pack mode still redirects onWin when mounting with an '
      'already-won pack state',
      (tester) async {
        final packPayload = _buildOceanPayload(pack: 'bollywood', idx: 1);
        final packState = PackPuzzleState(
          packId: 'bollywood',
          idx: 1,
          lang: 'en',
          guesses: [
            Guess(word: 'ocean', rank: 1, similarity: 1.0, band: TemperatureBand.win),
          ],
          hintsUsed: 0,
          won: true,
          gaveUp: false,
        );
        // See the runAsync note above _settle's callers — seeding must be
        // drained through tester.runAsync, not a bare await.
        await tester.runAsync(() => AppPersistence.instance.savePackState(packState));

        var onWinCalls = 0;
        await tester.pumpWidget(MaterialApp(
          home: PuzzleScreen(
            lang: 'en',
            date: 'bollywood-001',
            packId: 'bollywood',
            packIdx: 1,
            packTitle: 'Bollywood',
            onWin: () => onWinCalls++,
            onLoss: () {},
            payloadClient: _FixedClient(packPayload),
          ),
        ));
        await _settle(tester);
        await _settle(tester);

        expect(onWinCalls, equals(1),
            reason: 'pack mode must still redirect on an already-recorded win — '
                'this preserves the existing pack-list flow, which has no remount loop');
      },
    );
  });

  // ===========================================================================
  // (d) Loss-path smoke
  // ===========================================================================

  testWidgets(
    'daily loss on restart renders LossScreen inside the shell with nav present',
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
      // Seeding via a bare `await` (outside tester.runAsync) never completes:
      // testWidgets bodies run inside FakeAsync, and sqflite_common_ffi's real
      // OS-thread I/O only resolves when explicitly drained through runAsync.
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
          reason: 'restarting on an already-lost day must route to the loss screen');
      expect(find.byType(NavigationBar), findsOneWidget,
          reason: 'the bottom nav must stay mounted for the loss shell too');
    },
  );

  // ===========================================================================
  // (e) Stats tab reflects a same-session win (follow-up to the P1 fix:
  // StatsScreen is mounted eagerly at boot in the IndexedStack and only ever
  // loaded once in initState, so it kept showing boot-time Played 0/Streak 0
  // even after a win became reachable via the Stats tab post-fix).
  // ===========================================================================

  testWidgets(
    'Stats tab reflects a same-session daily win immediately, not stale boot-time numbers',
    (tester) async {
      const date = '2099-01-01';
      final payload = _buildOceanPayload();

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

      // Play an ACTIVE win through the puzzle tab (not a pre-seeded state) —
      // this is the exact live repro: win, then switch tabs within the
      // session, with no app restart in between.
      await tester.enterText(find.byType(TextField), 'ocean');
      await _tapGuessAndAwaitWin(tester);

      expect(_appBarTitle('You got it!'), findsOneWidget,
          reason: 'sanity: the active win must route to the win screen');

      await tester.tap(_navDestination('Stats'));
      await _settle(tester);
      await _settle(tester);

      _expectStatValue('Played', '1');
      _expectStatValue('Streak', '1');
    },
  );

  group('StatsScreen activation reload', () {
    testWidgets(
      'reloads when active flips false→true after stats changed while inactive',
      (tester) async {
        await tester.pumpWidget(const MaterialApp(
          home: StatsScreen(lang: 'en', active: false),
        ));
        await _settle(tester);

        _expectStatValue('Played', '0');
        _expectStatValue('Streak', '0');

        // Persist a win directly — simulates stats changing elsewhere (e.g.
        // the puzzle tab) while this StatsScreen instance stays mounted but
        // inactive in the IndexedStack.
        await tester.runAsync(() => AppPersistence.instance.recordWin(
              lang: 'en',
              guessCount: 3,
              today: DateTime.now(),
            ));

        // Flip active: false → true — must reload and show the new numbers,
        // not the stale ones captured at initState.
        await tester.pumpWidget(const MaterialApp(
          home: StatsScreen(lang: 'en', active: true),
        ));
        await _settle(tester);
        await _settle(tester);

        _expectStatValue('Played', '1');
        _expectStatValue('Streak', '1');
      },
    );
  });
}
