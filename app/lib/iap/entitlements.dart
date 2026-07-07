// ignore_for_file: avoid_classes_with_only_static_members

/// IAP gateway interface and associated value types.
///
/// Both [IapStub]-backed and RevenueCat-backed implementations satisfy
/// [IapGateway] without inheritance (structural conformance via `implements`).
///
/// ## Product → entitlement mapping (for RevenueCat dashboard setup)
///
/// | Product enum      | RC product ID           | RC entitlement ID   | Type          |
/// |-------------------|-------------------------|---------------------|---------------|
/// | removeAds         | `remove_ads`            | `remove_ads`        | non-consumable|
/// | archive           | `archive_access`        | `archive_access`    | non-consumable|
/// | streakFreeze      | `streak_freeze_3pack`   | *(consumable)*      | consumable    |
/// | themedPacks       | *(coming soon)*         | *(coming soon)*     | —             |
library;

import 'package:mindmeld/stubs/iap_stub.dart';

// ---------------------------------------------------------------------------
// Product enum (re-exported alias — callers use IapProduct from iap_stub.dart)
// ---------------------------------------------------------------------------

/// Alias so callers of the gateway don't need to import iap_stub.dart directly.
typedef Product = IapProduct;

// ---------------------------------------------------------------------------
// Result types
// ---------------------------------------------------------------------------

/// Outcome of a [IapGateway.purchase] call.
enum PurchaseOutcome {
  /// Purchase completed successfully; entitlements have been updated.
  success,

  /// User cancelled the purchase flow (not an error).
  cancelled,

  /// Purchase failed due to a store or SDK error.
  failed,

  /// Purchase is in stub mode — always returns this in the non-IAP build.
  comingSoon,
}

/// Current set of entitlements the user holds.
///
/// All fields default to their "nothing unlocked" state.
class Entitlements {
  const Entitlements({
    this.removeAds = false,
    this.archive = false,
    this.streakFreezes = 0,
    this.packs = const {},
  });

  /// User has purchased the Remove Ads product.
  final bool removeAds;

  /// User has purchased archive access (play past puzzles).
  final bool archive;

  /// Number of unconsumed streak-freeze uses remaining.
  final int streakFreezes;

  /// IDs of themed packs (phase 6c) the user has purchased.
  final Set<String> packs;

  /// The null / nothing-unlocked state.
  static const Entitlements empty = Entitlements();

  Entitlements copyWith({
    bool? removeAds,
    bool? archive,
    int? streakFreezes,
    Set<String>? packs,
  }) {
    return Entitlements(
      removeAds: removeAds ?? this.removeAds,
      archive: archive ?? this.archive,
      streakFreezes: streakFreezes ?? this.streakFreezes,
      packs: packs ?? this.packs,
    );
  }

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is Entitlements &&
          runtimeType == other.runtimeType &&
          removeAds == other.removeAds &&
          archive == other.archive &&
          streakFreezes == other.streakFreezes &&
          packs.length == other.packs.length &&
          packs.containsAll(other.packs));

  @override
  int get hashCode => Object.hash(
        removeAds,
        archive,
        streakFreezes,
        Object.hashAllUnordered(packs),
      );

  @override
  String toString() =>
      'Entitlements(removeAds: $removeAds, archive: $archive, '
      'streakFreezes: $streakFreezes, packs: $packs)';
}

// ---------------------------------------------------------------------------
// IapGateway interface
// ---------------------------------------------------------------------------

/// Contract that both the stub adapter and the RevenueCat gateway satisfy.
///
/// Puzzle screen and settings screen call into this interface; they are
/// unaware of whether the real SDK is active.
abstract class IapGateway {
  /// Attempt to purchase [product].
  ///
  /// Implementations MUST NOT throw — catch all SDK exceptions internally and
  /// return [PurchaseOutcome.failed].
  Future<PurchaseOutcome> purchase(Product product);

  /// Restore previously purchased products and refresh [current].
  Future<void> restore();

  /// Return the current set of entitlements without a network round-trip.
  ///
  /// Implementations should cache; this is called on every settings-screen
  /// build to decide which rows show "unlocked".
  Future<Entitlements> current();

  /// Consume one streak-freeze use (decrement the counter by 1).
  ///
  /// No-op when zero freezes remain. Implementations that do not track
  /// freezes may treat this as a no-op.
  Future<void> consumeStreakFreeze();

  /// Attempt to purchase themed pack [packId] (phase 6c).
  ///
  /// Implementations MUST NOT throw — catch all SDK exceptions internally and
  /// return [PurchaseOutcome.failed].
  Future<PurchaseOutcome> purchasePack(String packId);
}
