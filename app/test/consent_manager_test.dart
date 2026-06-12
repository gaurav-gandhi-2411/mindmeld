/// Tests for [ConsentManager].
///
/// The UMP flow itself cannot be exercised on the host (non-Android) test
/// runner because it requires the google_mobile_ads native channel.  These
/// tests verify the one behavioural guarantee that IS testable without a
/// platform channel: when [AppConfig.adsEnabled] is false (the default in
/// all test builds), [ConsentManager.gatherConsent] returns immediately
/// without making any platform calls.
///
/// Structure: one unit test that calls gatherConsent and expects it to
/// complete without error.  A timeout guard ensures it truly short-circuits
/// (if it attempted a real UMP call it would throw MissingPluginException).
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/ads/consent_manager.dart';
import 'package:mindmeld/core/config.dart';

void main() {
  // -------------------------------------------------------------------------
  // Guard: adsEnabled is false in test builds
  // -------------------------------------------------------------------------

  test('AppConfig.adsEnabled is false in test builds (no dart-define set)', () {
    // This assertion locks the expectation that test builds are non-monetised.
    // If someone runs tests with --dart-define=MONETIZED=true the flag flips
    // and the consent manager test below would attempt real UMP calls.
    expect(AppConfig.adsEnabled, isFalse,
        reason: 'Tests must run without --dart-define=ADS_ENABLED=true or '
            '--dart-define=MONETIZED=true');
  });

  // -------------------------------------------------------------------------
  // Short-circuits when adsEnabled=false
  // -------------------------------------------------------------------------

  test(
    'ConsentManager.gatherConsent completes immediately when adsEnabled=false',
    () async {
      // When adsEnabled=false, gatherConsent must return without doing anything.
      // If it called ConsentInformation or ConsentForm it would throw
      // MissingPluginException on the host test runner.
      await expectLater(
        ConsentManager.gatherConsent(),
        completes,
        reason: 'gatherConsent must short-circuit when adsEnabled=false',
      );
    },
  );
}
