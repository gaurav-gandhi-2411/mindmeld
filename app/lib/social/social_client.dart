/// Thin wrapper around the firebase_auth + cloud_firestore SDKs for the 6a
/// Social feature.
///
/// ## Architecture — thin client injection
///
/// Mirrors [AnalyticsClient] (firebase_exporter.dart) and [RcClient]
/// (revenuecat_gateway.dart): [SocialClient] is the abstract interface the
/// rest of the app depends on; [_LiveSocialClient] is the ONLY place
/// firebase_auth / cloud_firestore SDK calls live; tests inject a fake that
/// never touches a platform channel.
///
/// Firebase app initialisation is NOT this file's responsibility — callers
/// (see social_service.dart) must ensure `Firebase.initializeApp()` has run
/// before constructing [_LiveSocialClient]. This keeps Firebase entirely out
/// of solo/offline/signed-out play.
library;

import 'dart:math';

import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/foundation.dart' show debugPrint;

import 'package:mindmeld/social/social_models.dart';

/// Alphabet for join codes — excludes visually-ambiguous characters
/// (0/O, 1/I/L) so codes are easy to read aloud/type from a WhatsApp share.
const String _kCodeAlphabet = '23456789ABCDEFGHJKMNPQRSTUVWXYZ';
const int _kCodeLength = 6;
const int _kMaxCreateRetries = 5;

String _generateCode(Random random) {
  return List.generate(
    _kCodeLength,
    (_) => _kCodeAlphabet[random.nextInt(_kCodeAlphabet.length)],
  ).join();
}

/// Abstract interface for the Firestore/Auth operations 6a needs.
///
/// Tests inject a fake; production supplies [buildSocialClient].
abstract class SocialClient {
  /// Uid of the currently signed-in user, or null if never signed in.
  String? get currentUid;

  /// Silent anonymous sign-in. Idempotent — returns the existing uid if
  /// already signed in this session/device.
  Future<String> signInAnonymously();

  /// Create or update the caller's own profile display name.
  Future<void> setDisplayName({required String uid, required String displayName});

  /// Fetch a display name by uid, or null if no profile exists yet.
  Future<String?> getDisplayName(String uid);

  /// Create a group + its join code. Retries with a fresh code on collision.
  Future<SocialGroup> createGroup({required String uid, required String name});

  /// Resolve a join code to a groupId, or null if the code doesn't exist.
  Future<String?> resolveCode(String code);

  /// Fetch a single group by id, or null if it doesn't exist.
  Future<SocialGroup?> getGroup(String groupId);

  /// All groups the caller belongs to.
  Future<List<SocialGroup>> myGroups(String uid);

  /// Add uid to a group's memberUids. No-op if already a member.
  Future<void> joinGroup({required String groupId, required String uid});

  /// Write today's result to one group. Create-only: callers must treat a
  /// permission-denied re-write (result already recorded) as a benign no-op.
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
  });

  /// Fetch the day's PRESENT result docs for a group, keyed by uid.
  ///
  /// Absence of a uid from the returned map (for a uid in the group's
  /// memberUids) means that member has not played yet — callers must
  /// synthesize the "not played yet" row themselves; this method never
  /// fabricates one.
  Future<Map<String, LeaderboardEntry>> fetchResults({
    required String groupId,
    required String date,
  });

  // ---------------------------------------------------------------------
  // Data deletion (Play/GDPR) — see social_service.dart's deleteMyData().
  // ---------------------------------------------------------------------

  /// Delete the caller's own profile doc (`users/{uid}`).
  Future<void> deleteOwnProfile(String uid);

  /// Remove ONLY [uid] from one group's `memberUids` (leave-group /
  /// delete-my-data flow). No-op if [uid] is already not a member.
  Future<void> removeSelfFromGroup({required String groupId, required String uid});

  /// Best-effort deletion of every past result doc across every group/day
  /// that carries [uid] — see this method's `_LiveSocialClient`
  /// implementation doc comment for why this is "best-effort" (a
  /// production collection-group query may need a one-time index) rather
  /// than a guaranteed operation. MUST be called BEFORE
  /// [removeSelfFromGroup] for each group — `firestore.rules` still
  /// membership-gates reading these docs, so once the caller has left a
  /// group this can no longer find that group's results.
  Future<void> deleteOwnResultsBestEffort(String uid);
}

