/// Widget tests for the IAP/settings screen (acceptance criterion 3, part B):
/// "IAP screens render via stub."
///
/// These tests verify:
///   1. Puzzle Archive and Streak Freeze are NOT rendered as purchasable rows
///      — both shipped free/earned (ArchiveScreen's "Practice" tab;
///      AppPersistence.recordWin/rescueStreakOrReset) rather than as an IAP,
///      so neither may ever surface a "coming soon" purchase row. Remove Ads
///      is also NOT rendered, for a different reason: AppConfig.
///      iapEnabledEffective/adsEnabledEffective are hard-false on web (the
///      only shipped platform) — there is no ad to remove and no purchase
///      path to reach there, so the row would be dead UI. All three
///      IapProduct enum values are retained (harmless, unused by this
///      screen's UI) rather than ripped out, to avoid churning the
///      RevenueCat product-mapping/entitlements plumbing for products that
///      were never actually sold on this platform.
///   2. Themed Packs (phase 6c) is a navigation row into the pack selector —
///      not a purchase row — and is enabled/tappable regardless of
///      iapEnabledEffective, since it's a real, working feature (Bollywood
///      is free; other packs default-unlock when IAP is disabled — see
///      packUnlocked in core/packs.dart).
///   3. IapStub.isAvailable(themedPacks) stays false — it is no longer part
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
  // Purchasable/nav rows render (archive excluded — ships free)
  // -------------------------------------------------------------------------

  group('SettingsScreen IAP section', () {
    testWidgets(
      'Remove Ads is NOT rendered on web (ads/IAP hard-disabled there — dead '
      'UI otherwise, per AppConfig.iapEnabledEffective)',
      (tester) async {
        await tester.pumpWidget(_buildSettingsScreen());
        await tester.pump();

        expect(
          find.text(IapStub.productNames[IapProduct.removeAds]!),
          findsNothing,
        );
      },
    );

    testWidgets(
      'Puzzle Archive is NOT rendered as a purchasable IAP row (ships free)',
      (tester) async {
        await tester.pumpWidget(_buildSettingsScreen());
        await tester.pump();

        expect(
          find.text(IapStub.productNames[IapProduct.archive]!),
          findsNothing,
        );
      },
    );

    testWidgets(
      'Streak Freeze is NOT rendered as a purchasable IAP row (earned, not bought)',
      (tester) async {
        await tester.pumpWidget(_buildSettingsScreen());
        await tester.pump();

        expect(
          find.text(IapStub.productNames[IapProduct.streakFreeze]!),
          findsNothing,
        );
      },
    );

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

  // Note: no purchasable-product-tap coverage remains here — removeAds is
  // the only generic product left after archive/streakFreeze shipped free/
  // earned, and it's gated off entirely on web (see the "NOT rendered on
  // web" test above), so there is no purchasable row to tap in this test
  // environment. IapStub.purchase()'s coming-soon behavior itself is still
  // covered directly below (IapStub contract group).

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
