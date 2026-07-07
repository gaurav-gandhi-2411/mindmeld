/// Unit tests for [RevenueCatGateway] with an injected [FakeRcClient].
///
/// All tests run as pure host (dart vm) tests — no Flutter platform channel,
/// no purchases_flutter native code. The production SDK is kept behind the
/// [RcClient] injection point so tests can exercise all paths without any
/// real RevenueCat infrastructure.
///
/// Test coverage:
///   1. configure skipped when key empty → gateway behaves as stub (comingSoon).
///   2. Successful remove_ads purchase → Entitlements.removeAds true
///      + analytics `purchase` event logged.
///   3. Consumable purchase (streakFreeze) → increments streakFreezes count.
///   4. restore() maps returned entitlement IDs to Entitlements correctly.
///   5. SDK exception on purchase → graceful PurchaseOutcome.failed (no crash).
///   6. Cancellation PlatformException → PurchaseOutcome.cancelled.
///   7. themedPacks always returns comingSoon without touching SDK.
///   8. buildIapGateway() returns stub when iapEnabled=false (default).
///   9. (phase 6c) purchasePack(packId) maps to product id mm_pack_{packId}.
///  10. (phase 6c) entitlement ids "pack_{packId}" parse into Entitlements.packs.
///  11. (phase 6c) IapStubAdapter.purchasePack always returns comingSoon.
library;

import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/core/persistence.dart';
import 'package:mindmeld/iap/entitlements.dart';
import 'package:mindmeld/iap/iap_stub_adapter.dart';
import 'package:mindmeld/iap/revenuecat_gateway.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

// ---------------------------------------------------------------------------
// FakeRcClient — injectable test double
// ---------------------------------------------------------------------------

/// Configurable [RcClient] for tests.
///
/// - [shouldThrow]: when non-null, purchase() throws this exception.
/// - [cancelPurchase]: when true, purchase() throws a cancellation
///   [PlatformException] (errorCode = purchaseCancelledError index = 1).
/// - [purchaseEntitlements]: entitlement IDs returned after purchase.
/// - [customerEntitlements]: entitlement IDs returned by getCustomerInfo/restore.
class FakeRcClient implements RcClient {
  FakeRcClient({
    this.shouldThrow,
    this.cancelPurchase = false,
    this.purchaseEntitlements = const {},
    this.customerEntitlements = const {},
  });

  final Object? shouldThrow;
  final bool cancelPurchase;
  final Set<String> purchaseEntitlements;
  final Set<String> customerEntitlements;

  bool configured = false;
  String? lastConfiguredKey;
  String? lastPurchasedProductId;
  int purchaseCallCount = 0;
  int restoreCallCount = 0;

  @override
  Future<void> configure(String apiKey) async {
    configured = true;
    lastConfiguredKey = apiKey;
  }

  @override
  Future<RcPurchaseResult> purchase(String productId) async {
    purchaseCallCount++;
    lastPurchasedProductId = productId;

    if (cancelPurchase) {
      // purchaseCancelledError index is 1 in PurchasesErrorCode.
      throw PlatformException(code: '1', message: 'User cancelled');
    }
    if (shouldThrow != null) throw shouldThrow!;

    return RcPurchaseResult(
      activeEntitlementIds: purchaseEntitlements,
      purchasedProductId: productId,
    );
  }

  @override
  Future<RcCustomerInfo> restore() async {
    restoreCallCount++;
    return RcCustomerInfo(activeEntitlementIds: customerEntitlements);
  }

  @override
  Future<RcCustomerInfo> getCustomerInfo() async {
    return RcCustomerInfo(activeEntitlementIds: customerEntitlements);
  }
}

// ---------------------------------------------------------------------------
// Test setup
// ---------------------------------------------------------------------------

late Directory _tmpDir;

