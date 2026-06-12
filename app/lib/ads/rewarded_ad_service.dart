/// Rewarded-ad gate abstraction used by the puzzle screen.
///
/// [HintGate] is the single interface both the stub and the real AdMob
/// implementation satisfy.  [buildHintGate] is the factory the puzzle screen
/// calls — it routes to [AdMobRewardedGate] when [AppConfig.adsEnabled] is
/// true, otherwise to a [_StubGate] wrapping [RewardedAdStub].
///
/// ## Test injection
///
/// [AdMobRewardedGate] accepts an [AdLoader] function that production code
/// supplies as [defaultAdLoader].  Tests replace it with a lambda that either
/// throws (simulating load failure → fallback) or returns a [FakeLoadedAd]
/// (simulating successful load + reward).  This keeps google_mobile_ads
/// platform channels completely out of host tests.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:google_mobile_ads/google_mobile_ads.dart';
import 'package:mindmeld/core/config.dart';
import 'package:mindmeld/core/persistence.dart';
import 'package:mindmeld/stubs/analytics_stub.dart';
import 'package:mindmeld/stubs/rewarded_ad_stub.dart';

// ---------------------------------------------------------------------------
// Result type
// ---------------------------------------------------------------------------

/// Outcome of a [HintGate.requestHint] call.
class HintGateResult {
  const HintGateResult({required this.granted, required this.fallback});

  /// True if the player is entitled to a hint (reward earned or stub ran).
  final bool granted;

  /// True when the result came from the stub fallback rather than a live ad.
  final bool fallback;
}

// ---------------------------------------------------------------------------
// Abstract interface
// ---------------------------------------------------------------------------

/// Contract that both the stub gate and real AdMob gate satisfy.
///
/// Puzzle screen calls [requestHint] and acts on [HintGateResult.granted].
abstract class HintGate {
  /// Show a rewarded ad (or stub) and resolve with the grant outcome.
  ///
  /// Implementors MUST NOT throw — catch failures internally and return
  /// `granted: true, fallback: true` so the player always gets their hint.
  Future<HintGateResult> requestHint(BuildContext context);
}

// ---------------------------------------------------------------------------
// Ad loader injection point (decouples platform channel from unit tests)
// ---------------------------------------------------------------------------

/// A loaded ad handle returned by an [AdLoader].
///
/// The real implementation wraps [RewardedAd]; tests use [FakeLoadedAd].
abstract class LoadedAdHandle {
  /// Show the ad. Resolves true if the user earned a reward, false otherwise.
  Future<bool> show();
}

/// Function type injected into [AdMobRewardedGate] to load a rewarded ad.
///
/// Must complete with a [LoadedAdHandle] on success or throw on failure.
typedef AdLoader = Future<LoadedAdHandle> Function(String adUnitId);

// ---------------------------------------------------------------------------
// Production AdLoader implementation
// ---------------------------------------------------------------------------

/// Wraps a live [RewardedAd] returned by the google_mobile_ads SDK.
class _LiveRewardedAdHandle implements LoadedAdHandle {
  _LiveRewardedAdHandle(this._ad);

  final RewardedAd _ad;

  @override
  Future<bool> show() {
    final completer = Completer<bool>();

    _ad.fullScreenContentCallback = FullScreenContentCallback<RewardedAd>(
      onAdDismissedFullScreenContent: (ad) {
        ad.dispose();
        // If the user dismissed without earning, complete with false.
        if (!completer.isCompleted) completer.complete(false);
      },
      onAdFailedToShowFullScreenContent: (ad, error) {
        ad.dispose();
        if (!completer.isCompleted) {
          completer.completeError(
            Exception('RewardedAd show failed: ${error.message}'),
          );
        }
      },
    );

    _ad.show(
      // ignore: avoid_types_on_closure_parameters — SDK callback signature requires typed params
      onUserEarnedReward: (AdWithoutView ad, RewardItem reward) {
        // Complete with true on reward; dismiss callback will fire after.
        if (!completer.isCompleted) completer.complete(true);
      },
    );

    return completer.future;
  }
}

/// Production [AdLoader] that calls the real google_mobile_ads platform channel.
///
/// This is the only place in the codebase that calls [RewardedAd.load].
/// Tests never call this — they inject [FakeLoadedAd] via [AdMobRewardedGate].
Future<LoadedAdHandle> defaultAdLoader(String adUnitId) {
  final completer = Completer<LoadedAdHandle>();

  RewardedAd.load(
    adUnitId: adUnitId,
    request: const AdRequest(),
    rewardedAdLoadCallback: RewardedAdLoadCallback(
      onAdLoaded: (ad) => completer.complete(_LiveRewardedAdHandle(ad)),
      onAdFailedToLoad: (error) => completer.completeError(
        Exception('RewardedAd load failed: ${error.message}'),
      ),
    ),
  );

  return completer.future;
}