/// Production [SocialClient] backed by real Firebase SDKs.
///
/// This is the ONLY place in the codebase that calls [FirebaseAuth] or
/// [FirebaseFirestore] methods. Tests never instantiate this class.
class _LiveSocialClient implements SocialClient {
  _LiveSocialClient({Random? random}) : _random = random ?? Random.secure();

  final Random _random;

  FirebaseAuth get _auth => FirebaseAuth.instance;
  FirebaseFirestore get _db => FirebaseFirestore.instance;

  @override
  String? get currentUid => _auth.currentUser?.uid;

  @override
  Future<String> signInAnonymously() async {
    final existing = _auth.currentUser;
    if (existing != null) return existing.uid;
    final cred = await _auth.signInAnonymously();
    return cred.user!.uid;
  }

  @override
  Future<void> setDisplayName({required String uid, required String displayName}) async {
    final ref = _db.collection('users').doc(uid);
    final snap = await ref.get();
    if (!snap.exists) {
      await ref.set({
        'displayName': displayName,
        'createdAt': FieldValue.serverTimestamp(),
        'groupIds': <String>[],
      });
    } else {
      await ref.update({'displayName': displayName});
    }
  }

  @override
  Future<String?> getDisplayName(String uid) async {
    final snap = await _db.collection('users').doc(uid).get();
    if (!snap.exists) return null;
    return snap.data()?['displayName'] as String?;
  }

  @override
  Future<SocialGroup> createGroup({required String uid, required String name}) async {
    // Deliberately SEQUENTIAL, not a WriteBatch. The codes/{code} create
    // rule does a get() on groups/{groupId} to verify ownership, and that
    // get() does NOT see a sibling write from the same batch — Firestore
    // evaluates each batched write's rules against the state BEFORE the
    // batch, not the state it will have after. Batching these two writes
    // together made every single create fail with permission-denied (not
    // just code collisions) — confirmed against the emulator. Writing the
    // group first and awaiting it, then writing the code doc, is the
    // pattern that actually works against these rules (also emulator-verified
    // — see firebase-tests/rules.test.js).
    FirebaseException? lastCodeError;
    for (var attempt = 0; attempt < _kMaxCreateRetries; attempt++) {
      final code = _generateCode(_random);
      final groupRef = _db.collection('groups').doc();

      // Group write: any failure here is a real error (bad data, auth),
      // never a code collision, so it propagates immediately — no retry.
      debugPrint('SocialClient: groups/${groupRef.id} write starting…');
      await groupRef.set({
        'name': name,
        'code': code,
        'createdBy': uid,
        'memberUids': [uid],
        'createdAt': FieldValue.serverTimestamp(),
      });
      debugPrint('SocialClient: groups/${groupRef.id} write done.');

      try {
        debugPrint('SocialClient: codes/$code write starting…');
        await _db.collection('codes').doc(code).set({'groupId': groupRef.id});
        debugPrint('SocialClient: codes/$code write done.');
        return SocialGroup(
          id: groupRef.id,
          name: name,
          code: code,
          createdBy: uid,
          memberUids: [uid],
        );
      } on FirebaseException catch (e) {
        debugPrint('SocialClient: codes/$code write FAILED: ${e.code}');
        // Collision on `code` (codes/{code} already exists -> `update` rule
        // denies it) — retry with a fresh group + code. Any other failure
        // propagates. The orphaned group from this attempt is harmless: with
        // no codes/{code} doc pointing at it, nobody can join it but its
        // creator, whose own group list still lists it (rare — 31^6 codespace).
        if (e.code != 'permission-denied') rethrow;
        lastCodeError = e;
      }
    }
    throw lastCodeError ?? StateError('createGroup: exhausted retries');
  }

  @override
  Future<String?> resolveCode(String code) async {
    final snap = await _db.collection('codes').doc(code.toUpperCase()).get();
    if (!snap.exists) return null;
    return snap.data()?['groupId'] as String?;
  }

  @override
  Future<SocialGroup?> getGroup(String groupId) async {
    final snap = await _db.collection('groups').doc(groupId).get();
    return _groupFromSnap(snap);
  }

  @override
  Future<List<SocialGroup>> myGroups(String uid) async {
    final query = await _db
        .collection('groups')
        .where('memberUids', arrayContains: uid)
        .get();
    return query.docs
        .map(_groupFromSnap)
        .whereType<SocialGroup>()
        .toList();
  }

