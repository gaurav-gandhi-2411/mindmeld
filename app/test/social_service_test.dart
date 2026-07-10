/// Unit tests for [SocialService].
///
/// All tests run as pure host (dart vm) tests — zero Firebase SDK calls.
/// [_FakeSocialClient] is an in-memory stand-in for the real Firestore/Auth
/// wrapper; [SocialService]'s Firebase-init step is bypassed via the
/// [SocialService.new]'s `firebaseInitializer` override so tests never touch
/// the firebase_core platform channel.
///
/// Coverage (mirrors spec.md #6a acceptance criteria):
///   1. Offline/signed-out degradation: no local identity -> every social
///      read/write is a safe no-op, and the fake client is never touched.
///   2. Group create + join (by code), including multiple-group membership.
///   3. Result write to all of a player's groups; create-only idempotency
///      (a duplicate write for the same day is swallowed, not thrown).
///   4. Leaderboard ranking, including synthesizing "not played yet" rows
///      for members with no result doc — and that those rows are spoiler-safe.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/social/social_client.dart';
import 'package:mindmeld/social/social_models.dart';
import 'package:mindmeld/social/social_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

// ---------------------------------------------------------------------------
// _FakeSocialClient — in-memory stand-in for the real Firestore/Auth wrapper
// ---------------------------------------------------------------------------

/// Multiple instances can share the same backing maps to simulate two
/// different signed-in devices talking to the same backend.
class _FakeSocialClient implements SocialClient {
  _FakeSocialClient({
    Map<String, String>? users,
    Map<String, Map<String, dynamic>>? groups,
    Map<String, String>? codes,
    Map<String, Map<String, Map<String, Map<String, dynamic>>>>? results,
    this.uidToAssign,
  })  : users = users ?? {},
        groups = groups ?? {},
        codes = codes ?? {},
        results = results ?? {};

  final Map<String, String> users;
  final Map<String, Map<String, dynamic>> groups;
  final Map<String, String> codes;
  final Map<String, Map<String, Map<String, Map<String, dynamic>>>> results;

  /// If set, [signInAnonymously] "assigns" this uid (simulates a specific
  /// device/user rather than an arbitrary generated one).
  String? uidToAssign;
  String? _currentUid;

  /// Calls recorded for the "never touches Firebase when offline" assertions.
  int signInCalls = 0;
  int myGroupsCalls = 0;
  int writeResultCalls = 0;

  static int _groupCounter = 0;

  @override
  String? get currentUid => _currentUid;

  @override
  Future<String> signInAnonymously() async {
    signInCalls++;
    _currentUid ??= uidToAssign ?? 'uid${_groupCounter++}';
    return _currentUid!;
  }

  @override
  Future<void> setDisplayName({required String uid, required String displayName}) async {
    users[uid] = displayName;
  }

  @override
  Future<String?> getDisplayName(String uid) async => users[uid];

  @override
  Future<SocialGroup> createGroup({required String uid, required String name}) async {
    final id = 'group${_groupCounter++}';
    final code = 'CODE${_groupCounter++}';
    groups[id] = {'name': name, 'code': code, 'createdBy': uid, 'memberUids': <String>[uid]};
    codes[code] = id;
    return _groupFrom(id);
  }

  @override
  Future<String?> resolveCode(String code) async => codes[code.toUpperCase()];

  @override
  Future<SocialGroup?> getGroup(String groupId) async {
    if (!groups.containsKey(groupId)) return null;
    return _groupFrom(groupId);
  }

  @override
  Future<List<SocialGroup>> myGroups(String uid) async {
    myGroupsCalls++;
    return groups.entries
        .where((e) => (e.value['memberUids'] as List<String>).contains(uid))
        .map((e) => _groupFrom(e.key))
        .toList();
  }

