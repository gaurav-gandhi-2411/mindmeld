# Play Console Data Safety — Mindmeld

> **Draft — verify against each SDK's official Play data-safety disclosure doc before
> submitting; flags below mark the uncertain rows.**
>
> Reference links for verification:
> - AdMob: https://support.google.com/admob/answer/9999955 (AdMob data safety guidance)
> - Firebase Analytics: https://firebase.google.com/support/privacy#data_safety_for_android
> - Firebase Crashlytics: https://firebase.google.com/support/privacy#data_safety_for_android
> - RevenueCat: https://www.revenuecat.com/privacy (check their "Data Safety for Android" help page)
> - UMP SDK: https://support.google.com/admob/answer/10114209

---

## Section 1 — Data Collection and Security

### Does your app collect or share any of the required user data types?

**Yes.**

### Is all of the user data collected by your app encrypted in transit?

**Yes.** All four integrations communicate exclusively over HTTPS:
- AdMob/UMP: Google's ad network infrastructure (HTTPS enforced by SDK).
- Firebase Analytics: `https://firebase.googleapis.com` endpoints.
- Firebase Crashlytics: `https://firebase.googleapis.com` endpoints.
- RevenueCat: `https://api.revenuecat.com` (verified in purchases_flutter SDK source).

### Do you provide a way for users to request that their data is deleted?

**Partially — this requires a product decision before submission.**

Situation as built:
- **Local device data** (guess history, streaks, analytics ring buffer in SQLite):
  uninstalling the app deletes all of it. No server-side copy exists.
- **Firebase Analytics / Crashlytics:** Google retains pseudonymous event and crash
  data for up to 14 months. Users can reset their Firebase app-instance ID by
  clearing app data or reinstalling, which orphans prior data from any new events.
  Google provides no per-user deletion API for Analytics data because it is not
  linked to an identity — only aggregate/pseudonymous retention applies.
- **AdMob advertising ID:** Users can reset or opt out of ad personalization via
  Android Settings → Google → Ads. This does not delete historical ad logs held
  by Google.
- **RevenueCat:** Purchase records are retained for dispute and restoration
  purposes. RevenueCat does offer a customer deletion API (DELETE
  `/v1/subscribers/{app_user_id}`), but our app generates an anonymous RC app-user
  ID on first launch — there is no UI to expose this ID to the user or to send a
  deletion request on their behalf.

⚠ UNCERTAIN: **Product decision needed.** Play requires a deletion mechanism or a
clear disclosure that deletion is not possible. The defensible current answer is:
"Users can contact the developer at [email] to request deletion; upon receipt we
will call RevenueCat's delete API for their anonymous ID (if they can identify it
via a purchase receipt) and request Firebase data deletion via the Firebase console
for the relevant app-instance ID." This requires a support email to be live before
submission. Verify Play's current minimum requirement at:
https://support.google.com/googleplay/android-developer/answer/10787469

---

## Section 2 — Data Types Collected and Shared

Play Console Data Safety organizes collected data into categories. Each row below
maps our actual SDK behavior (as verified in source code) to Play's taxonomy.

---

### 2.1 Location

#### Approximate location

| Field | Answer |
|---|---|
| Collected? | ⚠ UNCERTAIN (see below) |
| Shared? | ⚠ UNCERTAIN (see below) |
| Processed ephemerally? | No |
| Required or optional? | N/A — not a user-facing feature |
| Purpose(s) | Advertising / Analytics |

⚠ UNCERTAIN: **AdMob derives approximate location from IP address for ad
targeting.** Google's infrastructure does this server-side; the app never calls
`LocationManager` or requests the `ACCESS_COARSE_LOCATION` permission. Whether
Play requires you to declare "Approximate location" because AdMob uses IP-derived
geolocation is not definitively answered by the general Play policy text — AdMob's
own data-safety guidance page (link above) states the answer for their specific
SDK. Verify that page before declaring Yes or No here. Firebase Analytics also
derives coarse country/region from IP (documented in Firebase privacy FAQ — same
verification applies).

---

### 2.2 Personal info

No name, email address, phone number, precise address, or any contact information
is collected by the app or any integrated SDK in our configuration.

---

