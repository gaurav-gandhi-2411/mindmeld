/// RevenueCat-backed [IapGateway] implementation.
///
/// ## Architecture — thin client injection
///
/// All purchases_flutter SDK calls are routed through an [RcClient] abstract
/// interface.  Production code supplies [defaultRcClient]; host tests inject a
/// [FakeRcClient] that never touches a platform channel.  This mirrors the
/// [AdLoader] pattern from rewarded_ad_service.dart.
///
/// ## Key-empty guard
///
/// If [AppConfig.revenueCatApiKey] is empty at construction time the gateway
/// logs a warning and falls back to [IapStubAdapter], which returns
/// [PurchaseOutcome.comingSoon] for all calls.
///
/// ## Product → entitlement-id mapping
///
/// | IapProduct      | RC product ID          | RC entitlement ID  |
/// |-----------------|------------------------|--------------------|
/// | removeAds       | remove_ads             | remove_ads         |
/// | archive         | archive_access         | archive_access     |
/// | streakFreeze    | streak_freeze_3pack    | (consumable)       |
/// | themedPacks     | —                      | —                  |
library;

import 'dart:developer' as dev;

import 'package:flutter/services.dart';
import 'package:purchases_flutter/purchases_flutter.dart';

import 'package:mindmeld/core/config.dart';
import 'package:mindmeld/iap/entitlements.dart';
import 'package:mindmeld/iap/iap_stub_adapter.dart';
import 'package:mindmeld/stubs/analytics_stub.dart';
import 'package:mindmeld/stubs/iap_stub.dart';
import 'package:mindmeld/core/persistence.dart';

// ---------------------------------------------------------------------------
// Product ID constants (single source of truth for RC dashboard setup)
// ---------------------------------------------------------------------------

/// RevenueCat product identifier for the Remove Ads non-consumable.
const String kRcProductRemoveAds = 'remove_ads';

/// RevenueCat product identifier for the Archive Access non-consumable.
const String kRcProductArchiveAccess = 'archive_access';

/// RevenueCat product identifier for the Streak Freeze 3-pack consumable.
const String kRcProductStreakFreeze3Pack = 'streak_freeze_3pack';

/// RevenueCat entitlement identifier for Remove Ads.
const String kRcEntitlementRemoveAds = 'remove_ads';

/// RevenueCat entitlement identifier for Archive Access.
const String kRcEntitlementArchiveAccess = 'archive_access';

// ---------------------------------------------------------------------------
// Thin-client value types
// ---------------------------------------------------------------------------

/// Result of a successful [RcClient.purchase] call.
class RcPurchaseResult {
  const RcPurchaseResult({
    required this.activeEntitlementIds,
    required this.purchasedProductId,
  });

  /// Active entitlement IDs after the purchase completed.
  final Set<String> activeEntitlementIds;

  /// The product ID that was just purchased (used to track consumable grants).
  final String purchasedProductId;
}

/// Result of [RcClient.getCustomerInfo] or [RcClient.restore].
class RcCustomerInfo {
  const RcCustomerInfo({required this.activeEntitlementIds});

  /// Entitlement IDs currently active for this customer.
  final Set<String> activeEntitlementIds;
}

// ---------------------------------------------------------------------------
// Thin-client interface (injectable for tests)
// ---------------------------------------------------------------------------

/// Thin wrapper interface around the purchases_flutter SDK.
///
/// Tests inject a [FakeRcClient]; production supplies [defaultRcClient].
abstract class RcClient {
  /// Configure the SDK with [apiKey]. Safe to call multiple times (idempotent).
  Future<void> configure(String apiKey);

  /// Purchase [productId].
  ///
  /// Throws [PlatformException] on cancellation or failure.
  /// Callers must check [PurchasesErrorHelper.getErrorCode] for cancellation.
  Future<RcPurchaseResult> purchase(String productId);

  /// Restore purchases and return updated customer info.
  Future<RcCustomerInfo> restore();

  /// Fetch current customer info (cached by SDK).
  Future<RcCustomerInfo> getCustomerInfo();
}

// ---------------------------------------------------------------------------
// Production RcClient implementation
// ---------------------------------------------------------------------------

/// Production [RcClient] that calls the real purchases_flutter SDK.
///
/// This is the only place in the codebase that calls [Purchases.*] methods.
/// Tests never instantiate this class.
class _LiveRcClient implements RcClient {
  bool _configured = false;

  @override
  Future<void> configure(String apiKey) async {
    if (_configured) return;
    await Purchases.configure(PurchasesConfiguration(apiKey));
    _configured = true;
  }

  @override
  Future<RcPurchaseResult> purchase(String productId) async {
    // Fetch offerings → find the StoreProduct matching productId.
    final offerings = await Purchases.getOfferings();
    StoreProduct? product;
    for (final offering in offerings.all.values) {
      for (final package in offering.availablePackages) {
        if (package.storeProduct.identifier == productId) {
          product = package.storeProduct;
          break;
        }
      }
      if (product != null) break;
    }

    if (product == null) {
      throw PlatformException(
        code: '${PurchasesErrorCode.productNotAvailableForPurchaseError.index}',
        message: 'Product $productId not found in offerings',
      );
    }

    // Use the non-deprecated purchase(PurchaseParams) API.
    final result = await Purchases.purchase(PurchaseParams.storeProduct(product));
    return RcPurchaseResult(
      activeEntitlementIds: result.customerInfo.entitlements.active.keys.toSet(),
      purchasedProductId: productId,
    );
  }

