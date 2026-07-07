/// Orchestration layer for the 6b daily-notifications feature.
///
/// ## Degradation guarantee
///
/// Mirrors [SocialService] (social_service.dart): every public method here
/// catches its own failures (offline, misconfigured VAPID key, browser
/// permission races) and degrades gracefully — solo/social play must never
/// be blocked or crashed by a notifications-feature error. Firebase Messaging
/// / Firestore are touched ONLY when the player takes an explicit action
/// (opt in / opt out), never on app boot.
///
/// ## Reuse, don't duplicate, Firebase init
///
/// uid provisioning is delegated entirely to [SocialService.ensureSignedIn]
/// — this file never calls `Firebase.initializeApp()` or
/// `signInAnonymously()` directly. A player can opt into notifications
/// without ever having touched Social; [SocialService.ensureSignedIn] handles
/// that first-time-anonymous-identity case transparently either way.
///
/// ## Web-only this phase
///
/// Native push is explicitly out of scope (spec-phase6b.md) — that boundary
/// is enforced at the UI layer (the win/loss opt-in card and the Settings
/// toggle are both gated to `kIsWeb`), NOT inside this service. Gating here
/// too would make [optIn]'s success path unreachable in host/VM tests, since
/// `kIsWeb` is a compile-time constant that is always false off-web. The iOS
/// "not installed as a PWA" check and the timezone lookup are injected as
/// plain functions (default to the real conditional-imported helpers) for
/// the same testability reason — mirrors how [SocialService] takes an
/// injectable `firebaseInitializer`.
///
/// All logging in this file uses [debugPrint] — see social_service.dart's
/// doc comment for why (dart:developer's log() is a no-op in release web
/// builds).
library;

import 'package:flutter/foundation.dart' show debugPrint;
import 'package:shared_preferences/shared_preferences.dart';

import 'package:mindmeld/notifications/ios_pwa_check_stub.dart'
    // ignore: uri_does_not_exist
    if (dart.library.html) 'package:mindmeld/notifications/ios_pwa_check_web.dart';
import 'package:mindmeld/notifications/notification_client.dart';
import 'package:mindmeld/notifications/notification_web_config.dart';
import 'package:mindmeld/notifications/timezone_stub.dart'
    // ignore: uri_does_not_exist
    if (dart.library.html) 'package:mindmeld/notifications/timezone_web.dart';
import 'package:mindmeld/social/social_service.dart';

/// Hard ceiling on every individual Firebase Messaging/Firestore call made
/// from this service. Mirrors social_service.dart's `_kSocialOpTimeout` (same
/// value, separate constant — never import a private constant across files).
const Duration _kNotifOpTimeout = Duration(seconds: 20);

const String _kAskedOncePrefsKey = 'notif_asked_once';
const String _kGrantedPrefsKey = 'notif_granted';
const String _kLangPrefsKey = 'notif_lang';

/// Outcome of a [NotificationService.optIn] attempt.
enum OptInResult {
  /// Permission granted, token obtained, Firestore write succeeded.
  success,

  /// The browser/OS denied permission (just now, or previously — denial is
  /// permanent and is never re-prompted).
  permissionDenied,

  /// iOS Safari, not installed as a PWA — real push cannot work here. The UI
  /// should show the "Add to Home Screen first" nudge instead of a generic
  /// error.
  iosNotInstalled,

  /// Offline, misconfigured (placeholder VAPID key), or any other failure.
  offlineOrError,
}

/// High-level notification operations used by the UI layer.
///
/// Construct via [buildNotificationService] rather than directly.
class NotificationService {
  NotificationService({
    NotificationClient? client,
    SocialService? socialService,
    bool Function()? iosNotInstalledCheck,
    String? Function()? timezoneProvider,
    String? vapidKey,
  })  : _client = client ?? defaultNotificationClient,
        _socialService = socialService ?? buildSocialService(),
        _iosNotInstalledCheck = iosNotInstalledCheck ?? isIosPwaNotInstalled,
        _timezoneProvider = timezoneProvider ?? currentTimezone,
        _vapidKey = vapidKey ?? notificationVapidKey;