### 2.3 Financial info

#### Purchase history

| Field | Answer |
|---|---|
| Collected? | Yes |
| Shared? | Yes — shared with RevenueCat as a data processor |
| Processed ephemerally? | No |
| Required or optional? | Required (only collected when user initiates a purchase) |
| Purpose(s) | App functionality (purchase validation, entitlement management, purchase restoration) |

**What is collected:** Google Play purchase tokens and transaction IDs are sent to
RevenueCat's API to verify and track active entitlements (Remove Ads, Archive
Access, Streak Freeze packs). RevenueCat also assigns an anonymous app-user ID on
first launch. No payment card details are accessible to the app — those remain
within the Google Play Store.

**Source in code:** `app/lib/iap/revenuecat_gateway.dart` —
`_LiveRcClient.purchase()` calls `Purchases.purchase()` which sends the Play
purchase token to RevenueCat servers. `getCustomerInfo()` and `restore()` also
contact RevenueCat.

⚠ UNCERTAIN: Play's taxonomy places "Purchase history" under "Financial info."
Verify that RevenueCat's Play data-safety disclosure doc (check their help center)
instructs developers to declare this under Financial info → Purchase history rather
than App activity → In-app purchase history. The distinction affects which Play
category you tick.

---

### 2.4 App activity

#### App interactions

| Field | Answer |
|---|---|
| Collected? | Yes |
| Shared? | No — processed by Google (Firebase) as a data processor; not sold or shared with third parties outside Google's infrastructure |
| Processed ephemerally? | No (events queue locally then flush to Firebase; Firebase retains for up to 14 months) |
| Required or optional? | Optional (analytics disabled when `ANALYTICS_ENABLED=false` at build time; enabled in production builds) |
| Purpose(s) | Analytics |

**Events collected (exact list from code and privacy policy):**

| Event name | Parameters sent | What is NOT sent |
|---|---|---|
| `guess_made` | temperature band (string), guess count (int), `lang`, `day` | The guess word itself |
| `hint_used` | hint index (int), hint rank (int), `lang`, `day` | The hint word itself |
| `win` | `lang`, `day` | Secret word |
| `ad_watched` | `fallback` (bool→int), `lang`, `day` | — |
| `share_tapped` | `lang`, `day` | — |
| `purchase` | product name (string), active entitlement IDs (list→string), `lang`, `day` | Transaction ID, price |

**Source in code:** `app/lib/analytics/firebase_exporter.dart` — events always
write to local SQLite ring buffer first (`AppPersistence.logEvent`); when
`analyticsEnabled=true`, `FirebaseExporter._flush()` drains unflushed events to
`FirebaseAnalytics.instance.logEvent`. The `_normaliseParams` method strips booleans
and complex types to String/num before transmission.

#### In-app search history / Other user-generated content

Not collected. The guess text typed by the user is validated locally against the
vocabulary and never transmitted anywhere (confirmed: no field in any event payload
carries raw guess text).

---

### 2.5 App info and performance

#### Crash logs

| Field | Answer |
|---|---|
| Collected? | Yes |
| Shared? | No — processed by Google (Firebase Crashlytics) as a data processor |
| Processed ephemerally? | No |
| Required or optional? | Optional (only active when `ANALYTICS_ENABLED=true`) |
| Purpose(s) | App functionality (crash diagnosis and fix); Analytics |

**What is collected:** Flutter error objects and stack traces (code-level, no user
content), device model, OS version, app version, and a randomly generated
Crashlytics installation ID. No gameplay state (guesses, streaks, hints) is
attached to crash reports.

**Source in code:** `app/lib/analytics/firebase_exporter.dart` —
`FirebaseExporter.recordError()` calls `FirebaseCrashlytics.instance.recordError()`.
When `analyticsEnabled=false`, `_NoOpExporter.recordError()` is a no-op.

#### Diagnostics

| Field | Answer |
|---|---|
| Collected? | Yes (via Crashlytics — device model, OS version, app version) |
| Shared? | No |
| Processed ephemerally? | No |
| Required or optional? | Optional |
| Purpose(s) | App functionality |

---

### 2.6 Device or other identifiers

#### Device or other IDs (Advertising ID — GAID)