  @override
  Future<RcCustomerInfo> restore() async {
    final info = await Purchases.restorePurchases();
    return RcCustomerInfo(
      activeEntitlementIds: info.entitlements.active.keys.toSet(),
    );
  }

  @override
  Future<RcCustomerInfo> getCustomerInfo() async {
    final info = await Purchases.getCustomerInfo();
    return RcCustomerInfo(
      activeEntitlementIds: info.entitlements.active.keys.toSet(),
    );
  }
}

/// Production [RcClient] singleton.
final RcClient defaultRcClient = _LiveRcClient();

// ---------------------------------------------------------------------------
// RevenueCatGateway
// ---------------------------------------------------------------------------

/// [IapGateway] backed by the RevenueCat SDK.
///
/// Construct via [buildIapGateway] rather than directly.
class RevenueCatGateway implements IapGateway {
  RevenueCatGateway({
    required this.apiKey,
    RcClient? rcClient,
  }) : _rcClient = rcClient ?? defaultRcClient;

  /// The RevenueCat public API key used to configure the SDK.
  final String apiKey;
  final RcClient _rcClient;

  // Cached streak-freeze count (consumables are not tracked as entitlements).
  int _streakFreezes = 0;

  bool _configured = false;

  AnalyticsStub get _analytics => AnalyticsStub(AppPersistence.instance);

  /// Lazily configure the SDK on first use.
  Future<void> _ensureConfigured() async {
    if (_configured) return;
    await _rcClient.configure(apiKey);
    _configured = true;
  }

  // ---------------------------------------------------------------------------
  // IapGateway interface
  // ---------------------------------------------------------------------------

  @override
  Future<PurchaseOutcome> purchase(Product product) async {
    if (product == IapProduct.themedPacks) {
      return PurchaseOutcome.comingSoon;
    }

    final productId = _productId(product);
    if (productId == null) return PurchaseOutcome.comingSoon;

    try {
      await _ensureConfigured();
      final result = await _rcClient.purchase(productId);

      // Consumable: increment local count (streak freezes come in a 3-pack).
      if (product == IapProduct.streakFreeze) {
        _streakFreezes += 3;
      }

      // Log purchase analytics event.
      await _analytics.logEvent('purchase', {
        'product': product.name,
        'entitlements': result.activeEntitlementIds.toList(),
      });

      return PurchaseOutcome.success;
    } on PlatformException catch (e) {
      final errorCode = PurchasesErrorHelper.getErrorCode(e);
      if (errorCode == PurchasesErrorCode.purchaseCancelledError) {
        return PurchaseOutcome.cancelled;
      }
      dev.log(
        'RevenueCatGateway.purchase failed: ${e.message}',
        name: 'RevenueCatGateway',
      );
      return PurchaseOutcome.failed;
    } catch (e) {
      dev.log(
        'RevenueCatGateway.purchase unexpected error: $e',
        name: 'RevenueCatGateway',
      );
      return PurchaseOutcome.failed;
    }
  }

  @override
  Future<void> restore() async {
    try {
      await _ensureConfigured();
      await _rcClient.restore();
    } catch (e) {
      dev.log('RevenueCatGateway.restore error: $e', name: 'RevenueCatGateway');
    }
  }

  @override
  Future<Entitlements> current() async {
    try {
      await _ensureConfigured();
      final info = await _rcClient.getCustomerInfo();
      return _entitlementsFromIds(info.activeEntitlementIds);
    } catch (e) {
      dev.log('RevenueCatGateway.current error: $e', name: 'RevenueCatGateway');
      return Entitlements(streakFreezes: _streakFreezes);
    }
  }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  /// Maps [IapProduct] → RevenueCat product ID string.
  String? _productId(IapProduct product) => switch (product) {
        IapProduct.removeAds => kRcProductRemoveAds,
        IapProduct.archive => kRcProductArchiveAccess,
        IapProduct.streakFreeze => kRcProductStreakFreeze3Pack,
        IapProduct.themedPacks => null,
      };

  /// Converts a set of active RC entitlement IDs to an [Entitlements] value.
  Entitlements _entitlementsFromIds(Set<String> ids) => Entitlements(
        removeAds: ids.contains(kRcEntitlementRemoveAds),
        archive: ids.contains(kRcEntitlementArchiveAccess),
        streakFreezes: _streakFreezes,
      );
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/// Construct the appropriate [IapGateway] for the current build configuration.
///
/// - [AppConfig.iapEnabled] = true AND [AppConfig.revenueCatApiKey] non-empty
///   → [RevenueCatGateway]
/// - Otherwise → [IapStubAdapter] wrapping [IapStub] (stub mode)
///
/// The optional [rcClient] parameter allows tests to inject a [FakeRcClient]
/// without touching dart-defines.
IapGateway buildIapGateway({RcClient? rcClient}) {
  final key = AppConfig.revenueCatApiKey;
  // iapEnabledEffective is false on web — purchases_flutter is native-only.
  if (AppConfig.iapEnabledEffective && key.isNotEmpty) {
    return RevenueCatGateway(apiKey: key, rcClient: rcClient);
  }
  // rcClient is not used in stub mode; ignore the parameter.
  if (AppConfig.iapEnabledEffective && key.isEmpty) {
    dev.log(
      'iapEnabled=true but REVENUECAT_API_KEY is empty — falling back to stub',
      name: 'buildIapGateway',
    );
  }
  return IapStubAdapter();
}
