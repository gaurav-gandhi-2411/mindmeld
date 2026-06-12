// ignore_for_file: avoid_classes_with_only_static_members

/// Application-wide configuration constants.
///
/// Phase 1: ads and IAP are disabled behind config flags.
/// Phase 2 wires real SDKs by flipping these flags.
class AppConfig {
  /// Rewarded-ad integration is not live in Phase 1.
  /// When true the real AdMob SDK would be invoked.
  static const bool adsEnabled = false;

  /// IAP integration is not live in Phase 1.
  /// When true the real RevenueCat SDK would be invoked.
  static const bool iapEnabled = false;

  /// Base URL for fetching daily payloads.
  /// Override with an environment variable or build arg in production.
  static const String payloadBaseUrl = 'https://example.com/payloads';

  /// Languages supported in Phase 1.
  static const List<String> supportedLangs = ['en', 'hi-en'];

  /// Human-readable labels for each language key.
  static const Map<String, String> langLabels = {
    'en': 'English',
    'hi-en': 'Hinglish',
  };

  /// Temperature band thresholds — see [TemperatureBand] in models.dart.
  ///
  /// These are multipliers of vocab size n, applied by [bandForRank].
  /// Actual thresholds are max(floor, n * fraction).
  static const int scorchingFloor = 50;
  static const double scorchingFraction = 0.001;

  static const int hotFloor = 500;
  static const double hotFraction = 0.01;

  static const double warmFraction = 0.05;
  static const double coldFraction = 0.25;
}
