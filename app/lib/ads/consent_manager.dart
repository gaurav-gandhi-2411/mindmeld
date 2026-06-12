/// UMP (User Messaging Platform) consent flow.
///
/// [ConsentManager.gatherConsent] is the single entry point called from
/// [main] when [AppConfig.adsEnabled] is true.  When adsEnabled is false this
/// function is a no-op — zero UMP platform channel calls are made.
///
/// ## UMP API surface (google_mobile_ads 9.0.0)
///
/// The SDK exposes consent through two classes:
///
/// - [ConsentInformation] — query/update consent status.
///   Key methods:
///   `requestConsentInfoUpdate(params, onSuccess, onFailure)`
///   `canRequestAds() → Future<bool>`
///   `getPrivacyOptionsRequirementStatus() → Future<PrivacyOptionsRequirementStatus>`
///
/// - [ConsentForm] — show the consent form when required.
///   Key static methods:
///   `loadAndShowConsentFormIfRequired(onDismissed)` — initial consent flow.
///   `showPrivacyOptionsForm(onDismissed)` — reopen options form from Settings.
///   The first helper loads and shows a form only when the SDK determines the
///   user is in a region that requires consent (EEA / UK). It is a no-op for
///   users outside those regions, making it the recommended integration pattern.
///
/// After [gatherConsent] resolves, callers may load ads unconditionally:
/// the SDK internally gates personalised vs non-personalised ad serving based
/// on the consent state.
library;

import 'dart:async';

import 'package:google_mobile_ads/google_mobile_ads.dart';
import 'package:mindmeld/core/config.dart';

/// Manages UMP consent gathering before the first ad load.
class ConsentManager {
  const ConsentManager._();

  /// Request and (if necessary) display the UMP consent form.
  ///
  /// Short-circuits immediately when [AppConfig.adsEnabled] is false so zero
  /// UMP code executes in non-monetised builds.
  ///
  /// In monetised builds:
  ///   1. Calls [ConsentInformation.requestConsentInfoUpdate] to get the latest
  ///      consent status from Google's servers.
  ///   2. Calls [ConsentForm.loadAndShowConsentFormIfRequired] which shows a
  ///      consent form only when the SDK determines one is required (EEA/UK
  ///      users who have not yet consented).  For other regions it is a no-op.
  ///
  /// Failures (network errors, form load errors) are silently swallowed so a
  /// consent hiccup never prevents the app from starting.
  static Future<void> gatherConsent() async {
    if (!AppConfig.adsEnabledEffective) return;

    // Step 1: refresh consent status.
    final updateCompleter = Completer<void>();
    ConsentInformation.instance.requestConsentInfoUpdate(
      ConsentRequestParameters(),
      () => updateCompleter.complete(),
      (FormError error) {
        // Failure is non-fatal; proceed to form step regardless.
        updateCompleter.complete();
      },
    );
    await updateCompleter.future;

    // Step 2: show form if required (no-op outside EEA/UK).
    final formCompleter = Completer<void>();
    ConsentForm.loadAndShowConsentFormIfRequired(
      (FormError? formError) => formCompleter.complete(),
    );
    await formCompleter.future;
  }

  /// Returns whether the user's region requires a privacy options entry point.
  ///
  /// Uses [ConsentInformation.getPrivacyOptionsRequirementStatus] from the
  /// google_mobile_ads 9.0.0 UMP API.
  ///
  /// Returns `false` immediately when [AppConfig.adsEnabled] is false, so no
  /// platform channel call is made in non-monetised/test builds.
  static Future<bool> isPrivacyOptionsRequired() async {
    if (!AppConfig.adsEnabledEffective) return false;
    final status =
        await ConsentInformation.instance.getPrivacyOptionsRequirementStatus();
    return status == PrivacyOptionsRequirementStatus.required;
  }

  /// Presents the privacy options form to the user.
  ///
  /// Uses [ConsentForm.showPrivacyOptionsForm] from the google_mobile_ads 9.0.0
  /// UMP API. This allows the user to update their consent choices after the
  /// initial consent flow — e.g. via Settings → "Privacy options".
  ///
  /// Is a no-op when [AppConfig.adsEnabled] is false so no platform channel
  /// call is made in non-monetised/test builds. Errors are silently swallowed
  /// to keep the Settings screen stable.
  static Future<void> showPrivacyOptions() async {
    if (!AppConfig.adsEnabledEffective) return;
    final completer = Completer<void>();
    ConsentForm.showPrivacyOptionsForm(
      (FormError? formError) => completer.complete(),
    );
    await completer.future;
  }
}
