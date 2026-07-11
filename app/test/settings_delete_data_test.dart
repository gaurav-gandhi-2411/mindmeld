/// Widget tests for the "Delete my data" action added to [SettingsScreen]
/// (launch-hardening pass, Play/GDPR data-deletion requirement).
///
/// Coverage:
///   1. The tile is always visible.
///   2. Tapping it shows a confirmation dialog; cancelling does NOT call
///      [SocialService.deleteMyData].
///   3. Confirming with no local identity shows the friendly
///      "nothing to delete" message.
///   4. Confirming with a local identity calls deleteMyData() and shows the
///      success message.
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
// _FakeSocialClient — minimal in-memory stand-in, mirrors the fakes in
// social_service_test.dart / social_activation_reload_test.dart (duplicated
// per this codebase's existing convention rather than imported/shared).
// ---------------------------------------------------------------------------
class _FakeSocialClient implements SocialClient {
  final Map<String, String> users = {};
  final Map<String, Map<String, dynamic>> groups = {};
  String? _uid;
  int deleteOwnProfileCalls = 0;
  int removeSelfFromGroupCalls = 0;

  @override
  String? get currentUid => _uid;

  @override
  Future<String> signInAnonymously() async => _uid ??= 'uid0';

  @override
  Future<void> setDisplayName({required String uid, required String displayName}) async {
    users[uid] = displayName;
  }

  @override
  Future<String?> getDisplayName(String uid) async => users[uid];

  @override
  Future<SocialGroup> createGroup({required String uid, required String name}) async {
    const id = 'group0';
    groups[id] = {'name': name, 'code': 'CODE0', 'createdBy': uid, 'memberUids': <String>[uid]};
    return SocialGroup(id: id, name: name, code: 'CODE0', createdBy: uid, memberUids: [uid]);
  }

  @override
  Future<String?> resolveCode(String code) async => null;

  @override
  Future<SocialGroup?> getGroup(String groupId) async => null;

  @override
  Future<List<SocialGroup>> myGroups(String uid) async {
    return groups.entries
        .where((e) => (e.value['memberUids'] as List<String>).contains(uid))
        .map((e) => SocialGroup(
              id: e.key,
              name: e.value['name'] as String,
              code: e.value['code'] as String,
              createdBy: e.value['createdBy'] as String,
              memberUids: List<String>.from(e.value['memberUids'] as List),
            ))
        .toList();
  }

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
  Future<void> deleteOwnProfile(String uid) async {
    deleteOwnProfileCalls++;
    users.remove(uid);
  }

  @override
  Future<void> removeSelfFromGroup({required String groupId, required String uid}) async {
    removeSelfFromGroupCalls++;
    (groups[groupId]?['memberUids'] as List<String>?)?.remove(uid);
  }

  @override
  Future<void> deleteOwnResultsBestEffort(String uid) async {}
}

/// Minimal [NotificationClient] stand-in — the Notifications section is
/// unrelated to this test file, but [SettingsScreen] always builds one via
/// [buildNotificationService] unless overridden, and the REAL client would
/// hang on a platform channel call with no Firebase plugin registered in a
/// host/VM test (mirrors settings_notifications_test.dart's fake).
class _FakeNotificationClient implements NotificationClient {
  @override
  Future<NotifPermission> currentPermission() async => NotifPermission.notDetermined;

  @override
  Future<NotifPermission> requestPermission() async => NotifPermission.notDetermined;