  final NotificationClient _client;
  final SocialService _socialService;
  final bool Function() _iosNotInstalledCheck;
  final String? Function() _timezoneProvider;
  final String _vapidKey;

  // ---------------------------------------------------------------------------
  // Permission status
  // ---------------------------------------------------------------------------

  /// Current permission status. Never prompts, never throws, and —
  /// critically — never itself provisions Firebase.
  ///
  /// Uses [SocialService.isFirebaseReadyLocally] (zero network, never
  /// triggers init), NOT [SocialService.ensureFirebaseReady]. This method is
  /// reachable on every cold page load (main.dart's `IndexedStack` mounts
  /// [SettingsScreen] eagerly, and the win/loss opt-in card calls this from
  /// `initState` on every win/loss) — an earlier version of this method
  /// called `ensureFirebaseReady()` here, which silently triggered a real
  /// `Firebase.initializeApp()` for every single visitor immediately after
  /// onboarding, regardless of whether they ever touched Social or
  /// Notifications. That defeated the entire point of lazy init (fast cold
  /// boot for solo-only players) and was caught live via the cold-profile
  /// harness, not a test — no widget test mounts the full app shell, so
  /// nothing exercised this path. The trade-off accepted here (same one
  /// [SocialService.hasLocalIdentity] already accepts): if NOTHING has
  /// touched Firebase yet this page session, this reports `notDetermined`
  /// even for a returning user who granted/denied in a PREVIOUS session —
  /// acceptable because `notDetermined` is exactly the value that correctly
  /// shows the opt-in card to a genuinely first-time visitor, and a
  /// browser that already decided will never re-prompt regardless of what
  /// this method reports (see [optIn]'s doc comment).
  Future<NotifPermission> currentPermission() async {
    try {
      if (!_socialService.isFirebaseReadyLocally) {
        return NotifPermission.notDetermined;
      }
      return await _client.currentPermission().timeout(_kNotifOpTimeout);
    } catch (e) {
      debugPrint('NotificationService: currentPermission FAILED: $e');
      return NotifPermission.notDetermined;
    }
  }

  /// True when the browser is iOS Safari and the app is not installed as a
  /// PWA — callers should show the "Add to Home Screen" nudge instead of the
  /// real opt-in flow. Always false on native (see [isIosPwaNotInstalled]'s
  /// stub).
  bool get iosNotInstalled => _iosNotInstalledCheck();

  // ---------------------------------------------------------------------------
  // Opt in / opt out
  // ---------------------------------------------------------------------------

