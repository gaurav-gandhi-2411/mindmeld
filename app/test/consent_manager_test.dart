/// Tests for [ConsentManager].
///
/// The UMP flow itself cannot be exercised on the host (non-Android) test
/// runner because it requires the google_mobile_ads native channel.  These
/// tests verify the behavioural guarantees that ARE testable without a platform
/// channel: when [AppConfig.adsEnabled] is false (the default in all test
/// builds), each method returns immediately without making any platform calls.
///
/// UMP API names used (google_mobile_ads 9.0.0):
///   - [ConsentInformation.getPrivacyOptionsRequirementStatus] →
///     [PrivacyOptionsRequirementStatus]
///   - [ConsentForm.showPrivacyOptionsForm]
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
    // and the consent manager tests below would attempt real UMP calls.
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

  // -------------------------------------------------------------------------
  // isPrivacyOptionsRequired — short-circuits when adsEnabled=false
  // -------------------------------------------------------------------------

  test(
    'ConsentManager.isPrivacyOptionsRequired returns false immediately '
    'when adsEnabled=false',
    () async {
      // adsEnabled=false in test builds (asserted above).
      // If this called ConsentInformation.getPrivacyOptionsRequirementStatus it
      // would throw MissingPluginException on the host runner.
      final result = await ConsentManager.isPrivacyOptionsRequired();
      expect(result, isFalse,
          reason: 'Must return false without a platform channel call when '
              'adsEnabled=false');
    },
  );

  // -------------------------------------------------------------------------
  // showPrivacyOptions — short-circuits when adsEnabled=false
  // -------------------------------------------------------------------------

  test(
    'ConsentManager.showPrivacyOptions completes immediately when adsEnabled=false',
    () async {
      // adsEnabled=false in test builds.
      // If this called ConsentForm.showPrivacyOptionsForm it would throw
      // MissingPluginException on the host runner.
      await expectLater(
        ConsentManager.showPrivacyOptions(),
        completes,
        reason: 'showPrivacyOptions must short-circuit when adsEnabled=false',
      );
    },
  );
}
