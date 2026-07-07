/// Thin wrapper around the firebase_messaging + cloud_firestore SDKs for the
/// 6b daily-notifications feature.
///
/// ## Architecture — thin client injection
///
/// Mirrors [SocialClient] (social_client.dart): [NotificationClient] is the
/// abstract interface the rest of the app depends on; [_LiveNotificationClient]
/// is the ONLY place firebase_messaging / cloud_firestore SDK calls live for
/// this feature; tests inject a fake that never touches a platform channel.
///
/// ## Topic subscription is server-side only
///
/// [FirebaseMessaging.subscribeToTopic] / [unsubscribeFromTopic] throw
/// `UnimplementedError` on Flutter web (a permanent limitation of
/// firebase_messaging_web) — this file MUST NEVER call either method. Instead,
/// [writeOptIn] / [writeOptOut] set `notifPendingAction` on the user's profile
/// doc; a separate GitHub Actions cron job performs the actual server-side
/// topic (un)subscription via the Admin SDK. See spec-phase6b.md.
///
/// Firebase app initialisation is NOT this file's responsibility — callers
/// (see notification_service.dart) must ensure `Firebase.initializeApp()` has
/// run before constructing [_LiveNotificationClient]. In practice this is
/// guaranteed by routing all uid provisioning through [SocialService.ensureSignedIn].
library;

import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_messaging/firebase_messaging.dart';

/// App-level notification permission status.
///
/// Mirrors [AuthorizationStatus] from firebase_messaging without leaking that
/// type into [NotificationService]'s public API — same pattern as how
/// [SocialClient] hides Firestore/Auth types behind [SocialGroup] /
/// [LeaderboardEntry].
enum NotifPermission {
  /// Notifications may be shown (covers both `authorized` and `provisional`
  /// upstream statuses — provisional is iOS-only and behaves as granted for
  /// our purposes since no user-facing distinction is needed this phase).
  granted,

  /// Notifications are blocked at the browser/OS level. Permanent until the
  /// user changes it in their browser/OS settings — never re-prompt.
  denied,

  /// The user has never been asked.
  notDetermined,
}

/// Abstract interface for the Firebase Messaging + Firestore operations 6b
/// needs.
///
/// Tests inject a fake; production supplies [defaultNotificationClient].
abstract class NotificationClient {
  /// Current permission status — does not prompt the user.
  Future<NotifPermission> currentPermission();

  /// Prompts the browser/OS permission dialog. Callers must only invoke this
  /// after an explicit in-app "yes" (never on app boot) — see
  /// [NotificationService.optIn].
  Future<NotifPermission> requestPermission();

  /// FCM registration token for [vapidKey], or null on any failure
  /// (unsupported browser, JS exception, user never granted permission).
  Future<String?> getToken(String vapidKey);

  /// Write the opt-in fields to `users/{uid}` (merge). Sets
  /// `notifPendingAction: 'subscribe'` so the server-side cron job performs
  /// the actual topic subscription. Always stamps `notifUpdatedAt` with
  /// [FieldValue.serverTimestamp] — the Firestore rules reject any other value.
  Future<void> writeOptIn({
    required String uid,
    required String fcmToken,
    required String notifLang,
    String? timezone,
  });

  /// Write the opt-out fields to `users/{uid}` (merge). Sets
  /// `notifPendingAction: 'unsubscribe'`, clears `fcmToken`/`notifLang`, and
  /// leaves `timezone` untouched (still useful for a future re-opt-in).
  Future<void> writeOptOut({required String uid});
}

/// Production [NotificationClient] backed by real Firebase SDKs.
///
/// This is the ONLY place in the codebase that calls [FirebaseMessaging] or
/// [FirebaseFirestore] methods for the notifications feature. Tests never
/// instantiate this class.
class _LiveNotificationClient implements NotificationClient {
  FirebaseMessaging get _messaging => FirebaseMessaging.instance;
  FirebaseFirestore get _db => FirebaseFirestore.instance;

  static NotifPermission _mapStatus(AuthorizationStatus status) {
    switch (status) {
      case AuthorizationStatus.authorized:
      case AuthorizationStatus.provisional:
        return NotifPermission.granted;
      case AuthorizationStatus.denied:
        return NotifPermission.denied;
      case AuthorizationStatus.notDetermined:
        return NotifPermission.notDetermined;
    }
  }

  @override
  Future<NotifPermission> currentPermission() async {
    final settings = await _messaging.getNotificationSettings();
    return _mapStatus(settings.authorizationStatus);
  }

  @override
  Future<NotifPermission> requestPermission() async {
    final settings = await _messaging.requestPermission();
    return _mapStatus(settings.authorizationStatus);
  }

  @override
  Future<String?> getToken(String vapidKey) {
    return _messaging.getToken(vapidKey: vapidKey);
  }

  @override
  Future<void> writeOptIn({
    required String uid,
    required String fcmToken,
    required String notifLang,
    String? timezone,
  }) async {
    await _db.collection('users').doc(uid).set({
      'fcmToken': fcmToken,
      'notifLang': notifLang,
      'timezone': ?timezone,
      'notifPendingAction': 'subscribe',
      'notifUpdatedAt': FieldValue.serverTimestamp(),
    }, SetOptions(merge: true));
  }

  @override
  Future<void> writeOptOut({required String uid}) async {
    await _db.collection('users').doc(uid).set({
      'fcmToken': null,
      'notifLang': null,
      'notifPendingAction': 'unsubscribe',
      'notifUpdatedAt': FieldValue.serverTimestamp(),
    }, SetOptions(merge: true));
  }
}

/// Production [NotificationClient] singleton.
///
/// Callers must ensure `Firebase.initializeApp()` has already run before
/// touching this (guaranteed by [NotificationService] routing uid
/// provisioning through [SocialService.ensureSignedIn]).
final NotificationClient defaultNotificationClient = _LiveNotificationClient();
