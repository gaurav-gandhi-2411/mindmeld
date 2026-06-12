// IAP product stubs for Phase 1.
// Phase 2: Replace [IapStub] with real RevenueCat (or similar) calls.
// The [purchase] contract stays identical — callers need not change.
// Themed Packs are greyed out in the UI as "Coming Soon."

/// Available IAP product identifiers.
enum IapProduct {
  /// Remove all rewarded ads permanently.
  removeAds,

  /// Unlock the puzzle archive (play past days).
  archive,

  /// Protect your streak for one missed day.
  streakFreeze,

  /// Themed vocabulary packs (greyed out, Phase 3+).
  themedPacks,
}

/// Result of an attempted IAP purchase.
class PurchaseResult {
  const PurchaseResult({required this.success, required this.message});

  final bool success;
  final String message;
}

/// Stub IAP manager.
///
/// Phase 2 wires real store purchase flows here.
class IapStub {
  const IapStub();

  /// Human-readable display name for each product.
  static const Map<IapProduct, String> productNames = {
    IapProduct.removeAds: 'Remove Ads',
    IapProduct.archive: 'Puzzle Archive',
    IapProduct.streakFreeze: 'Streak Freeze',
    IapProduct.themedPacks: 'Themed Packs',
  };

  /// Whether a product is available for purchase in Phase 1.
  ///
  /// Themed Packs are Phase 3+ — always unavailable in Phase 1.
  static bool isAvailable(IapProduct product) {
    return product != IapProduct.themedPacks;
  }

  /// Attempt to purchase [product].
  ///
  /// Always returns a "coming soon" result in Phase 1.
  Future<PurchaseResult> purchase(IapProduct product) async {
    // Phase 2: initiate real purchase via RevenueCat:
    //   final result = await Purchases.purchaseProduct(productId);
    //   return PurchaseResult(success: result.entitlements.active.isNotEmpty, ...);
    return const PurchaseResult(
      success: false,
      message: 'Coming soon! In-app purchases will be available in the next update.',
    );
  }

  /// Restore previously purchased products.
  ///
  /// No-op stub in Phase 1.
  Future<void> restorePurchases() async {
    // Phase 2: await Purchases.restorePurchases();
  }
}
