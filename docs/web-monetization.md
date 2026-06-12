# Web Monetization — Phase 4 Plan

## Current state (Phase 3)

On web, `AppConfig.adsEnabledEffective` and `AppConfig.iapEnabledEffective` are
always `false` regardless of dart-defines. `google_mobile_ads` and
`purchases_flutter` are native-only plugins; they are excluded from web
compilation via the effective-flag guards in `buildHintGate` and
`buildIapGateway`. Web users always receive the `RewardedAdStub` (free hint with
a 3-second simulated delay).

## Phase 4: AdsGateway for rewarded web ads

The existing `HintGate` interface is the integration point:

```dart
abstract class HintGate {
  Future<HintGateResult> requestHint(BuildContext context);
}
```

A Phase 4 `WebAdGateway` will implement `HintGate` using the **Google Ad Placement
API** (formerly H5 Games Ads / AFG rewarded interstitials):

1. Load the AFG SDK script (`//pagead2.googlesyndication.com/pagead/js/adsbygoogle.js`).
2. Call `adBreak({ type: 'reward', ... })` when the player taps the hint button.
3. Resolve `HintGateResult(granted: true, fallback: false)` on reward callback.
4. Fall back to `RewardedAdStub` if the ad slot returns no fill.

The `buildHintGate` factory in `rewarded_ad_service.dart` will route to
`WebAdGateway` when `kIsWeb && AppConfig.adsEnabledEffective` (once a web-safe
ads flag is introduced). The native path is byte-identical — the conditional
import pattern already in use for `share_stub.dart` / `share_web.dart` will
apply here too.

AFG documentation: https://developers.google.com/ad-placement/apis/adbreak
