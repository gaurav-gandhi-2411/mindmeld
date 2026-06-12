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

  static const double warmFraction = 0.05;
  static const double coldFraction = 0.25;
}