void main() {
  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  setUp(() async {
    AppPersistence.resetForTest();
    _tmpDir = await Directory.systemTemp.createTemp('mindmeld_rc_');
    await AppPersistence.instance.init(
      dbPath: p.join(_tmpDir.path, 'rc_test.db'),
    );
  });

  tearDown(() async {
    await AppPersistence.instance.close();
    AppPersistence.resetForTest();
    await _tmpDir.delete(recursive: true);
  });

  // -------------------------------------------------------------------------
  // Test 1: empty API key → SDK never configured, behaves as stub
  // -------------------------------------------------------------------------

  test('empty API key: SDK configure never called, factory returns stub',
      () async {
    final fake = FakeRcClient();

    // The factory checks iapEnabled AND key non-empty.
    // AppConfig.iapEnabled is false in test builds — factory returns stub
    // regardless of key value, and the SDK is never configured.
    final stubGateway = buildIapGateway(rcClient: fake);

    expect(stubGateway, isA<IapStubAdapter>());
    expect(fake.configured, isFalse,
        reason: 'SDK must not be configured when factory returns stub');
  });

  // -------------------------------------------------------------------------
  // Test 2: successful remove_ads purchase → removeAds=true + analytics event
  // -------------------------------------------------------------------------

  test(
      'successful remove_ads purchase → Entitlements.removeAds=true '
      'and purchase analytics event logged', () async {
    final fake = FakeRcClient(
      purchaseEntitlements: {kRcEntitlementRemoveAds},
      customerEntitlements: {kRcEntitlementRemoveAds},
    );
    final gateway = RevenueCatGateway(apiKey: 'test_key', rcClient: fake);

    final outcome = await gateway.purchase(Product.removeAds);

    expect(outcome, equals(PurchaseOutcome.success));
    expect(fake.lastPurchasedProductId, equals(kRcProductRemoveAds));

    final entitlements = await gateway.current();
    expect(entitlements.removeAds, isTrue);
    expect(entitlements.archive, isFalse);

    // Verify purchase analytics event was logged.
    final events = await AppPersistence.instance.exportAnalyticsBuffer();
    final purchaseEvents =
        events.where((e) => e['event_name'] == 'purchase').toList();
    expect(purchaseEvents, isNotEmpty,
        reason: 'purchase analytics event must be logged after successful buy');
  });

  // -------------------------------------------------------------------------
  // Test 3: consumable streakFreeze purchase → increments streakFreezes by 3
  // -------------------------------------------------------------------------

  test('streakFreeze purchase increments streakFreezes count by 3', () async {
    final fake = FakeRcClient(purchaseEntitlements: {});
    final gateway = RevenueCatGateway(apiKey: 'test_key', rcClient: fake);

    expect((await gateway.current()).streakFreezes, equals(0));

    final outcome = await gateway.purchase(Product.streakFreeze);

    expect(outcome, equals(PurchaseOutcome.success));
    expect(fake.lastPurchasedProductId, equals(kRcProductStreakFreeze3Pack));

    final entitlements = await gateway.current();
    expect(entitlements.streakFreezes, equals(3));

    // Second pack: accumulates.
    await gateway.purchase(Product.streakFreeze);
    expect((await gateway.current()).streakFreezes, equals(6));
  });

  // -------------------------------------------------------------------------
  // Test 4: restore() maps restored entitlement IDs to Entitlements
  // -------------------------------------------------------------------------

  test('restore() maps restored entitlement IDs correctly', () async {
    final fake = FakeRcClient(
      customerEntitlements: {
        kRcEntitlementRemoveAds,
        kRcEntitlementArchiveAccess,
      },
    );
    final gateway = RevenueCatGateway(apiKey: 'test_key', rcClient: fake);

    await gateway.restore();

    expect(fake.restoreCallCount, equals(1));

    // After restore, current() should reflect the new entitlements.
    final entitlements = await gateway.current();
    expect(entitlements.removeAds, isTrue);
    expect(entitlements.archive, isTrue);
  });

  // -------------------------------------------------------------------------
  // Test 5: SDK exception on purchase → PurchaseOutcome.failed (no crash)
  // -------------------------------------------------------------------------

  test('SDK exception on purchase → PurchaseOutcome.failed without throwing',
      () async {
    final fake = FakeRcClient(
      shouldThrow: Exception('store unavailable'),
    );
    final gateway = RevenueCatGateway(apiKey: 'test_key', rcClient: fake);

    final outcome = await gateway.purchase(Product.removeAds);

    expect(outcome, equals(PurchaseOutcome.failed));
  });

  // -------------------------------------------------------------------------
  // Test 6: Cancellation PlatformException → PurchaseOutcome.cancelled
  // -------------------------------------------------------------------------

  test('user cancellation PlatformException → PurchaseOutcome.cancelled',
      () async {
    final fake = FakeRcClient(cancelPurchase: true);
    final gateway = RevenueCatGateway(apiKey: 'test_key', rcClient: fake);

    final outcome = await gateway.purchase(Product.removeAds);

    expect(outcome, equals(PurchaseOutcome.cancelled));
  });

  // -------------------------------------------------------------------------
  // Test 7: themedPacks → comingSoon without touching SDK
  // -------------------------------------------------------------------------

  test('themedPacks purchase always returns comingSoon without SDK call',
      () async {
    final fake = FakeRcClient();
    final gateway = RevenueCatGateway(apiKey: 'test_key', rcClient: fake);

    final outcome = await gateway.purchase(Product.themedPacks);

    expect(outcome, equals(PurchaseOutcome.comingSoon));
    expect(fake.purchaseCallCount, equals(0),
        reason: 'SDK must never be called for themedPacks');
  });

  // -------------------------------------------------------------------------
  // Test 8: buildIapGateway with flags off returns IapStubAdapter
  // -------------------------------------------------------------------------

  test('buildIapGateway with iapEnabled=false returns IapStubAdapter', () {
    // AppConfig.iapEnabled is false in test builds (no dart-define).
    final gateway = buildIapGateway();
    expect(gateway, isA<IapStubAdapter>());
  });

  // -------------------------------------------------------------------------
  // Test 9: IapStubAdapter.purchase returns comingSoon for all products
  // -------------------------------------------------------------------------

  test('IapStubAdapter returns comingSoon for all products', () async {
    final adapter = IapStubAdapter();
    for (final product in Product.values) {
      final outcome = await adapter.purchase(product);
      expect(
        outcome,
        equals(PurchaseOutcome.comingSoon),
        reason: '${product.name} must return comingSoon in stub mode',
      );
    }
  });

  // -------------------------------------------------------------------------
  // Test 10: IapStubAdapter.current() always returns Entitlements.empty
  // -------------------------------------------------------------------------

  test('IapStubAdapter.current returns Entitlements.empty', () async {
    final adapter = IapStubAdapter();
    final e = await adapter.current();
    expect(e.removeAds, isFalse);
    expect(e.archive, isFalse);
    expect(e.streakFreezes, equals(0));
    expect(e.packs, isEmpty);
  });

  // -------------------------------------------------------------------------
  // Phase 6c: themed-pack purchases (purchasePack, not the generic enum flow)
  // -------------------------------------------------------------------------

  group('Themed pack purchases (phase 6c)', () {
    test('purchasePack maps packId to RC product id mm_pack_{packId}',
        () async {
      final fake = FakeRcClient(purchaseEntitlements: {'pack_bollywood'});
      final gateway = RevenueCatGateway(apiKey: 'test_key', rcClient: fake);

      final outcome = await gateway.purchasePack('bollywood');

      expect(outcome, equals(PurchaseOutcome.success));
      expect(fake.lastPurchasedProductId, equals('mm_pack_bollywood'));
    });

    test('entitlement ids "pack_{packId}" parse into Entitlements.packs',
        () async {
      final fake = FakeRcClient(
        customerEntitlements: {'pack_bollywood', 'pack_cricket', kRcEntitlementRemoveAds},
      );
      final gateway = RevenueCatGateway(apiKey: 'test_key', rcClient: fake);

      final entitlements = await gateway.current();

      expect(entitlements.packs, equals({'bollywood', 'cricket'}));
      expect(entitlements.removeAds, isTrue);
    });

    test('purchasePack SDK exception → PurchaseOutcome.failed without throwing',
        () async {
      final fake = FakeRcClient(shouldThrow: Exception('store unavailable'));
      final gateway = RevenueCatGateway(apiKey: 'test_key', rcClient: fake);

      final outcome = await gateway.purchasePack('bollywood');
      expect(outcome, equals(PurchaseOutcome.failed));
    });

    test('purchasePack cancellation → PurchaseOutcome.cancelled', () async {
      final fake = FakeRcClient(cancelPurchase: true);
      final gateway = RevenueCatGateway(apiKey: 'test_key', rcClient: fake);

      final outcome = await gateway.purchasePack('bollywood');
      expect(outcome, equals(PurchaseOutcome.cancelled));
    });

    test('IapStubAdapter.purchasePack always returns comingSoon', () async {
      final adapter = IapStubAdapter();
      final outcome = await adapter.purchasePack('bollywood');
      expect(outcome, equals(PurchaseOutcome.comingSoon));
    });
  });
}