| Field | Answer |
|---|---|
| Collected? | Yes — Google Mobile Ads SDK reads the GAID to serve and frequency-cap rewarded ads |
| Shared? | Yes — shared with Google ad network partners for ad delivery and measurement |
| Processed ephemerally? | No |
| Required or optional? | Required for rewarded ad functionality; the app degrades gracefully if the user has opted out of ad personalization in Android Settings |
| Purpose(s) | Advertising / Marketing |

**Source in code:** `app/lib/ads/rewarded_ad_service.dart` —
`defaultAdLoader()` calls `RewardedAd.load()` with an `AdRequest()` (no custom
targeting parameters added by the app). The AdMob SDK handles GAID access
internally.

**UMP / Consent:** The UMP SDK shows a consent dialog in GDPR-applicable regions
(EEA/UK) before the first ad loads. If consent is denied or not required,
non-personalized ads are served; the GAID may still be read for frequency capping
depending on Google's non-personalized ad implementation.

⚠ UNCERTAIN: **Exact Play declaration for non-personalized ad path.** When a user
denies personalization consent, does the AdMob SDK still read and transmit the GAID
(for frequency capping, fraud prevention)? AdMob's data-safety guidance page
(https://support.google.com/admob/answer/9999955) documents the correct declaration
for this scenario. Verify before submitting — the answer affects whether "Advertising
ID" is Required or Optional, and whether "shared" applies in all cases or only with
consent.

⚠ UNCERTAIN: **Firebase app-instance ID.** Firebase Analytics assigns a
pseudonymous app-instance ID (not the GAID — it is Firebase-generated). Play's
taxonomy may require declaring this separately under "Device or other IDs" in
addition to the GAID. Verify against Firebase's Play data-safety guidance page
(link at top).

---

## Section 3 — Data Handling Practices

### Does your app share any of the collected data with third parties?

**Yes** — two third-party data processors receive data:

| Third party | Data shared | Basis |
|---|---|---|
| Google (AdMob/ad network partners) | Advertising ID (GAID), ad interaction signals | Ad delivery; ⚠ UNCERTAIN whether sharing with ad network partners beyond Google itself must be declared separately — verify AdMob guidance |
| RevenueCat | Anonymous app-user ID, Play purchase tokens, entitlement status | Purchase validation and restoration |

Firebase Analytics and Crashlytics are Google services acting as data processors
under Google's terms; data is not "shared" in Play's third-party sense but stays
within Google's infrastructure. Confirm this interpretation against Firebase's own
Play data-safety guidance.

---

## Summary of All ⚠ UNCERTAIN Flags

| # | Flag | Where to verify |
|---|---|---|
| 1 | Deletion mechanism: no account system means no clean per-user deletion UX; defensible path is a support-email contact flow + RevenueCat delete API. Play may require a more explicit in-app mechanism. | https://support.google.com/googleplay/android-developer/answer/10787469 |
| 2 | Approximate location: AdMob and Firebase both derive coarse location from IP server-side; unclear whether Play requires declaring "Approximate location" for IP-derived geolocation when the app requests no location permission. | AdMob: https://support.google.com/admob/answer/9999955; Firebase: https://firebase.google.com/support/privacy#data_safety_for_android |
| 3 | RevenueCat taxonomy: purchase tokens/entitlements may belong under "Financial info → Purchase history" or "App activity → In-app purchase history" — RevenueCat's own Play data-safety disclosure doc is the source of truth. | RevenueCat help center / their Play data-safety guidance article |
| 4 | GAID in non-personalized ad path: when UMP consent is denied, does the AdMob SDK still read/transmit the GAID? This affects whether Advertising ID is Required or Optional in the Play form. | https://support.google.com/admob/answer/9999955 |
| 5 | Firebase app-instance ID: pseudonymous Firebase-generated identifier; may require a separate "Device or other IDs" declaration distinct from the GAID. | https://firebase.google.com/support/privacy#data_safety_for_android |
| 6 | AdMob sharing scope: Play asks whether data is shared with third parties. AdMob passes signals to ad network partners beyond Google itself; the form may require naming those partners or checking a "third-party sharing" box. | https://support.google.com/admob/answer/9999955 |
