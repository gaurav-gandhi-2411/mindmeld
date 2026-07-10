/// Unit tests for [shouldActivateAppCheck] / [ensureAppCheckActivated].
///
/// All tests run as pure host (dart vm) tests — zero Firebase SDK calls, zero
/// browser JS interop. `kIsWeb` is a compile-time constant that is always
/// false under the dart-vm test runner, so [ensureAppCheckActivated] itself
/// always no-ops at its very first guard in this environment; the guard
/// logic that actually decides whether to call `.activate()` is exercised
/// directly via the extracted pure predicate [shouldActivateAppCheck] (see
/// app_check_init.dart's doc comment for why it's split out this way).
///
/// Coverage:
///   1. Placeholder (empty) site key never activates, regardless of
///      Firebase readiness — mirrors [AppConfig.revenueCatApiKey]'s
///      empty-default gating pattern (see revenuecat_gateway_test.dart's
///      "empty API key" test).
///   2. Firebase not yet ready never activates, even with a real-looking key.
///   3. Only firebaseReady=true AND a non-empty site key activates.
///   4. [ensureAppCheckActivated] never throws and is a safe no-op on a
///      non-web test target before any Firebase app exists.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/analytics/app_check_init.dart';

void main() {
  group('shouldActivateAppCheck', () {
    test('false when site key is empty (placeholder default), even if '
        'Firebase is ready', () {
      expect(
        shouldActivateAppCheck(firebaseReady: true, siteKey: ''),
        isFalse,
      );
    });

    test('false when Firebase is not yet ready, even with a real-looking key', () {
      expect(
        shouldActivateAppCheck(firebaseReady: false, siteKey: '6Lc-real-site-key'),
        isFalse,
      );
    });

    test('false when neither Firebase is ready nor the site key is set', () {
      expect(
        shouldActivateAppCheck(firebaseReady: false, siteKey: ''),
        isFalse,
      );
    });

    test('true only when Firebase is ready AND the site key is non-empty', () {
      expect(
        shouldActivateAppCheck(firebaseReady: true, siteKey: '6Lc-real-site-key'),
        isTrue,
      );
    });
  });

  group('ensureAppCheckActivated', () {
    test('no-ops cleanly (never throws) with no Firebase app and the '
        'default placeholder site key', () async {
      await expectLater(ensureAppCheckActivated(), completes);
    });

    test('appCheckRecaptchaSiteKey defaults to empty (placeholder) with no '
        'dart-define supplied, matching AppConfig.revenueCatApiKey\'s pattern', () {
      expect(appCheckRecaptchaSiteKey, isEmpty);
    });
  });
}