  /// Full opt-in flow: ensure signed in -> request browser permission (only
  /// call site for the actual permission-prompting API — callers must only
  /// invoke this after an explicit in-app "yes") -> on grant: get an FCM
  /// token -> write it to Firestore with `notifPendingAction: 'subscribe'` ->
  /// cache locally.
  ///
  /// Never throws. Returns [OptInResult.iosNotInstalled] without touching
  /// [NotificationClient.getToken] at all when [iosNotInstalled] is true.
  Future<OptInResult> optIn({required String lang}) async {
    if (_iosNotInstalledCheck()) return OptInResult.iosNotInstalled;

    if (_vapidKey == 'PLACEHOLDER') {
      debugPrint('NotificationService: optIn skipped — VAPID key still PLACEHOLDER.');
      return OptInResult.offlineOrError;
    }

    try {
      // ensureSignedIn() FIRST (not after the denial check below) — this is
      // always safe here because optIn() is only ever reached from an
      // explicit user action (never called eagerly), unlike the public
      // currentPermission() method, which main.dart's IndexedStack DOES
      // reach eagerly (Settings, the win/loss card) and must never force
      // Firebase to initialise for that reason (see currentPermission's doc
      // comment). Signing in here first means the "honour a previous
      // browser-level denial" check right after can see the TRUE status
      // instead of a false notDetermined from Firebase never having been
      // touched this session — without this ordering, that check could never
      // actually skip requestPermission() on a session's first-ever
      // Firebase-touching action (still not a user-visible bug even then:
      // browsers never re-prompt a decided permission regardless — but this
      // ordering makes the "skip an unnecessary call" optimization work
      // correctly rather than silently never firing).
      final uid = await _socialService.ensureSignedIn();
      if (uid == null) return OptInResult.offlineOrError;

      // Honour a previous browser-level denial honestly — never re-prompt.
      final existing = await currentPermission();
      if (existing == NotifPermission.denied) {
        return OptInResult.permissionDenied;
      }

      debugPrint('NotificationService: [1/3] requestPermission() starting…');
      final permission = await _client.requestPermission().timeout(_kNotifOpTimeout);
      debugPrint('NotificationService: [1/3] requestPermission() done ($permission).');
      await _markAskedOnce();
      if (permission != NotifPermission.granted) {
        return OptInResult.permissionDenied;
      }

      debugPrint('NotificationService: [2/3] getToken() starting…');
      final token = await _client.getToken(_vapidKey).timeout(_kNotifOpTimeout);
      debugPrint('NotificationService: [2/3] getToken() done (token=${token != null}).');
      if (token == null) return OptInResult.offlineOrError;

      final timezone = _timezoneProvider();

      debugPrint('NotificationService: [3/3] writeOptIn() starting…');
      await _client
          .writeOptIn(uid: uid, fcmToken: token, notifLang: lang, timezone: timezone)
          .timeout(_kNotifOpTimeout);
      debugPrint('NotificationService: [3/3] writeOptIn() done.');

      await _cacheGranted(lang: lang);
      return OptInResult.success;
    } catch (e) {
      debugPrint('NotificationService: optIn FAILED: $e');
      return OptInResult.offlineOrError;
    }
  }

  /// Opt out: write `notifPendingAction: 'unsubscribe'` (+ clear
  /// `fcmToken`/`notifLang`) to Firestore, then clear the local cache. Never
  /// throws — a failed remote write still clears local state so the UI shows
  /// "off" (the cron job's next run is idempotent regardless).
  Future<void> optOut() async {
    try {
      final uid = await _socialService.ensureSignedIn();
      if (uid != null) {
        await _client.writeOptOut(uid: uid).timeout(_kNotifOpTimeout);
      }
    } catch (e) {
      debugPrint('NotificationService: optOut FAILED: $e');
    }
    await _clearLocalState();
  }

  // ---------------------------------------------------------------------------
  // Local cache (no network)
  // ---------------------------------------------------------------------------

  /// True once the in-app permission prompt has been triggered at least once
  /// (browser-level, not the in-app card dismissal — that's tracked
  /// separately by the win-screen card widget).
  Future<bool> hasBeenAskedOnce() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getBool(_kAskedOncePrefsKey) ?? false;
  }

  /// True if the last known opt-in succeeded (local cache only — the source
  /// of truth for whether the topic subscription actually landed is the
  /// server-side cron job, but this is enough for honest UI state).
  Future<bool> isSubscribedLocally() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getBool(_kGrantedPrefsKey) ?? false;
  }

  /// The language last subscribed to, or null if never subscribed.
  Future<String?> subscribedLang() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_kLangPrefsKey);
  }

  Future<void> _markAskedOnce() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_kAskedOncePrefsKey, true);
  }

  Future<void> _cacheGranted({required String lang}) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_kGrantedPrefsKey, true);
    await prefs.setString(_kLangPrefsKey, lang);
  }

  Future<void> _clearLocalState() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_kGrantedPrefsKey, false);
    await prefs.remove(_kLangPrefsKey);
  }
}

/// Construct the default [NotificationService]. The optional parameters
/// allow tests to inject fakes without touching Firebase or real browser
/// JS interop.
NotificationService buildNotificationService({
  NotificationClient? client,
  SocialService? socialService,
  bool Function()? iosNotInstalledCheck,
  String? Function()? timezoneProvider,
  String? vapidKey,
}) =>
    NotificationService(
      client: client,
      socialService: socialService,
      iosNotInstalledCheck: iosNotInstalledCheck,
      timezoneProvider: timezoneProvider,
      vapidKey: vapidKey,
    );