  @override
  Future<void> joinGroup({required String groupId, required String uid}) async {
    final groupRef = _db.collection('groups').doc(groupId);
    final snap = await groupRef.get();
    if (!snap.exists) {
      throw StateError('joinGroup: group $groupId does not exist');
    }
    final members = List<String>.from(snap.data()!['memberUids'] as List? ?? []);
    if (members.contains(uid)) return; // already a member — idempotent no-op.

    await groupRef.update({
      'memberUids': FieldValue.arrayUnion([uid]),
    });
    // Best-effort convenience index on the user's own profile; not the
    // source of truth for membership (that's groups/{id}.memberUids).
    await _db.collection('users').doc(uid).set(
      {'groupIds': FieldValue.arrayUnion([groupId])},
      SetOptions(merge: true),
    );
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
    final ref = _db
        .collection('groups')
        .doc(groupId)
        .collection('days')
        .doc(date)
        .collection('results')
        .doc(uid);
    await ref.set({
      'uid': uid,
      'displayName': displayName,
      'outcome': outcome,
      'guessesUsed': guessesUsed,
      'par': par,
      'scoreVsPar': scoreVsPar,
      'lang': lang,
      'finishedAt': FieldValue.serverTimestamp(),
    });
  }

  @override
  Future<Map<String, LeaderboardEntry>> fetchResults({
    required String groupId,
    required String date,
  }) async {
    final query = await _db
        .collection('groups')
        .doc(groupId)
        .collection('days')
        .doc(date)
        .collection('results')
        .get();

    final out = <String, LeaderboardEntry>{};
    for (final doc in query.docs) {
      final data = doc.data();
      final ts = data['finishedAt'];
      out[doc.id] = LeaderboardEntry(
        uid: data['uid'] as String,
        displayName: data['displayName'] as String,
        played: true,
        outcome: data['outcome'] as String?,
        guessesUsed: data['guessesUsed'] as int?,
        par: data['par'] as int?,
        scoreVsPar: data['scoreVsPar'] as int?,
        lang: data['lang'] as String?,
        finishedAt: ts is Timestamp ? ts.toDate() : null,
      );
    }
    return out;
  }

  @override
  Future<void> deleteOwnProfile(String uid) async {
    await _db.collection('users').doc(uid).delete();
  }

  @override
  Future<void> removeSelfFromGroup({required String groupId, required String uid}) async {
    await _db.collection('groups').doc(groupId).update({
      'memberUids': FieldValue.arrayRemove([uid]),
    });
  }

  @override
  Future<void> deleteOwnResultsBestEffort(String uid) async {
    // Collection-group query across every groups/{id}/days/{date}/results
    // subcollection, filtered to this uid's own docs (firestore.rules'
    // get/list rule on that subcollection still requires group membership,
    // which is why the caller MUST run this before removeSelfFromGroup —
    // see this method's doc comment on the SocialClient interface).
    //
    // Best-effort, not guaranteed: a collection-group query needs a
    // Firestore index scoped to COLLECTION_GROUP for the 'uid' field. A
    // single-collection index (the default) does NOT cover collection-group
    // queries — production may need a ONE-TIME manual step (Firebase
    // console -> Firestore -> Indexes -> Collection group, or letting the
    // first failed query's error surface a console link to auto-create it)
    // before this succeeds live. Failure here must never block the more
    // important profile+membership deletion in SocialService.deleteMyData(),
    // so every failure is caught and logged, never rethrown.
    try {
      final query =
          await _db.collectionGroup('results').where('uid', isEqualTo: uid).get();
      for (final resultDoc in query.docs) {
        try {
          await resultDoc.reference.delete();
        } catch (e) {
          debugPrint(
              'SocialClient: deleteOwnResultsBestEffort failed for ${resultDoc.reference.path}: $e');
        }
      }
    } catch (e) {
      debugPrint('SocialClient: deleteOwnResultsBestEffort query failed (non-fatal): $e');
    }
  }

  SocialGroup? _groupFromSnap(DocumentSnapshot<Map<String, dynamic>> snap) {
    if (!snap.exists) return null;
    final data = snap.data()!;
    return SocialGroup(
      id: snap.id,
      name: data['name'] as String,
      code: data['code'] as String,
      createdBy: data['createdBy'] as String,
      memberUids: List<String>.from(data['memberUids'] as List? ?? []),
    );
  }
}

/// Production [SocialClient] singleton.
///
/// Callers must ensure `Firebase.initializeApp()` has already run before
/// touching this (see social_service.dart's lazy-init guard).
final SocialClient defaultSocialClient = _LiveSocialClient();
