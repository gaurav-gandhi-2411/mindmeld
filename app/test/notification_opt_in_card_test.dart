/// Widget + unit tests for [NotificationOptInCard] and
/// [shouldShowNotificationOptInCard] (win/loss-screen contextual opt-in ask).
///
/// Coverage (mirrors spec-phase6b.md "Permission UX" + acceptance criteria):
///   1. [shouldShowNotificationOptInCard] gating: web-only, not already
///      granted/denied, and suppressed after one dismissal ("never nag").
///   2. The card renders its copy and both action buttons.
///   3. Tapping "Not now" fires the dismissed analytics event and calls
///      [NotificationOptInCard.onDismissed].
///   4. Tapping "Yes, remind me" on a successful opt-in fires the granted
///      analytics event and calls [onDismissed].
///   5. A dismissal suppresses future [shouldShowNotificationOptInCard] calls.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/analytics/firebase_exporter.dart';
import 'package:mindmeld/features/notifications/notification_opt_in_card.dart';
import 'package:mindmeld/notifications/notification_client.dart';
import 'package:mindmeld/notifications/notification_service.dart';
import 'package:mindmeld/social/social_client.dart';
import 'package:mindmeld/social/social_models.dart';
import 'package:mindmeld/social/social_service.dart';
import 'package:mindmeld/stubs/analytics_stub.dart';
import 'package:shared_preferences/shared_preferences.dart';

// ---------------------------------------------------------------------------
// Fakes
// ---------------------------------------------------------------------------

/// Minimal [SocialClient] stand-in — only signInAnonymously is reachable via
/// [NotificationService.optIn]'s [SocialService.ensureSignedIn] call.
class _FakeSocialClient implements SocialClient {
  String? _uid;

  @override
  String? get currentUid => _uid;

  @override
  Future<String> signInAnonymously() async => _uid ??= 'uid0';

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

/// Configurable [NotificationClient] for widget tests.
class _FakeNotificationClient implements NotificationClient {
  _FakeNotificationClient({this.permission = NotifPermission.notDetermined});

  NotifPermission permission;

  @override
  Future<NotifPermission> currentPermission() async => permission;

  @override
  Future<NotifPermission> requestPermission() async {
    permission = NotifPermission.granted;
    return permission;
  }

  @override
  Future<String?> getToken(String vapidKey) async => 'fake-token';

  @override
  Future<void> writeOptIn({
    required String uid,
    required String fcmToken,
    required String notifLang,
    String? timezone,
  }) async {}

  @override
  Future<void> writeOptOut({required String uid}) async {}
}

/// Records every logged event without touching AppPersistence/SQLite.
class _FakeExporter implements AnalyticsExporter {
  final List<(String, Map<String, dynamic>?)> events = [];

  @override
  Future<void> logEvent(String name, [Map<String, dynamic>? props]) async {
    events.add((name, props));
  }

  @override
  Future<void> recordError(Object error, StackTrace? stack, {bool fatal = false}) async {}

  @override
  Future<void> init() async {}

