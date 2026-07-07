/// Widget tests for the IAP/settings screen (acceptance criterion 3, part B):
/// "IAP screens render via stub."
///
/// These tests verify:
///   1. All four IAP products are rendered in the settings screen.
///   2. Themed Packs is visually distinguished as "coming soon" / disabled.
///   3. Tapping a purchasable product surfaces the stub "coming soon" result
///      without crashing (snackbar appears).
///   4. Tapping the disabled Themed Packs product has no effect.
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
  // Themed Packs is greyed / disabled
  // -------------------------------------------------------------------------

  group('Themed Packs is marked as coming soon and disabled', () {
    testWidgets(
      'Themed Packs ListTile is disabled (enabled == false)',
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

        // The tile should be disabled (enabled: false in SettingsScreen).
        for (final tile in themedPacksTile) {
          expect(
            tile.enabled,
            isFalse,
            reason: 'Themed Packs must be disabled in Phase 1',
          );
        }
      },
    );

    testWidgets(
      'Themed Packs shows a "Soon" chip as its trailing widget',
      (tester) async {
        await tester.pumpWidget(_buildSettingsScreen());
        await tester.pump();

        // The settings screen renders a Chip(label: Text('Soon')) for
        // unavailable products.
        expect(find.widgetWithText(Chip, 'Soon'), findsOneWidget);
      },
    );

    testWidgets(
      'Themed Packs ListTile onTap is null (not tappable)',
      (tester) async {
        await tester.pumpWidget(_buildSettingsScreen());
        await tester.pump();

        // IapStub.isAvailable(themedPacks) == false → onTap set to null.
        expect(IapStub.isAvailable(IapProduct.themedPacks), isFalse);
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
