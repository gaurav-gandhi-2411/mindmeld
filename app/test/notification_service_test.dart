/// Unit tests for [NotificationService].
///
/// All tests run as pure host (dart vm) tests — zero Firebase SDK calls, zero
/// browser JS interop. [_FakeNotificationClient] is an in-memory stand-in for
/// the real firebase_messaging/cloud_firestore wrapper; the iOS-PWA check and
/// timezone lookup (normally web-only JS interop) are injected as plain
/// functions so their branches are exercisable on the VM — see
/// notification_service.dart's doc comment for why `kIsWeb` itself is never
/// checked inside the service.
///
/// [SocialService] is constructed with a `firebaseInitializer` override so
/// uid provisioning never touches the firebase_core platform channel either
/// (mirrors social_service_test.dart).
///
/// Coverage (mirrors spec-phase6b.md acceptance criteria):
///   1. Opt-in success path writes the correct Firestore-shaped fields.
///   2. Opt-in when permission previously denied never re-prompts.
///   3. Opt-out clears the remote + local fields.
///   4. iOS-not-installed path returns the right result without ever
///      touching [NotificationClient.getToken].
///   5. Every method degrades gracefully (never throws) on client throw.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/notifications/notification_client.dart';
import 'package:mindmeld/notifications/notification_service.dart';
import 'package:mindmeld/social/social_client.dart';
import 'package:mindmeld/social/social_models.dart';
import 'package:mindmeld/social/social_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

// ---------------------------------------------------------------------------
// _FakeSocialClient — minimal stand-in, only what SocialService.ensureSignedIn
// touches (mirrors the fixture in social_service_test.dart).
// ---------------------------------------------------------------------------

class _FakeSocialClient implements SocialClient {
  _FakeSocialClient({this.signInThrows = false});

  final bool signInThrows;
  String? _currentUid;

  @override
  String? get currentUid => _currentUid;

  @override
  Future<String> signInAnonymously() async {
    if (signInThrows) throw StateError('signIn failed');
    _currentUid ??= 'uid0';
    return _currentUid!;
  }

  @override
  Future<void> setDisplayName({required String uid, required String displayName}) async {}

  @override
  Future<String?> getDisplayName(String uid) async => null;

  @override
  Future<SocialGroup> createGroup({required String uid, required String name}) {
    throw UnimplementedError();
  }

  @override
  Future<String?> resolveCode(String code) async => null;

  @override
  Future<SocialGroup?> getGroup(String groupId) async => null;

  @override
  Future<List<SocialGroup>> myGroups(String uid) async => [];

  @override
  Future<void> joinGroup({required String groupId, required String uid}) async {}

  @override
  Future<void> writeResult({
    required String groupId,
    required String date,
    required String uid,
    required String displayName,
    required String outcome,
    required int guessesUsed,
    required int par,
    required int scoreVsPar,
    required String lang,
  }) async {}

  @override
  Future<Map<String, LeaderboardEntry>> fetchResults({
    required String groupId,
    required String date,
  }) async =>
      {};

  @override
  Future<void> deleteOwnProfile(String uid) async {}

  @override
  Future<void> removeSelfFromGroup({required String groupId, required String uid}) async {}

  @override
  Future<void> deleteOwnResultsBestEffort(String uid) async {}
}

// ---------------------------------------------------------------------------
// _FakeNotificationClient
// ---------------------------------------------------------------------------

class _FakeNotificationClient implements NotificationClient {
  _FakeNotificationClient({
    this.permission = NotifPermission.notDetermined,
    this.requestPermissionResult = NotifPermission.granted,
    this.token = 'fake-token',
    this.getTokenThrows = false,
    this.writeThrows = false,
  });

  NotifPermission permission;
  NotifPermission requestPermissionResult;
  String? token;
  bool getTokenThrows;
  bool writeThrows;

  int requestPermissionCalls = 0;
  int getTokenCalls = 0;
  int writeOptInCalls = 0;
  int writeOptOutCalls = 0;

  // Captured args from the last writeOptIn call, for field-shape assertions.
  String? lastUid;
  String? lastFcmToken;
  String? lastNotifLang;
  String? lastTimezone;

  @override
  Future<NotifPermission> currentPermission() async => permission;

  @override
  Future<NotifPermission> requestPermission() async {
    requestPermissionCalls++;
    permission = requestPermissionResult;
    return requestPermissionResult;
  }

  @override
  Future<String?> getToken(String vapidKey) async {
    getTokenCalls++;
    if (getTokenThrows) throw StateError('getToken failed');
    return token;
  }

  @override
  Future<void> writeOptIn({
    required String uid,
    required String fcmToken,
    required String notifLang,
    String? timezone,
  }) async {
    writeOptInCalls++;
    if (writeThrows) throw StateError('writeOptIn failed');
    lastUid = uid;
    lastFcmToken = fcmToken;
    lastNotifLang = notifLang;
    lastTimezone = timezone;
  }

