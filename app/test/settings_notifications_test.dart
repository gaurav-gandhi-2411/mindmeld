/// Widget tests for the Notifications section added to [SettingsScreen]
/// (phase 6b). Mirrors settings_privacy_test.dart's harness style.
///
/// Coverage (mirrors spec-phase6b.md acceptance criteria):
///   1. Honest state text: "On"/"Off", "blocked in your browser settings"
///      (denied), "Add to Home Screen to enable notifications" (iOS not
///      installed).
///   2. Turning the toggle on when never-asked triggers [NotificationService.optIn].
///   3. Turning the toggle on when previously denied never re-prompts and
///      shows the honest blocked message.
///   4. Turning the toggle off calls [NotificationService.optOut].
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/features/settings/settings_screen.dart';
import 'package:mindmeld/notifications/notification_client.dart';
import 'package:mindmeld/notifications/notification_service.dart';
import 'package:mindmeld/social/social_client.dart';
import 'package:mindmeld/social/social_models.dart';
import 'package:mindmeld/social/social_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

// ---------------------------------------------------------------------------
// Fakes
// ---------------------------------------------------------------------------

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

class _FakeNotificationClient implements NotificationClient {
  _FakeNotificationClient({this.permission = NotifPermission.notDetermined});

  NotifPermission permission;
  int writeOptInCalls = 0;
  int writeOptOutCalls = 0;

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
  }) async {
    writeOptInCalls++;
  }

  @override
  Future<void> writeOptOut({required String uid}) async {
    writeOptOutCalls++;
  }
}

/// Builds a [NotificationService] with Firebase ALREADY made ready (via
/// [SocialService.ensureSignedIn]) before returning, so
/// [NotificationService.currentPermission] — which deliberately never forces
/// Firebase to initialise itself, see its doc comment — can see [permission]'s
/// real value immediately. Without this, every test here would see
/// `notDetermined` (Firebase never touched by a fresh instance) regardless of
/// [permission], since main.dart's `IndexedStack` mounts [SettingsScreen]
/// eagerly and this must never provision Firebase just from that.
Future<NotificationService> _buildService({
  NotifPermission permission = NotifPermission.notDetermined,
  bool iosNotInstalled = false,
}) async {
  final social = SocialService(
    client: _FakeSocialClient(),
    firebaseInitializer: () async => true,
  );
  await social.ensureSignedIn();
  return NotificationService(
    client: _FakeNotificationClient(permission: permission),
    socialService: social,
    iosNotInstalledCheck: () => iosNotInstalled,
    timezoneProvider: () => null,
    vapidKey: 'real-vapid-key',
  );
}

Widget _buildSettings(NotificationService service) {
  return MaterialApp(
    home: SettingsScreen(
      currentLang: 'en',
      onLangChanged: (_) {},
      onReplayOnboarding: () {},
      notificationService: service,
    ),
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

/// The Notifications toggle sits at the bottom of a long [ListView] whose
/// off-screen children aren't built until scrolled into the cache extent —
/// [ensureVisible] only works on already-built elements, so every test must
/// scroll there first via [WidgetTester.scrollUntilVisible].
Future<void> _scrollToNotifToggle(WidgetTester tester) async {
  await tester.pumpAndSettle();
  final target = find.widgetWithText(SwitchListTile, 'Daily puzzle reminder');
  await tester.scrollUntilVisible(
    target,
    200,
    scrollable: find.byType(Scrollable),
  );
  // scrollUntilVisible stops once the target is merely present/built, which
  // is not the same as fully within the viewport's hit-testable bounds — the
  // exact list length (and therefore how close the target sits to whatever
  // scroll increment last landed) affects whether those coincide. ensureVisible
  // scrolls precisely so the target's bounds are actually inside the
  // viewport, which is what the tap() calls below need.
  await tester.ensureVisible(target);
  await tester.pumpAndSettle();
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('shows "Off" when never asked', (tester) async {
    await tester.pumpWidget(_buildSettings(await _buildService()));
    await _scrollToNotifToggle(tester);

    expect(find.text('Daily puzzle reminder'), findsOneWidget);
    expect(find.text('Off'), findsOneWidget);
  });

  testWidgets('shows the honest "blocked" message when denied at the browser level',
      (tester) async {
    await tester.pumpWidget(_buildSettings(await _buildService(permission: NotifPermission.denied)));
    await _scrollToNotifToggle(tester);

    expect(find.text('Notifications blocked in your browser settings'), findsOneWidget);
  });

  testWidgets('shows the Add-to-Home-Screen nudge on iOS-not-installed', (tester) async {
    await tester.pumpWidget(_buildSettings(await _buildService(iosNotInstalled: true)));
    await _scrollToNotifToggle(tester);

    expect(find.text('Add to Home Screen to enable notifications'), findsOneWidget);
  });

  testWidgets('toggling on triggers optIn() and flips to "On" on success', (tester) async {
    final service = await _buildService();
    await tester.pumpWidget(_buildSettings(service));
    await _scrollToNotifToggle(tester);

    await tester.tap(find.widgetWithText(SwitchListTile, 'Daily puzzle reminder'));
    await tester.pumpAndSettle();

    expect(await service.isSubscribedLocally(), isTrue);
    expect(find.text('On'), findsOneWidget);
  });

  testWidgets('toggling on when already denied never re-prompts and shows the blocked message',
      (tester) async {
    final client = _FakeNotificationClient(permission: NotifPermission.denied);
    final service = NotificationService(
      client: client,
      socialService: SocialService(
        client: _FakeSocialClient(),
        firebaseInitializer: () async => true,
      ),
      vapidKey: 'real-vapid-key',
    );
    await tester.pumpWidget(_buildSettings(service));
    await _scrollToNotifToggle(tester);

    await tester.tap(find.widgetWithText(SwitchListTile, 'Daily puzzle reminder'));
    await tester.pumpAndSettle();

    expect(client.writeOptInCalls, 0);
    expect(find.text('Notifications blocked in your browser settings'), findsWidgets);
  });

  testWidgets('toggling off calls optOut() and flips to "Off"', (tester) async {
    final service = await _buildService();
    await service.optIn(lang: 'en'); // establish an "on" state first
    await tester.pumpWidget(_buildSettings(service));
    await _scrollToNotifToggle(tester);

    expect(find.text('On'), findsOneWidget);

    await tester.tap(find.widgetWithText(SwitchListTile, 'Daily puzzle reminder'));
    await tester.pumpAndSettle();

    expect(await service.isSubscribedLocally(), isFalse);
    expect(find.text('Off'), findsOneWidget);
  });
}