// ---------------------------------------------------------------------------
// AdMobRewardedGate
// ---------------------------------------------------------------------------

/// Timeout before falling back to the stub if the ad has not loaded.
const Duration _kAdLoadTimeout = Duration(seconds: 8);

/// Implements [HintGate] using the real AdMob rewarded-ad SDK.
///
/// ## Fallback behaviour
///
/// If the ad fails to load, times out (> 8 s), or fails to show, the gate
/// falls back to [RewardedAdStub] so the player still gets their hint.
/// [HintGateResult.fallback] is true in that case and an `ad_watched`
/// analytics event is logged with `{fallback: true}`.
///
/// ## Test injection
///
/// Supply a custom [adLoader] to bypass the real SDK:
/// ```dart
/// // Exercises the fallback path:
/// AdMobRewardedGate(adLoader: (_) async => throw Exception('no fill'));
///
/// // Exercises the happy path:
/// AdMobRewardedGate(adLoader: (_) async => FakeLoadedAd(rewarded: true));
/// ```
class AdMobRewardedGate implements HintGate {
  AdMobRewardedGate({
    AdLoader? adLoader,
    RewardedAdStub? fallbackStub,
  })  : _adLoader = adLoader ?? defaultAdLoader,
        _fallbackStub = fallbackStub ?? const RewardedAdStub();

  final AdLoader _adLoader;
  final RewardedAdStub _fallbackStub;

  AnalyticsStub get _analytics => AnalyticsStub(AppPersistence.instance);

  @override
  Future<HintGateResult> requestHint(BuildContext context) async {
    LoadedAdHandle? handle;

    try {
      handle = await _adLoader(AppConfig.admobRewardedAdUnitId)
          .timeout(_kAdLoadTimeout);
    } catch (_) {
      // Load failed or timed out — fall back to stub.
      if (!context.mounted) {
        return const HintGateResult(granted: false, fallback: true);
      }
      return _fallback(context);
    }

    try {
      final rewarded = await handle.show();
      if (!context.mounted) {
        return const HintGateResult(granted: false, fallback: true);
      }
      if (!rewarded) {
        // Dismissed without reward — still give the hint via stub flow.
        return _fallback(context);
      }
      await _logAdWatched(fallback: false);
      return const HintGateResult(granted: true, fallback: false);
    } catch (_) {
      if (!context.mounted) {
        return const HintGateResult(granted: false, fallback: true);
      }
      return _fallback(context);
    }
  }

  Future<HintGateResult> _fallback(BuildContext context) async {
    // context.mounted is guaranteed by callers before this is called.
    final granted = await _fallbackStub.show(context);
    await _logAdWatched(fallback: true);
    return HintGateResult(granted: granted, fallback: true);
  }

  Future<void> _logAdWatched({required bool fallback}) async {
    await _analytics.logEvent(AnalyticsEvent.adWatched, {'fallback': fallback});
  }
}

// ---------------------------------------------------------------------------
// Stub gate
// ---------------------------------------------------------------------------

/// Wraps [RewardedAdStub] to satisfy the [HintGate] interface.
class _StubGate implements HintGate {
  const _StubGate(this._stub);

  final RewardedAdStub _stub;

  @override
  Future<HintGateResult> requestHint(BuildContext context) async {
    final granted = await _stub.show(context);
    return HintGateResult(granted: granted, fallback: true);
  }
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/// Construct the appropriate [HintGate] for the current build configuration.
///
/// - [AppConfig.adsEnabled] = true  → [AdMobRewardedGate]
/// - [AppConfig.adsEnabled] = false → [_StubGate] wrapping [RewardedAdStub]
///
/// The optional [adStub] and [adLoader] parameters allow tests to inject
/// fakes without touching dart-defines.
HintGate buildHintGate({
  RewardedAdStub? adStub,
  AdLoader? adLoader,
}) {
  // adsEnabledEffective is false on web — web always gets the stub gate.
  // google_mobile_ads is a native-only plugin; it must not be invoked on web.
  if (AppConfig.adsEnabledEffective) {
    return AdMobRewardedGate(adLoader: adLoader);
  }
  return _StubGate(adStub ?? const RewardedAdStub());
}

// ---------------------------------------------------------------------------
// Fake ad handle (public — used in unit tests)
// ---------------------------------------------------------------------------

/// A [LoadedAdHandle] that immediately resolves with [rewarded].
///
/// Use this in tests to inject into [AdMobRewardedGate] without a platform
/// channel:
/// ```dart
/// final gate = AdMobRewardedGate(
///   adLoader: (_) async => const FakeLoadedAd(rewarded: true),
/// );
/// ```
class FakeLoadedAd implements LoadedAdHandle {
  const FakeLoadedAd({required this.rewarded});

  final bool rewarded;

  @override
  Future<bool> show() async => rewarded;
}
