/// Regression coverage for the "load once in initState, never reload on
/// tab reactivation" staleness pattern (see stats_screen.dart / commit
/// 2e596b0 for the original StatsScreen fix), applied to
/// [SocialHomeScreen] — the second `IndexedStack` tab found to have it.
///
/// [GroupLeaderboardScreen] does NOT have this bug: it's reached via
/// `Navigator.push`, never the `IndexedStack`, so every open constructs a
/// brand-new widget instance with a fresh `initState`/`_load()`. The second
/// test group here locks in that already-correct behaviour across a
/// pop/re-push cycle, matching the real navigation flow.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/features/social/group_leaderboard_screen.dart';
import 'package:mindmeld/features/social/social_home_screen.dart';
import 'package:mindmeld/social/social_client.dart';
import 'package:mindmeld/social/social_models.dart';
import 'package:mindmeld/social/social_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

// ---------------------------------------------------------------------------
// _FakeSocialClient — in-memory stand-in for the real Firestore/Auth wrapper.
//
// Mirrors the fake in social_service_test.dart (kept private to that
// library, so duplicated here rather than imported) — multiple instances
// can share the same backing maps to simulate two different signed-in
// devices talking to the same backend.
// ---------------------------------------------------------------------------
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

  String? uidToAssign;
  String? _currentUid;

  static int _groupCounter = 0;

  @override
  String? get currentUid => _currentUid;

  @override
  Future<String> signInAnonymously() async {
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
    final byDate = results.putIfAbsent(groupId, () => {});
    final byUid = byDate.putIfAbsent(date, () => {});
    if (byUid.containsKey(uid)) {
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
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  group('SocialHomeScreen activation reload', () {
    testWidgets(
      'reloads groups when active flips false→true after a group was created while inactive; '
      'a plain rebuild with active unchanged does not reload',
      (tester) async {
        final aliceClient = _FakeSocialClient(uidToAssign: 'alice');
        final aliceService =
            SocialService(client: aliceClient, firebaseInitializer: () async => true);
        // Establish local identity before mount so hasLocalIdentity is true
        // and myGroups() actually hits the fake client.
        await aliceService.ensureSignedIn();

        await tester.pumpWidget(MaterialApp(
          home: SocialHomeScreen(
            date: '2026-07-10',
            lang: 'en',
            socialService: aliceService,
            active: true,
          ),
        ));
        await tester.pumpAndSettle();

        expect(find.text('Connect to play with friends'), findsOneWidget,
            reason: 'sanity: alice has no groups yet');

        // Simulate a group appearing elsewhere in this session (e.g. created
        // via another path) WITHOUT going through the widget's own
        // _createGroup — the point is that the WIDGET never re-fetches on
        // its own.
        await aliceService.createGroup(groupName: 'Office Crew', displayName: 'Alice');

        // A plain rebuild with active UNCHANGED (true -> true) must NOT
        // reload — proves it's the false->true transition that matters,
        // not any rebuild.
        await tester.pumpWidget(MaterialApp(
          home: SocialHomeScreen(
            date: '2026-07-10',
            lang: 'en',
            socialService: aliceService,
            active: true,
          ),
        ));
        await tester.pumpAndSettle();

        expect(find.text('Connect to play with friends'), findsOneWidget,
            reason: 'a rebuild with active unchanged must stay stale');
        expect(find.text('Office Crew'), findsNothing);

        // Tab away (active: false)...
        await tester.pumpWidget(MaterialApp(
          home: SocialHomeScreen(
            date: '2026-07-10',
            lang: 'en',
            socialService: aliceService,
            active: false,
          ),
        ));
        await tester.pumpAndSettle();

        // ...then back (active: true) — must reload and show the new group.
        await tester.pumpWidget(MaterialApp(
          home: SocialHomeScreen(
            date: '2026-07-10',
            lang: 'en',
            socialService: aliceService,
            active: true,
          ),
        ));
        await tester.pumpAndSettle();

        expect(find.text('Office Crew'), findsOneWidget,
            reason: 'tab reactivation must reload the group list');
        expect(find.text('Connect to play with friends'), findsNothing);
      },
    );
  });

  group('GroupLeaderboardScreen freshness across pop/re-push', () {
    testWidgets(
      "reflects a friend's fresh result across a pop/re-push cycle "
      '(already-correct behaviour — locked in as regression coverage)',
      (tester) async {
        final users = <String, String>{};
        final groups = <String, Map<String, dynamic>>{};
        final codes = <String, String>{};
        final results = <String, Map<String, Map<String, Map<String, dynamic>>>>{};

        final aliceClient = _FakeSocialClient(
            users: users, groups: groups, codes: codes, results: results, uidToAssign: 'alice');
        final aliceService =
            SocialService(client: aliceClient, firebaseInitializer: () async => true);
        final group =
            await aliceService.createGroup(groupName: 'Friends', displayName: 'Alice');

        final bobClient = _FakeSocialClient(
            users: users, groups: groups, codes: codes, results: results, uidToAssign: 'bob');
        final bobService =
            SocialService(client: bobClient, firebaseInitializer: () async => true);
        await bobService.joinByCode(code: group!.code, displayName: 'Bob');

        // Alice already played today — isolates the "not played yet" row to
        // bob alone, so the assertions below target his row specifically.
        await aliceService.writeResultToAllGroups(
          date: '2026-07-10',
          outcome: 'win',
          guessesUsed: 3,
          par: 5,
          scoreVsPar: -2,
          lang: 'en',
        );

        final navigatorKey = GlobalKey<NavigatorState>();
        await tester.pumpWidget(MaterialApp(
          navigatorKey: navigatorKey,
          home: const Scaffold(body: SizedBox()),
        ));

        // First push: bob hasn't played yet.
        navigatorKey.currentState!.push(MaterialPageRoute<void>(
          builder: (_) => GroupLeaderboardScreen(
            group: group,
            date: '2026-07-10',
            lang: 'en',
            socialService: aliceService,
          ),
        ));
        await tester.pumpAndSettle();

        expect(find.text('Not played yet'), findsOneWidget,
            reason: "sanity: bob's row starts as not-played");

        // Pop back.
        navigatorKey.currentState!.pop();
        await tester.pumpAndSettle();

        // Bob finishes his puzzle.
        await bobService.writeResultToAllGroups(
          date: '2026-07-10',
          outcome: 'win',
          guessesUsed: 4,
          par: 5,
          scoreVsPar: -1,
          lang: 'en',
        );

        // Push a FRESH GroupLeaderboardScreen instance — must show bob's win.
        navigatorKey.currentState!.push(MaterialPageRoute<void>(
          builder: (_) => GroupLeaderboardScreen(
            group: group,
            date: '2026-07-10',
            lang: 'en',
            socialService: aliceService,
          ),
        ));
        await tester.pumpAndSettle();

        expect(find.text('Not played yet'), findsNothing,
            reason: "bob's fresh win must be reflected, not a stale not-played row");
        expect(find.textContaining('Won in 4'), findsOneWidget);
      },
    );
  });
}