  @override
  Future<void> joinGroup({required String groupId, required String uid}) async {
    final g = groups[groupId];
    if (g == null) throw StateError('joinGroup: no such group');
    final members = g['memberUids'] as List<String>;
    if (!members.contains(uid)) members.add(uid);
  }

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
  }) async {
    writeResultCalls++;
    final byDate = results.putIfAbsent(groupId, () => {});
    final byUid = byDate.putIfAbsent(date, () => {});
    if (byUid.containsKey(uid)) {
      // Mirrors the real create-only Firestore rule denying a re-write.
      throw StateError('permission-denied: result already exists for $uid on $date');
    }
    byUid[uid] = {
      'uid': uid,
      'displayName': displayName,
      'outcome': outcome,
      'guessesUsed': guessesUsed,
      'par': par,
      'scoreVsPar': scoreVsPar,
      'lang': lang,
    };
  }

  @override
  Future<Map<String, LeaderboardEntry>> fetchResults({
    required String groupId,
    required String date,
  }) async {
    final byUid = results[groupId]?[date] ?? {};
    return byUid.map((uid, data) => MapEntry(
          uid,
          LeaderboardEntry(
            uid: data['uid'] as String,
            displayName: data['displayName'] as String,
            played: true,
            outcome: data['outcome'] as String?,
            guessesUsed: data['guessesUsed'] as int?,
            par: data['par'] as int?,
            scoreVsPar: data['scoreVsPar'] as int?,
            lang: data['lang'] as String?,
          ),
        ));
  }

  SocialGroup _groupFrom(String id) {
    final g = groups[id]!;
    return SocialGroup(
      id: id,
      name: g['name'] as String,
      code: g['code'] as String,
      createdBy: g['createdBy'] as String,
      memberUids: List<String>.from(g['memberUids'] as List),
    );
  }

  int deleteOwnProfileCalls = 0;
  int removeSelfFromGroupCalls = 0;
  int deleteOwnResultsBestEffortCalls = 0;

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
  Future<void> deleteOwnResultsBestEffort(String uid) async {
    deleteOwnResultsBestEffortCalls++;
    for (final byDate in results.values) {
      for (final byUid in byDate.values) {
        byUid.remove(uid);
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  group('offline / signed-out degradation', () {
    test('myGroups() is [] and never touches the client when Firebase init fails', () async {
      final fake = _FakeSocialClient();
      final service = SocialService(client: fake, firebaseInitializer: () async => false);

      expect(await service.myGroups(), isEmpty);
      expect(fake.myGroupsCalls, 0);
      expect(service.hasLocalIdentity, isFalse);
    });

    test('writeResultToAllGroups() no-ops silently when offline', () async {
      final fake = _FakeSocialClient();
      final service = SocialService(client: fake, firebaseInitializer: () async => false);

      await service.writeResultToAllGroups(
        date: '2026-07-06',
        outcome: 'win',
        guessesUsed: 5,
        par: 6,
        scoreVsPar: -1,
        lang: 'en',
      );

      expect(fake.writeResultCalls, 0); // never reached the client
    });

    test('createGroup() returns offline status without touching the client', () async {
      final fake = _FakeSocialClient();
      final service = SocialService(client: fake, firebaseInitializer: () async => false);

      final result = await service.createGroup(groupName: 'Friends', displayName: 'Alice');

      expect(result.status, CreateGroupStatus.offline);
      expect(result.group, isNull);
      expect(fake.groups, isEmpty);
    });

    test('ensureSignedIn() returns null (never throws) on init failure', () async {
      final service = SocialService(
        client: _FakeSocialClient(),
        firebaseInitializer: () async => false,
      );
      expect(await service.ensureSignedIn(), isNull);
    });
  });

  group('group create + join', () {
    test('creating a group signs in, sets the profile, and returns the group', () async {
      final fake = _FakeSocialClient();
      final service = SocialService(client: fake, firebaseInitializer: () async => true);

      final result = await service.createGroup(groupName: 'Office Crew', displayName: 'Alice');

      expect(result.status, CreateGroupStatus.success);
      final group = result.group;
      expect(group, isNotNull);
      expect(group!.name, 'Office Crew');
      expect(group.memberUids, [fake.currentUid]);
      expect(fake.users[fake.currentUid], 'Alice');
      expect(service.hasLocalIdentity, isTrue);
      expect(service.selfUidOrNull, fake.currentUid);
    });

    test('a second player joins by code; the group now has both members', () async {
      final users = <String, String>{};
      final groups = <String, Map<String, dynamic>>{};
      final codes = <String, String>{};

      final aliceClient = _FakeSocialClient(users: users, groups: groups, codes: codes, uidToAssign: 'alice');
      final alice = SocialService(client: aliceClient, firebaseInitializer: () async => true);
      final group = (await alice.createGroup(groupName: 'Friends', displayName: 'Alice')).group;

      final bobClient = _FakeSocialClient(users: users, groups: groups, codes: codes, uidToAssign: 'bob');
      final bob = SocialService(client: bobClient, firebaseInitializer: () async => true);
      final result = await bob.joinByCode(code: group!.code, displayName: 'Bob');

      expect(result.status, JoinCodeStatus.success);
      expect(result.group!.memberUids, containsAll(['alice', 'bob']));
    });

    test('joining an unknown code returns codeNotFound', () async {
      final service = SocialService(client: _FakeSocialClient(), firebaseInitializer: () async => true);
      final result = await service.joinByCode(code: 'NOSUCH', displayName: 'Alice');
      expect(result.status, JoinCodeStatus.codeNotFound);
    });

    test('a player can belong to multiple groups', () async {
      final fake = _FakeSocialClient(uidToAssign: 'alice');
      final service = SocialService(client: fake, firebaseInitializer: () async => true);

      await service.createGroup(groupName: 'Group One', displayName: 'Alice');
      await service.createGroup(groupName: 'Group Two', displayName: 'Alice');

      final mine = await service.myGroups();
      expect(mine.map((g) => g.name).toSet(), {'Group One', 'Group Two'});
    });
  });

  group('result write', () {
    test('writes to every group the player belongs to', () async {
      final fake = _FakeSocialClient(uidToAssign: 'alice');
      final service = SocialService(client: fake, firebaseInitializer: () async => true);
      await service.createGroup(groupName: 'Group One', displayName: 'Alice');
      await service.createGroup(groupName: 'Group Two', displayName: 'Alice');

      await service.writeResultToAllGroups(
        date: '2026-07-06',
        outcome: 'win',
        guessesUsed: 4,
        par: 6,
        scoreVsPar: -2,
        lang: 'en',
      );

      expect(fake.writeResultCalls, 2);
      for (final groupResults in fake.results.values) {
        expect(groupResults['2026-07-06']!['alice']!['outcome'], 'win');
      }
    });

    test('a duplicate write for the same day is swallowed, not thrown (create-only)', () async {
      final fake = _FakeSocialClient(uidToAssign: 'alice');
      final service = SocialService(client: fake, firebaseInitializer: () async => true);
      await service.createGroup(groupName: 'Group One', displayName: 'Alice');

      await service.writeResultToAllGroups(
        date: '2026-07-06', outcome: 'win', guessesUsed: 4, par: 6, scoreVsPar: -2, lang: 'en',
      );
      // Second call for the same day must not throw, even though the fake
      // client rejects the duplicate create exactly like the real rules do.
      await service.writeResultToAllGroups(
        date: '2026-07-06', outcome: 'loss', guessesUsed: 15, par: 6, scoreVsPar: 9, lang: 'en',
      );

      expect(fake.writeResultCalls, 2); // both attempted
      final stored = fake.results.values.first['2026-07-06']!['alice']!;
      expect(stored['outcome'], 'win'); // first write wins; second was rejected
    });
  });

  group('leaderboard', () {
    test('ranks wins by fewest guesses and synthesizes "not played yet" for missing docs', () async {
      final users = <String, String>{};
      final groups = <String, Map<String, dynamic>>{};
      final codes = <String, String>{};
      final results = <String, Map<String, Map<String, Map<String, dynamic>>>>{};

      final aliceClient = _FakeSocialClient(
          users: users, groups: groups, codes: codes, results: results, uidToAssign: 'alice');
      final alice = SocialService(client: aliceClient, firebaseInitializer: () async => true);
      final group = (await alice.createGroup(groupName: 'Friends', displayName: 'Alice')).group;

      final bobClient = _FakeSocialClient(
          users: users, groups: groups, codes: codes, results: results, uidToAssign: 'bob');
      final bob = SocialService(client: bobClient, firebaseInitializer: () async => true);
      await bob.joinByCode(code: group!.code, displayName: 'Bob');

      final carolClient = _FakeSocialClient(
          users: users, groups: groups, codes: codes, results: results, uidToAssign: 'carol');
      final carol = SocialService(client: carolClient, firebaseInitializer: () async => true);
      await carol.joinByCode(code: group.code, displayName: 'Carol');

      // Alice wins in 6, Bob wins in 3. Carol never plays today.
      await alice.writeResultToAllGroups(
        date: '2026-07-06', outcome: 'win', guessesUsed: 6, par: 6, scoreVsPar: 0, lang: 'en',
      );
      await bob.writeResultToAllGroups(
        date: '2026-07-06', outcome: 'win', guessesUsed: 3, par: 6, scoreVsPar: -3, lang: 'en',
      );

      final board = await alice.leaderboardFor(groupId: group.id, date: '2026-07-06');

      expect(board.map((e) => e.uid).toList(), ['bob', 'alice', 'carol']);
      expect(board.last.played, isFalse);
      // Spoiler safety: the not-played row carries no outcome/score data.
      expect(board.last.outcome, isNull);
      expect(board.last.guessesUsed, isNull);
      expect(board.last.scoreVsPar, isNull);
      expect(board.last.displayName, 'Carol'); // name still resolved for display
    });

    test('an unknown groupId yields an empty leaderboard rather than throwing', () async {
      final service = SocialService(client: _FakeSocialClient(), firebaseInitializer: () async => true);
      final board = await service.leaderboardFor(groupId: 'nope', date: '2026-07-06');
      expect(board, isEmpty);
    });
  });

  group('deleteMyData (Play/GDPR)', () {
    test('with no local identity, returns notSignedIn without touching the client', () async {
      final fake = _FakeSocialClient();
      final service = SocialService(client: fake, firebaseInitializer: () async => false);

      final result = await service.deleteMyData();

      expect(result.status, DeleteMyDataStatus.notSignedIn);
      expect(fake.deleteOwnProfileCalls, 0);
      expect(fake.removeSelfFromGroupCalls, 0);
    });

    test('removes the user from every group, deletes the profile, clears cached name', () async {
      final fake = _FakeSocialClient(uidToAssign: 'alice');
      final service = SocialService(client: fake, firebaseInitializer: () async => true);
      final groupOne = (await service.createGroup(groupName: 'Group One', displayName: 'Alice')).group!;
      final groupTwo = (await service.createGroup(groupName: 'Group Two', displayName: 'Alice')).group!;

      final result = await service.deleteMyData();

      expect(result.status, DeleteMyDataStatus.success);
      expect(fake.deleteOwnProfileCalls, 1);
      expect(fake.removeSelfFromGroupCalls, 2);
      expect(fake.users.containsKey('alice'), isFalse);
      expect((fake.groups[groupOne.id]!['memberUids'] as List<String>).contains('alice'), isFalse);
      expect((fake.groups[groupTwo.id]!['memberUids'] as List<String>).contains('alice'), isFalse);
      expect(await service.cachedDisplayName(), isNull);
    });

    test("does not remove OTHER members from a shared group's memberUids", () async {
      final users = <String, String>{};
      final groups = <String, Map<String, dynamic>>{};
      final codes = <String, String>{};

      final aliceClient = _FakeSocialClient(users: users, groups: groups, codes: codes, uidToAssign: 'alice');
      final alice = SocialService(client: aliceClient, firebaseInitializer: () async => true);
      final group = (await alice.createGroup(groupName: 'Friends', displayName: 'Alice')).group!;

      final bobClient = _FakeSocialClient(users: users, groups: groups, codes: codes, uidToAssign: 'bob');
      final bob = SocialService(client: bobClient, firebaseInitializer: () async => true);
      await bob.joinByCode(code: group.code, displayName: 'Bob');

      await alice.deleteMyData();

      final remaining = groups[group.id]!['memberUids'] as List<String>;
      expect(remaining, ['bob']);
      expect(users.containsKey('bob'), isTrue); // bob's own profile untouched
    });

    test('best-effort result deletion removes only the deleting user\'s own rows', () async {
      final fake = _FakeSocialClient(uidToAssign: 'alice');
      final service = SocialService(client: fake, firebaseInitializer: () async => true);
      final group = (await service.createGroup(groupName: 'Friends', displayName: 'Alice')).group!;
      await service.writeResultToAllGroups(
        date: '2026-07-06', outcome: 'win', guessesUsed: 4, par: 6, scoreVsPar: -2, lang: 'en',
      );

      await service.deleteMyData();

      expect(fake.deleteOwnResultsBestEffortCalls, 1);
      expect(fake.results[group.id]!['2026-07-06']!.containsKey('alice'), isFalse);
    });
  });
}
