// ignore_for_file: avoid_classes_with_only_static_members

/// Application-wide configuration constants.
///
/// Single monetisation toggle:
///   flutter build ... --dart-define=MONETIZED=true
///
/// Individual flags can also be set independently:
///   --dart-define=ADS_ENABLED=true
///   --dart-define=IAP_ENABLED=true
///   --dart-define=ANALYTICS_ENABLED=true
///
/// Defaults keep everything OFF and point to Google's TEST IDs so that a plain
/// `flutter run` / `flutter test` never touches production ad inventory.
class AppConfig {
  // ---------------------------------------------------------------------------
  // Monetisation gate
  // ---------------------------------------------------------------------------

  /// Master switch: set --dart-define=MONETIZED=true to enable all monetised
  /// features in a single flag. Individual flags below default to this value
  /// so a single build arg is enough for a full monetised build.
  static const bool monetized = bool.fromEnvironment('MONETIZED');

  /// Rewarded-ad integration. When true the real AdMob SDK is invoked.
  /// Defaults to [monetized] so --dart-define=MONETIZED=true turns it on.
  // ignore: avoid_bool_literals_in_conditional_expressions
  static const bool adsEnabled =
      bool.fromEnvironment('ADS_ENABLED') ? true : monetized;

  /// IAP integration. When true the real RevenueCat SDK would be invoked.
  // ignore: avoid_bool_literals_in_conditional_expressions
  static const bool iapEnabled =
      bool.fromEnvironment('IAP_ENABLED') ? true : monetized;

  /// Analytics integration. When true real remote analytics would be sent.
  // ignore: avoid_bool_literals_in_conditional_expressions
  static const bool analyticsEnabled =
      bool.fromEnvironment('ANALYTICS_ENABLED') ? true : monetized;

  // ---------------------------------------------------------------------------
  // Effective flags — web guards
  //
  // Native-only plugins (google_mobile_ads, purchases_flutter) must never be
  // invoked on web. These getters short-circuit to false when kIsWeb is true
  // so that factory methods and consumption sites always get a safe value
  // without needing to check kIsWeb themselves.
  // ---------------------------------------------------------------------------

  /// Effective ads flag: false on web regardless of [adsEnabled].
  ///
  /// google_mobile_ads is a native-only plugin; web builds always use the stub.
  // ignore: do_not_use_environment — kIsWeb is a compile-time const on all targets
  static bool get adsEnabledEffective {
    // dart.library.js_interop, not dart.library.html: html is FALSE under the
    // --wasm production build target, which would let this guard fall through
    // to `adsEnabled` on web (google_mobile_ads is native-only and must never
    // be invoked there). js_interop is true for BOTH web compile targets
    // (dart2js/DDC and dart2wasm), false on native — this must return false on
    // BOTH web targets. We reference it via a conditional to keep this file
    // free of dart:html/js_interop imports.
    if (const bool.fromEnvironment('dart.library.js_interop')) return false;
    return adsEnabled;
  }

  /// Effective IAP flag: false on web regardless of [iapEnabled].
  ///
  /// purchases_flutter is a native-only plugin; web builds always use the stub.
  static bool get iapEnabledEffective {
    // See adsEnabledEffective above: must be false on BOTH web compile
    // targets, so this keys on dart.library.js_interop, not dart.library.html.
    if (const bool.fromEnvironment('dart.library.js_interop')) return false;
    return iapEnabled;
  }

  // ---------------------------------------------------------------------------
  // Play URL — used in share card (viral loop) on all platforms.
  // ---------------------------------------------------------------------------

  /// Public play URL appended to the share card so recipients can immediately
  /// start playing. Included on all platforms (native + web).
  static const String playUrl = 'https://playwarmer.vercel.app/';

  // ---------------------------------------------------------------------------
  // AdMob IDs
  // ---------------------------------------------------------------------------