  @override
  Future<String?> getToken(String vapidKey) async => null;

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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

Widget _buildSettings(SocialService socialService) {
  return MaterialApp(
    home: SettingsScreen(
      currentLang: 'en',
      onLangChanged: (_) {},
      onReplayOnboarding: () {},
      notificationService: NotificationService(
        client: _FakeNotificationClient(),
        socialService: socialService,
      ),
      socialService: socialService,
    ),
  );
}

/// "Delete my data" sits at the bottom of a long [ListView] whose off-screen
/// children aren't built until scrolled into the cache extent — mirrors
/// settings_notifications_test.dart's `_scrollToNotifToggle` helper.
Future<void> _scrollToDeleteMyData(WidgetTester tester) async {
  await tester.pumpAndSettle();
  await tester.scrollUntilVisible(
    find.text('Delete my data'),
    200,
    scrollable: find.byType(Scrollable),
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('"Delete my data" tile is always visible', (tester) async {
    final service = SocialService(client: _FakeSocialClient(), firebaseInitializer: () async => false);
    await tester.pumpWidget(_buildSettings(service));
    await _scrollToDeleteMyData(tester);

    expect(find.text('Delete my data'), findsOneWidget);
  });

  testWidgets('tapping it shows a confirmation dialog; Cancel does not call deleteMyData',
      (tester) async {
    final fake = _FakeSocialClient();
    final service = SocialService(client: fake, firebaseInitializer: () async => true);
    await service.ensureSignedIn();

    await tester.pumpWidget(_buildSettings(service));
    await tester.pump();

    await _scrollToDeleteMyData(tester);
    await tester.tap(find.text('Delete my data'));
    await tester.pumpAndSettle();

    expect(find.text('Delete my data?'), findsOneWidget);

    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();

    expect(fake.deleteOwnProfileCalls, 0);
  });

  testWidgets('confirming with no local identity shows the "nothing to delete" message',
      (tester) async {
    final fake = _FakeSocialClient();
    final service = SocialService(client: fake, firebaseInitializer: () async => false);

    await tester.pumpWidget(_buildSettings(service));
    await tester.pump();

    await _scrollToDeleteMyData(tester);
    await tester.tap(find.text('Delete my data'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Delete'));
    await tester.pumpAndSettle();

    expect(
      find.text("You haven't used Play with Friends, so there's nothing to delete."),
      findsOneWidget,
    );
    expect(fake.deleteOwnProfileCalls, 0);
  });

  testWidgets('confirming with a local identity calls deleteMyData and shows success',
      (tester) async {
    final fake = _FakeSocialClient();
    final service = SocialService(client: fake, firebaseInitializer: () async => true);
    await service.createGroup(groupName: 'Friends', displayName: 'Alice');

    await tester.pumpWidget(_buildSettings(service));
    await tester.pump();

    await _scrollToDeleteMyData(tester);
    await tester.tap(find.text('Delete my data'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Delete'));
    await tester.pumpAndSettle();

    expect(find.text('Your data has been deleted.'), findsOneWidget);
    expect(fake.deleteOwnProfileCalls, 1);
    expect(fake.removeSelfFromGroupCalls, 1);
  });

  testWidgets(
      'regression 2026-07-11: a cached display name from a PRIOR session still deletes '
      'even though hasLocalIdentity is false this session (fresh page load, no other '
      'social action taken yet before tapping Delete)', (tester) async {
    final fake = _FakeSocialClient();
    // Simulate server-side state from a session that ended before this one
    // started -- this SocialService instance never calls ensureSignedIn (so
    // hasLocalIdentity starts false), but the SAME uid signInAnonymously()
    // resolves to (`uid0`, the fake's fixed first-call value) already owns
    // a group, mirroring a returning user whose persisted Firebase Auth
    // session hasn't been re-established THIS page load yet.
    fake.groups['group0'] = {
      'name': 'Friends',
      'code': 'CODE0',
      'createdBy': 'uid0',
      'memberUids': <String>['uid0'],
    };
    SharedPreferences.setMockInitialValues({'social_display_name': 'Alice'});
    final service = SocialService(client: fake, firebaseInitializer: () async => true);

    await tester.pumpWidget(_buildSettings(service));
    await tester.pump();

    await _scrollToDeleteMyData(tester);
    await tester.tap(find.text('Delete my data'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Delete'));
    await tester.pumpAndSettle();

    expect(find.text('Your data has been deleted.'), findsOneWidget);
    expect(fake.deleteOwnProfileCalls, 1);
    expect(fake.removeSelfFromGroupCalls, 1);
  });
}