  @override
  Future<void> writeOptOut({required String uid}) async {
    writeOptOutCalls++;
    if (writeThrows) throw StateError('writeOptOut failed');
    lastUid = uid;
    lastFcmToken = null;
    lastNotifLang = null;
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  NotificationService buildService({
    _FakeNotificationClient? client,
    _FakeSocialClient? socialClient,
    bool iosNotInstalled = false,
    String? timezone = 'Asia/Kolkata',
    String vapidKey = 'real-vapid-key',
  }) {
    final social = SocialService(
      client: socialClient ?? _FakeSocialClient(),
      firebaseInitializer: () async => true,
    );
    return NotificationService(
      client: client ?? _FakeNotificationClient(),
      socialService: social,
      iosNotInstalledCheck: () => iosNotInstalled,
      timezoneProvider: () => timezone,
      vapidKey: vapidKey,
    );
  }

  group('opt-in success path', () {
    test('writes fcmToken, notifLang, and timezone via writeOptIn', () async {
      final client = _FakeNotificationClient();
      final service = buildService(client: client);

      final result = await service.optIn(lang: 'en');

      expect(result, OptInResult.success);
      expect(client.writeOptInCalls, 1);
      expect(client.lastFcmToken, 'fake-token');
      expect(client.lastNotifLang, 'en');
      expect(client.lastTimezone, 'Asia/Kolkata');
      expect(client.lastUid, isNotNull);
      expect(await service.isSubscribedLocally(), isTrue);
      expect(await service.subscribedLang(), 'en');
    });

    test('placeholder VAPID key skips getToken entirely', () async {
      final client = _FakeNotificationClient();
      final service = buildService(client: client, vapidKey: 'PLACEHOLDER');

      final result = await service.optIn(lang: 'en');

      expect(result, OptInResult.offlineOrError);
      expect(client.getTokenCalls, 0);
      expect(client.writeOptInCalls, 0);
    });

    test('a null token (unsupported browser) degrades to offlineOrError without writing', () async {
      final client = _FakeNotificationClient(token: null);
      final service = buildService(client: client);

      final result = await service.optIn(lang: 'en');

      expect(result, OptInResult.offlineOrError);
      expect(client.getTokenCalls, 1);
      expect(client.writeOptInCalls, 0);
    });
  });

  group('permission denial — never re-prompt', () {
    test('optIn returns permissionDenied without calling requestPermission '
        'when already denied at the browser level', () async {
      final client = _FakeNotificationClient(permission: NotifPermission.denied);
      final service = buildService(client: client);

      final result = await service.optIn(lang: 'en');

      expect(result, OptInResult.permissionDenied);
      expect(client.requestPermissionCalls, 0); // never re-prompted
      expect(client.getTokenCalls, 0);
    });

    test('optIn returns permissionDenied when the browser prompt is declined '
        'just now', () async {
      final client = _FakeNotificationClient(
        permission: NotifPermission.notDetermined,
        requestPermissionResult: NotifPermission.denied,
      );
      final service = buildService(client: client);

      final result = await service.optIn(lang: 'en');

      expect(result, OptInResult.permissionDenied);
      expect(client.requestPermissionCalls, 1);
      expect(client.getTokenCalls, 0);
    });
  });

  group('opt-out', () {
    test('clears remote fields (writeOptOut) and local cache', () async {
      final client = _FakeNotificationClient();
      final service = buildService(client: client);

      await service.optIn(lang: 'hi-en'); // establish subscribed state first
      expect(await service.isSubscribedLocally(), isTrue);

      await service.optOut();

      expect(client.writeOptOutCalls, 1);
      expect(client.lastFcmToken, isNull);
      expect(client.lastNotifLang, isNull);
      expect(await service.isSubscribedLocally(), isFalse);
      expect(await service.subscribedLang(), isNull);
    });

    test('optOut never throws even if the remote write fails, and still '
        'clears local state', () async {
      final client = _FakeNotificationClient(writeThrows: true);
      final service = buildService(client: client);

      await expectLater(service.optOut(), completes);
      expect(await service.isSubscribedLocally(), isFalse);
    });
  });

  group('iOS not installed', () {
    test('returns iosNotInstalled without ever calling getToken', () async {
      final client = _FakeNotificationClient();
      final service = buildService(client: client, iosNotInstalled: true);

      final result = await service.optIn(lang: 'en');

      expect(result, OptInResult.iosNotInstalled);
      expect(client.getTokenCalls, 0);
      expect(client.writeOptInCalls, 0);
      expect(client.requestPermissionCalls, 0);
    });

    test('iosNotInstalled getter reflects the injected check', () {
      final service = buildService(iosNotInstalled: true);
      expect(service.iosNotInstalled, isTrue);
    });
  });

  group('graceful degradation — never throws', () {
    test('currentPermission() returns notDetermined if the client throws', () async {
      final service = NotificationService(
        client: _ThrowingNotificationClient(),
        socialService: SocialService(
          client: _FakeSocialClient(),
          firebaseInitializer: () async => true,
        ),
      );
      expect(await service.currentPermission(), NotifPermission.notDetermined);
    });

    test('optIn() returns offlineOrError (never throws) if ensureSignedIn fails', () async {
      final client = _FakeNotificationClient();
      final service = buildService(
        client: client,
        socialClient: _FakeSocialClient(signInThrows: true),
      );

      final result = await service.optIn(lang: 'en');

      expect(result, OptInResult.offlineOrError);
      expect(client.writeOptInCalls, 0);
    });

    test('optIn() returns offlineOrError (never throws) if getToken throws', () async {
      final client = _FakeNotificationClient(getTokenThrows: true);
      final service = buildService(client: client);

      final result = await service.optIn(lang: 'en');

      expect(result, OptInResult.offlineOrError);
      expect(client.writeOptInCalls, 0);
    });

    test('optIn() returns offlineOrError (never throws) if writeOptIn throws', () async {
      final client = _FakeNotificationClient(writeThrows: true);
      final service = buildService(client: client);

      final result = await service.optIn(lang: 'en');

      expect(result, OptInResult.offlineOrError);
      // Local cache must not be set on a failed remote write.
      expect(await service.isSubscribedLocally(), isFalse);
    });
  });

  group('Firebase readiness gate (regression — live 2026-07-07)', () {
    // Root cause #1 (JS-interop TypeError): main.dart's IndexedStack mounts
    // SettingsScreen eagerly on EVERY cold page load (not lazily on
    // tab-select), and SettingsScreen calls currentPermission() from
    // initState. With no readiness gate at all, the underlying
    // FirebaseMessaging.instance.getNotificationSettings() call threw a
    // JS-interop TypeError on a real browser whenever nothing had touched
    // Firebase yet this session — i.e. on literally every fresh visit. It
    // degraded gracefully (never crashed), but permission status could
    // never be read correctly.
    //
    // Root cause #2 (worse, caught only by the live cold-profile harness —
    // no widget test mounts the full IndexedStack app shell): the FIRST fix
    // attempt made currentPermission() call SocialService.ensureFirebaseReady(),
    // which DOES trigger a real Firebase.initializeApp() if not already
    // ready. Since this method is reachable from initState of an eagerly-
    // mounted screen, that silently provisioned Firebase for EVERY visitor
    // immediately after onboarding — regardless of whether they ever touched
    // Social or Notifications — defeating the entire point of lazy init.
    //
    // Final fix: SocialService.isFirebaseReadyLocally (zero network, never
    // triggers init — same pattern as hasLocalIdentity). currentPermission()
    // must NEVER call the real firebaseInitializer itself; it may only read
    // whatever readiness state some OTHER explicit action already produced.
    test('currentPermission() never triggers Firebase init when nothing has '
        'touched Firebase yet', () async {
      var initCalls = 0;
      final socialClient = _FakeSocialClient();
      final social = SocialService(
        client: socialClient,
        firebaseInitializer: () async {
          initCalls++;
          return true;
        },
      );
      // Client would return granted if ever reached — proves the result came
      // from the gate short-circuiting, not from the client happening to agree.
      final client = _FakeNotificationClient(permission: NotifPermission.granted);
      final service = NotificationService(client: client, socialService: social);

      final result = await service.currentPermission();

      expect(result, NotifPermission.notDetermined);
      expect(initCalls, 0, reason: 'must never provision Firebase just to check status');
      expect(socialClient.currentUid, isNull);
    });

    test('currentPermission() correctly delegates to the client once Firebase '
        'was ALREADY made ready by a prior explicit action', () async {
      final social = SocialService(
        client: _FakeSocialClient(),
        firebaseInitializer: () async => true,
      );
      // A prior explicit action (e.g. an earlier optIn() or social action in
      // the same session) already provisioned Firebase on this instance.
      await social.ensureSignedIn();

      final client = _FakeNotificationClient(permission: NotifPermission.denied);
      final service = NotificationService(client: client, socialService: social);

      expect(await service.currentPermission(), NotifPermission.denied);
    });
  });
}

/// Client whose every method throws — used to assert [NotificationService]
/// never propagates an exception out of [currentPermission].
class _ThrowingNotificationClient implements NotificationClient {
  @override
  Future<NotifPermission> currentPermission() async => throw StateError('boom');

  @override
  Future<NotifPermission> requestPermission() async => throw StateError('boom');

  @override
  Future<String?> getToken(String vapidKey) async => throw StateError('boom');

  @override
  Future<void> writeOptIn({
    required String uid,
    required String fcmToken,
    required String notifLang,
    String? timezone,
  }) async =>
      throw StateError('boom');

  @override
  Future<void> writeOptOut({required String uid}) async => throw StateError('boom');
}
