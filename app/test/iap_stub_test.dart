/// Widget tests for the IAP/settings screen (acceptance criterion 3, part B):
/// "IAP screens render via stub."
///
/// These tests verify:
///   1. All four IAP products are rendered in the settings screen.
///   2. Themed Packs (phase 6c) is a navigation row into the pack selector —
///      not a purchase row — and is enabled/tappable.
///   3. Tapping a purchasable product surfaces the stub "coming soon" result
///      without crashing (snackbar appears).
///   4. IapStub.isAvailable(themedPacks) stays false — it is no longer part
///      of the generic purchase() flow (packs use IapGateway.purchasePack).
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/features/settings/settings_screen.dart';
import 'package:mindmeld/notifications/notification_service.dart';
import 'package:mindmeld/social/social_service.dart';
import 'package:mindmeld/stubs/iap_stub.dart';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Wraps [SettingsScreen] in a [MaterialApp] with a [ScaffoldMessenger] so
/// snackbars triggered by IAP taps have a valid overlay context.
///
/// [SettingsScreen]'s Notifications section (6b) calls
/// [NotificationService.currentPermission] from initState, which now ensures
/// Firebase is ready first (see notification_service_test.dart's "Firebase
/// readiness gate" regression tests). Without a `firebaseInitializer`
/// override here, that would attempt a REAL `Firebase.initializeApp()` on
/// the test VM and hang until its 20s timeout, leaving a dangling Timer the
/// test framework flags as a leak. `firebaseInitializer: () async => false`
/// short-circuits before either the real Firebase or FCM client is ever
/// touched — this test suite doesn't exercise notifications at all.
Widget _buildSettingsScreen({
  String currentLang = 'en',
}) {
  return MaterialApp(
    home: SettingsScreen(
      currentLang: currentLang,
      onLangChanged: (_) {},
      onReplayOnboarding: () {},
      notificationService: NotificationService(
        socialService: SocialService(firebaseInitializer: () async => false),
      ),
    ),
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  // -------------------------------------------------------------------------
  // All four products render
  // -------------------------------------------------------------------------

  group('SettingsScreen IAP section — all four products render', () {
    testWidgets('Remove Ads product is visible', (tester) async {
      await tester.pumpWidget(_buildSettingsScreen());
      await tester.pump();

      expect(
        find.text(IapStub.productNames[IapProduct.removeAds]!),
        findsOneWidget,
      );
    });

    testWidgets('Puzzle Archive product is visible', (tester) async {
      await tester.pumpWidget(_buildSettingsScreen());
      await tester.pump();

      expect(
        find.text(IapStub.productNames[IapProduct.archive]!),
        findsOneWidget,
      );
    });

    testWidgets('Streak Freeze product is visible', (tester) async {
      await tester.pumpWidget(_buildSettingsScreen());
      await tester.pump();

      expect(
        find.text(IapStub.productNames[IapProduct.streakFreeze]!),
        findsOneWidget,
      );
    });

    testWidgets('Themed Packs product is visible', (tester) async {
      await tester.pumpWidget(_buildSettingsScreen());
      await tester.pump();

      expect(
        find.text(IapStub.productNames[IapProduct.themedPacks]!),
        findsOneWidget,
      );
    });
  });

  // -------------------------------------------------------------------------
  // Themed Packs is a navigation row (phase 6c)
  // -------------------------------------------------------------------------

  group('Themed Packs is a navigation row into the pack selector', () {
    testWidgets(
      'Themed Packs ListTile is enabled (enabled == true)',
      (tester) async {
        await tester.pumpWidget(_buildSettingsScreen());
        await tester.pump();

        // Find all ListTiles that contain the Themed Packs label.
        final themedPacksTile = tester.widgetList<ListTile>(
          find.ancestor(
            of: find.text(IapStub.productNames[IapProduct.themedPacks]!),
            matching: find.byType(ListTile),
          ),
        );

        expect(
          themedPacksTile,
          isNotEmpty,
          reason: 'Themed Packs ListTile must exist',
        );

        // The tile is now a navigation row (opens PackSelectorScreen), so it
        // must be enabled/tappable rather than disabled.
        for (final tile in themedPacksTile) {
          expect(
            tile.enabled,
            isTrue,
            reason: 'Themed Packs is a navigation row, not a purchase row',
          );
        }
      },
    );

    testWidgets(
      'Themed Packs no longer shows a "Soon" chip',
      (tester) async {
        await tester.pumpWidget(_buildSettingsScreen());
        await tester.pump();

        // No product row shows a "Soon" chip any more — Themed Packs was the
        // only product with isAvailable==false, and it's now a nav row.
        expect(find.widgetWithText(Chip, 'Soon'), findsNothing);
      },
    );

    testWidgets(
      'tapping Themed Packs navigates away from Settings',
      (tester) async {
        await tester.pumpWidget(_buildSettingsScreen());
        await tester.pump();

        await tester.tap(
          find.text(IapStub.productNames[IapProduct.themedPacks]!),
        );
        await tester.pump();
        await tester.pump(); // let the pushed route's first frame build

        // Settings' own "Themed Packs" row text is still mounted underneath
        // (Navigator keeps prior routes in the tree), so a successful push
        // means the label now appears TWICE: once in the Settings row, once
        // as PackSelectorScreen's AppBar title. This is timing-independent —
        // no need to wait on (or mock) the real manifest fetch.
        expect(find.text(IapStub.productNames[IapProduct.themedPacks]!),
            findsNWidgets(2),
            reason: 'Navigating to PackSelectorScreen adds its own AppBar title');
      },
    );
  });

  // -------------------------------------------------------------------------
  // Purchasable products show stub snackbar on tap
  // -------------------------------------------------------------------------

  group('Tapping a purchasable product shows the stub result without crashing',
      () {
    testWidgets(
      'tapping Remove Ads shows coming-soon snackbar',
      (tester) async {
        await tester.pumpWidget(_buildSettingsScreen());
        await tester.pump();

        await tester.tap(
          find.text(IapStub.productNames[IapProduct.removeAds]!),
        );

        // The IapStub.purchase() is async; let it resolve.
        await tester.pumpAndSettle();

        expect(
          find.text(
            'Coming soon! In-app purchases will be available in the next update.',
          ),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'tapping Puzzle Archive shows coming-soon snackbar',
      (tester) async {
        await tester.pumpWidget(_buildSettingsScreen());
        await tester.pump();

        await tester.tap(
          find.text(IapStub.productNames[IapProduct.archive]!),
        );
        await tester.pumpAndSettle();

        expect(
          find.text(
            'Coming soon! In-app purchases will be available in the next update.',
          ),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'tapping Streak Freeze shows coming-soon snackbar',
      (tester) async {
        await tester.pumpWidget(_buildSettingsScreen());
        await tester.pump();

        await tester.tap(
          find.text(IapStub.productNames[IapProduct.streakFreeze]!),
        );
        await tester.pumpAndSettle();

        expect(
          find.text(
            'Coming soon! In-app purchases will be available in the next update.',
          ),
          findsOneWidget,
        );
      },
    );
  });

  // -------------------------------------------------------------------------
  // IapStub contract
  // -------------------------------------------------------------------------

  group('IapStub contract', () {
    test('all four products are in IapProduct.values', () {
      expect(IapProduct.values.length, equals(4));
      expect(IapProduct.values, contains(IapProduct.removeAds));
      expect(IapProduct.values, contains(IapProduct.archive));
      expect(IapProduct.values, contains(IapProduct.streakFreeze));
      expect(IapProduct.values, contains(IapProduct.themedPacks));
    });

    test('productNames map covers all four products', () {
      for (final product in IapProduct.values) {
        expect(
          IapStub.productNames.containsKey(product),
          isTrue,
          reason: '${product.name} must have a display name',
        );
        expect(
          IapStub.productNames[product]!.isNotEmpty,
          isTrue,
        );
      }
    });

    test('only themedPacks is unavailable', () {
      expect(IapStub.isAvailable(IapProduct.removeAds), isTrue);
      expect(IapStub.isAvailable(IapProduct.archive), isTrue);
      expect(IapStub.isAvailable(IapProduct.streakFreeze), isTrue);
      expect(IapStub.isAvailable(IapProduct.themedPacks), isFalse);
    });

    test('purchase() returns a coming-soon PurchaseResult without throwing',
        () async {
      final stub = const IapStub();
      for (final product in IapProduct.values) {
        final result = await stub.purchase(product);
        expect(result.success, isFalse);
        expect(result.message, isNotEmpty);
        expect(result.message, contains('soon'));
      }
    });

    test('restorePurchases() completes without error', () async {
      await expectLater(
        const IapStub().restorePurchases(),
        completes,
      );
    });
  });
}