  /// AdMob rewarded-ad unit ID.
  ///
  /// Default: Google's official TEST rewarded ID. Production builds must
  /// supply the real ID via --dart-define=ADMOB_REWARDED_ID=ca-app-pub-...
  static const String admobRewardedAdUnitId = String.fromEnvironment(
    'ADMOB_REWARDED_ID',
    defaultValue: 'ca-app-pub-3940256099942544/5224354917',
  );

  /// AdMob application ID.
  ///
  /// Default: Google's official TEST app ID. Production builds must supply
  /// the real ID via --dart-define=ADMOB_APP_ID=ca-app-pub-...
  ///
  /// Note: the AndroidManifest.xml cannot read dart-defines at build time, so
  /// the TEST app ID is also hardcoded in the manifest. Phase-3 nicety: wire
  /// manifestPlaceholders in build.gradle.kts and use ${admobAppId} in manifest.
  static const String admobAppId = String.fromEnvironment(
    'ADMOB_APP_ID',
    defaultValue: 'ca-app-pub-3940256099942544~3347511713',
  );

  // ---------------------------------------------------------------------------
  // Hint / ad frequency cap
  // ---------------------------------------------------------------------------

  /// Maximum rewarded hints a player may unlock per day per language.
  ///
  /// This is a product rule (not an ad rule) — it applies in both stub and
  /// real AdMob modes. When [DayState.revealedHints.length] reaches this
  /// value the hint button is disabled with a "No more hints today" label.
  static const int maxHintsPerDay = 5;

  // ---------------------------------------------------------------------------
  // RevenueCat
  // ---------------------------------------------------------------------------

  /// RevenueCat public API key.
  ///
  /// Empty default keeps the app in stub mode so plain `flutter run` / `flutter
  /// test` never touches RevenueCat infrastructure. Production builds must
  /// supply the real key via `--dart-define=REVENUECAT_API_KEY=<key>`.
  static const String revenueCatApiKey = String.fromEnvironment('REVENUECAT_API_KEY');

  // ---------------------------------------------------------------------------
  // Base URL
  // ---------------------------------------------------------------------------

  /// Base URL for fetching daily payloads.
  /// Override with an environment variable or build arg in production.
  /// Points to the GitHub Pages host serving {lang}/{yyyy-MM-dd}.json.gz.
  static const String payloadBaseUrl =
      'https://gaurav-gandhi-2411.github.io/mindmeld-payloads';

  // ---------------------------------------------------------------------------
  // Language config
  // ---------------------------------------------------------------------------

  /// Languages supported in Phase 1.
  static const List<String> supportedLangs = ['en', 'hi-en'];

  /// Human-readable labels for each language key.
  static const Map<String, String> langLabels = {
    'en': 'English',
    'hi-en': 'Hinglish',
  };

  // ---------------------------------------------------------------------------
  // Temperature band thresholds — see [TemperatureBand] in models.dart
  // ---------------------------------------------------------------------------

  /// These are multipliers of vocab size n, applied by [bandForRank].
  /// Actual thresholds are max(floor, n * fraction).
  static const int scorchingFloor = 50;
  static const double scorchingFraction = 0.001;

  static const int hotFloor = 500;
  static const double hotFraction = 0.01;

  /// Floor added alongside scorching's/hot's existing floors (same max(floor,
  /// fraction) shape) to fix a band-calibration bug: for small vocabs (e.g.
  /// hi-en, n~10,495) hot's 500-rank floor already consumes most of the
  /// un-floored n*0.05=525 warm ceiling, squeezing Warm down to a 24-rank
  /// sliver (0.23% of vocab) versus EN's healthy 2,200-rank/4.0% Warm band at
  /// n=55,000. A floor of 900 leaves EN's own thresholds byte-for-byte
  /// unchanged (55,000 * 0.05 = 2,750 >> 900, so the floor never binds there)
  /// while giving hi-en a ~400-rank/3.8% Warm band -- matching EN's existing
  /// proportional feel. See docs/known-limitations.md #18 and PLAN.md.
  static const int warmFloor = 900;
  static const double warmFraction = 0.05;
  static const double coldFraction = 0.25;
}