  @override
  Future<void> onResume() async {}
}

NotificationService _buildService({NotifPermission permission = NotifPermission.notDetermined}) {
  return NotificationService(
    client: _FakeNotificationClient(permission: permission),
    socialService: SocialService(
      client: _FakeSocialClient(),
      firebaseInitializer: () async => true,
    ),
    iosNotInstalledCheck: () => false,
    timezoneProvider: () => null,
    vapidKey: 'real-vapid-key',
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  group('shouldShowNotificationOptInCard gating', () {
    test('false when not web (isWeb: false)', () async {
      final show = await shouldShowNotificationOptInCard(
        service: _buildService(),
        isWeb: false,
      );
      expect(show, isFalse);
    });

    test('true on web when permission is notDetermined and never dismissed', () async {
      final show = await shouldShowNotificationOptInCard(
        service: _buildService(permission: NotifPermission.notDetermined),
        isWeb: true,
      );
      expect(show, isTrue);
    });

    test('false when permission already granted', () async {
      // NotificationService.currentPermission() deliberately never forces
      // Firebase to initialise itself (see its doc comment — that was a real
      // live regression: main.dart's IndexedStack mounts the win/loss card
      // eagerly, so a forcing check would silently provision Firebase for
      // every visitor). It can only see a real granted/denied value once
      // Firebase was ALREADY made ready by some other explicit action —
      // simulated here via ensureSignedIn(), mirroring how a real session
      // would have Firebase ready by the time a SECOND win/loss screen shows
      // the card (e.g. after a first successful opt-in attempt).
      final social = SocialService(client: _FakeSocialClient(), firebaseInitializer: () async => true);
      await social.ensureSignedIn();
      final service = NotificationService(
        client: _FakeNotificationClient(permission: NotifPermission.granted),
        socialService: social,
        iosNotInstalledCheck: () => false,
        timezoneProvider: () => null,
        vapidKey: 'real-vapid-key',
      );

      final show = await shouldShowNotificationOptInCard(service: service, isWeb: true);
      expect(show, isFalse);
    });

    test('false when permission already denied', () async {
      final social = SocialService(client: _FakeSocialClient(), firebaseInitializer: () async => true);
      await social.ensureSignedIn();
      final service = NotificationService(
        client: _FakeNotificationClient(permission: NotifPermission.denied),
        socialService: social,
        iosNotInstalledCheck: () => false,
        timezoneProvider: () => null,
        vapidKey: 'real-vapid-key',
      );

      final show = await shouldShowNotificationOptInCard(service: service, isWeb: true);
      expect(show, isFalse);
    });

    test('false after a prior dismissal (never nag)', () async {
      SharedPreferences.setMockInitialValues({'notif_win_card_dismissed': true});
      final show = await shouldShowNotificationOptInCard(
        service: _buildService(),
        isWeb: true,
      );
      expect(show, isFalse);
    });
  });

  group('NotificationOptInCard widget', () {
    testWidgets('renders the ask copy and both buttons', (tester) async {
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: NotificationOptInCard(
            lang: 'en',
            notificationService: _buildService(),
            exporter: _FakeExporter(),
          ),
        ),
      ));

      expect(find.textContaining("reminder when tomorrow's Warmer"), findsOneWidget);
      expect(find.text('Not now'), findsOneWidget);
      expect(find.text('Yes, remind me'), findsOneWidget);
    });

    testWidgets('"Not now" sets the dismissed flag, logs analytics, calls onDismissed',
        (tester) async {
      final exporter = _FakeExporter();
      var dismissed = false;

      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: NotificationOptInCard(
            lang: 'en',
            notificationService: _buildService(),
            exporter: exporter,
            onDismissed: () => dismissed = true,
          ),
        ),
      ));

      await tester.tap(find.text('Not now'));
      await tester.pumpAndSettle();

      expect(dismissed, isTrue);
      expect(exporter.events.map((e) => e.$1), contains(AnalyticsEvent.notificationOptInDismissed));

      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getBool('notif_win_card_dismissed'), isTrue);

      // Dismissal must suppress future shows (never nag).
      final show = await shouldShowNotificationOptInCard(service: _buildService(), isWeb: true);
      expect(show, isFalse);
    });

    testWidgets('"Yes, remind me" on success logs the granted event and calls onDismissed',
        (tester) async {
      final exporter = _FakeExporter();
      var dismissed = false;

      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: NotificationOptInCard(
            lang: 'en',
            notificationService: _buildService(),
            exporter: exporter,
            onDismissed: () => dismissed = true,
          ),
        ),
      ));

      await tester.tap(find.text('Yes, remind me'));
      await tester.pumpAndSettle();

      expect(dismissed, isTrue);
      expect(
        exporter.events.map((e) => e.$1),
        contains(AnalyticsEvent.notificationPermissionGranted),
      );
      // A confirmation snackbar must appear.
      expect(find.byType(SnackBar), findsOneWidget);
    });

    testWidgets('"Yes, remind me" on iOS-not-installed shows the Add-to-Home-Screen nudge, '
        'not a generic error, and never calls onDismissed', (tester) async {
      final service = NotificationService(
        client: _FakeNotificationClient(),
        socialService: SocialService(
          client: _FakeSocialClient(),
          firebaseInitializer: () async => true,
        ),
        iosNotInstalledCheck: () => true,
        vapidKey: 'real-vapid-key',
      );
      var dismissed = false;

      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: NotificationOptInCard(
            lang: 'en',
            notificationService: service,
            exporter: _FakeExporter(),
            onDismissed: () => dismissed = true,
          ),
        ),
      ));

      await tester.tap(find.text('Yes, remind me'));
      await tester.pumpAndSettle();

      expect(dismissed, isFalse); // stays visible — user may install and retry
      expect(find.textContaining('Add Warmer to your Home Screen'), findsOneWidget);
    });
  });
}
