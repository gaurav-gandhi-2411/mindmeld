/// Widget tests for the privacy-related tiles added to [SettingsScreen].
///
/// Acceptance criteria:
///   1. With all monetisation flags off (default test build):
///      - "Privacy options" tile is NOT rendered (adsEnabled=false).
///      - "Privacy policy" tile IS rendered.
///      - Tapping "Privacy policy" opens a dialog that contains the policy URL
///        as [SelectableText].
///   2. Unit contract for [ConsentManager.isPrivacyOptionsRequired]:
///      returns false immediately when adsEnabled=false (covered in
///      consent_manager_test.dart; cross-referenced here for traceability).
///
/// These tests use the default test build flags (no --dart-define), so
/// [AppConfig.adsEnabled] is always false and no UMP platform channel is
/// touched.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/core/config.dart';
import 'package:mindmeld/features/settings/settings_screen.dart';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Wraps [SettingsScreen] in a [MaterialApp] so dialogs have a valid overlay.
Widget _buildSettings() {
  return MaterialApp(
    home: SettingsScreen(
      currentLang: 'en',
      onLangChanged: (_) {},
      onReplayOnboarding: () {},
    ),
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  // Sanity-check: adsEnabled must be off so these tests are valid.
  // Mirrors the guard in consent_manager_test.dart.
  test('AppConfig.adsEnabled is false — privacy tiles test pre-condition', () {
    expect(AppConfig.adsEnabled, isFalse,
        reason: 'All privacy tile tests assume adsEnabled=false. '
            'Do not run with --dart-define=ADS_ENABLED=true.');
  });

  // -------------------------------------------------------------------------
  // "Privacy options" must NOT render when adsEnabled=false
  // -------------------------------------------------------------------------

  group('"Privacy options" tile — hidden when adsEnabled=false', () {
    testWidgets(
      'no "Privacy options" ListTile is present in the widget tree',
      (tester) async {
        await tester.pumpWidget(_buildSettings());
        // Allow initState async calls (isPrivacyOptionsRequired returns false
        // synchronously but still goes through microtask queue).
        await tester.pump();

        expect(
          find.text('Privacy options'),
          findsNothing,
          reason: '"Privacy options" must not render when adsEnabled=false',
        );
      },
    );
  });

  // -------------------------------------------------------------------------
  // "Privacy policy" must ALWAYS render
  // -------------------------------------------------------------------------

  group('"Privacy policy" tile — always visible', () {
    testWidgets(
      '"Privacy policy" ListTile is present regardless of adsEnabled',
      (tester) async {
        await tester.pumpWidget(_buildSettings());
        await tester.pump();

        expect(
          find.text('Privacy policy'),
          findsOneWidget,
          reason: '"Privacy policy" tile must always be visible',
        );
      },
    );

    testWidgets(
      'tapping "Privacy policy" opens an AlertDialog',
      (tester) async {
        await tester.pumpWidget(_buildSettings());
        await tester.pump();

        // Scroll the tile into view before tapping — the list is taller than
        // the 800x600 test viewport, so the privacy tiles may be off-screen.
        // ensureVisible scrolls until the widget is fully within the viewport.
        await tester.ensureVisible(find.text('Privacy policy'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Privacy policy'));
        await tester.pumpAndSettle();

        // The dialog must appear.
        expect(find.byType(AlertDialog), findsOneWidget);
      },
    );

    testWidgets(
      'privacy policy dialog contains the correct URL as SelectableText',
      (tester) async {
        await tester.pumpWidget(_buildSettings());
        await tester.pump();

        await tester.ensureVisible(find.text('Privacy policy'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Privacy policy'));
        await tester.pumpAndSettle();

        // The URL must be displayed inside a SelectableText widget.
        expect(
          find.widgetWithText(
            SelectableText,
            'https://gaurav-gandhi-2411.github.io/mindmeld-payloads/privacy.html',
          ),
          findsOneWidget,
          reason: 'Dialog must contain the privacy policy URL',
        );
      },
    );

    testWidgets(
      'privacy policy dialog can be dismissed via Close button',
      (tester) async {
        await tester.pumpWidget(_buildSettings());
        await tester.pump();

        await tester.ensureVisible(find.text('Privacy policy'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Privacy policy'));
        await tester.pumpAndSettle();

        // Dismiss the dialog.
        await tester.tap(find.text('Close'));
        await tester.pumpAndSettle();

        // Dialog must be gone.
        expect(find.byType(AlertDialog), findsNothing);
      },
    );
  });
}
