/// Orchestration layer for the 6a Social feature.
///
/// ## Degradation guarantee
///
/// Firebase (Auth + Firestore) is touched ONLY when the player takes an
/// explicit social action (create group, join group, or finishing a puzzle
/// while already having a social identity) — never on app boot, and never
/// for a player who has never used social features. This is enforced by
/// [_defaultFirebaseInitializer] checking [Firebase.apps] (a getter that is
/// always safe to call, even before any app is initialised) before ANY
/// firebase_auth/cloud_firestore call.
///
/// Every method here catches its own failures (offline, misconfigured web
/// options, permission-denied races) and degrades gracefully — solo play
/// must never be blocked or crashed by a social-feature error.
///
/// All logging in this file uses [debugPrint], never `dart:developer`'s
/// `log()` — the latter compiles to a no-op in Flutter's release/product
/// web builds, which is exactly why the 2026-07-07 live hang produced zero
/// console output despite every failure path being "logged."
library;

import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/foundation.dart' show debugPrint, kIsWeb;
import 'package:shared_preferences/shared_preferences.dart';

import 'package:mindmeld/analytics/firebase_web_options.dart';
import 'package:mindmeld/social/social_client.dart';
import 'package:mindmeld/social/social_models.dart';

const String _kDisplayNamePrefsKey = 'social_display_name';

/// Hard ceiling on every individual Firebase/Firestore call made from this
/// service. Without this, a stuck platform-channel/JS-interop promise (a
/// known failure mode for firebase_auth on web) hangs forever with no
/// feedback — every social action must eventually resolve, one way or another.
const Duration _kSocialOpTimeout = Duration(seconds: 20);

/// Outcome of a join-by-code attempt.
enum JoinCodeStatus {
  /// Joined (or was already a member of) the group.
  success,

  /// The code does not resolve to any group.
  codeNotFound,

  /// Could not reach Firebase (offline / misconfigured) — degrade gently.
  offline,
}

class JoinCodeResult {
  const JoinCodeResult({required this.status, this.group});

  final JoinCodeStatus status;
  final SocialGroup? group;
}

/// High-level social operations used by the UI layer.
///
/// Construct via [buildSocialService] rather than directly.
class SocialService {
  SocialService({SocialClient? client, Future<bool> Function()? firebaseInitializer})
      : _client = client ?? defaultSocialClient,
        _firebaseInitializer = firebaseInitializer ?? _defaultFirebaseInitializer;

  final SocialClient _client;

  /// Provisions the Firebase app; overridable so tests can bypass the real
  /// firebase_core platform channel entirely while still exercising a fake
  /// [SocialClient] for the actual Firestore/Auth calls.
  final Future<bool> Function() _firebaseInitializer;

  /// Cached result of the first successful [_firebaseInitializer] call —
  /// avoids re-deriving readiness from a global registry on every check.
  bool _firebaseReady = false;

  // ---------------------------------------------------------------------------
  // Firebase lazy-init + sign-in
  // ---------------------------------------------------------------------------

  /// True if Firebase has been initialised AND the player already has an
  /// anonymous identity — checkable with zero network calls. Use this to
  /// decide whether to show the "gentle connect" state vs. live social UI.
  ///
  /// Re-derives [_firebaseReady] from the real, process-global [Firebase.apps]
  /// registry when this instance hasn't seen it true yet — NOT just returning
  /// the cached flag as-is. Found live 2026-07-07: every call site that fires
  /// a result write or checks identity ad hoc (e.g. `buildSocialService()` in
  /// main.dart's win/loss handlers, or the "Challenge your group" CTA pushing
  /// a brand-new [SocialHomeScreen]) constructs a FRESH [SocialService], whose
  /// own [_firebaseReady] always starts false — even when Firebase was already
  /// initialised and the player already signed in via a DIFFERENT instance
  /// earlier in the same session. That silently no-opped every single
  /// [writeResultToAllGroups] call (zero result docs ever written) and showed
  /// a false "Connect to play with friends" empty state for players who
  /// already had groups. [Firebase.apps] is safe to call with zero network
  /// cost regardless of which app instance touched it (see
  /// [_defaultFirebaseInitializer]), so this stays a local-only check.
  bool get hasLocalIdentity {
    if (!_firebaseReady) _firebaseReady = Firebase.apps.isNotEmpty;
    return _firebaseReady && _client.currentUid != null;
  }

  /// The signed-in uid, or null if there's no local identity yet. Used by UI
  /// to highlight "your" row in a leaderboard.
  String? get selfUidOrNull => hasLocalIdentity ? _client.currentUid : null;

  /// Guards [_applyFirestoreWebSettings] to exactly one call, ever — Firestore
  /// throws if `.settings =` is set after any other Firestore method has
  /// already run, so this must fire before the very first Firestore call
  /// regardless of WHICH code path initialised the Firebase app.
  static bool _firestoreSettingsApplied = false;

  /// Forces the web Firestore client onto long-polling instead of the
  /// default WebChannel streaming transport.
  ///
  /// Root-caused 2026-07-07: creating a group hung indefinitely live on
  /// playmindmeld.vercel.app with zero visible error, while every equivalent
  /// emulator test passed — the emulator doesn't reproduce real-network
  /// transport behavior. WebChannel streaming is known to stall silently
  /// behind some proxies/networks/browser configurations, and unlike a
  /// clean rejection, a stalled stream never fires the `.timeout()` guards
  /// added earlier in this file in a way the user could see quickly (the
  /// underlying request just never completes). `autoDetectLongPolling` asks
  /// the SDK to probe once and use long-polling only if the environment
  /// actually needs it, so this is not a blanket performance regression.
  static void _applyFirestoreWebSettings() {
    if (_firestoreSettingsApplied || !kIsWeb) return;
    _firestoreSettingsApplied = true;
    FirebaseFirestore.instance.settings = const Settings(
      webExperimentalAutoDetectLongPolling: true,
    );
    debugPrint('SocialService: applied webExperimentalAutoDetectLongPolling=true');
  }

  static Future<bool> _defaultFirebaseInitializer() async {
    if (Firebase.apps.isNotEmpty) {
      _applyFirestoreWebSettings();
      return true;
    }
    final webConfigReady = !kIsWeb || firebaseWebOptions.apiKey != 'PLACEHOLDER';
    if (!webConfigReady) return false;
    try {
      debugPrint('SocialService: [1/4] Firebase.initializeApp() starting…');
      await Firebase.initializeApp(options: kIsWeb ? firebaseWebOptions : null)
          .timeout(_kSocialOpTimeout);
      debugPrint('SocialService: [1/4] Firebase.initializeApp() done.');
      _applyFirestoreWebSettings();
      return true;
    } catch (e) {
      debugPrint('SocialService: [1/4] Firebase.initializeApp() FAILED: $e');
      return false;
    }
  }

  /// Silently provision (or resume) an anonymous identity. Returns null on
  /// any failure (offline, misconfigured, timed out) — never throws.
  Future<String?> ensureSignedIn() async {
    if (!_firebaseReady) {
      _firebaseReady = await _firebaseInitializer();
    }
    if (!_firebaseReady) return null;
    try {
      debugPrint('SocialService: [2/4] signInAnonymously() starting…');
      final uid = await _client.signInAnonymously().timeout(_kSocialOpTimeout);
      debugPrint('SocialService: [2/4] signInAnonymously() done (uid=$uid).');
      return uid;
    } catch (e) {
      debugPrint('SocialService: [2/4] signInAnonymously() FAILED: $e');
      return null;
    }
  }

  // ---------------------------------------------------------------------------
  // Display name
  // ---------------------------------------------------------------------------

  /// Locally-cached display name (no network). Null if never set.
  Future<String?> cachedDisplayName() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_kDisplayNamePrefsKey);
  }

  /// Set/update the display name both locally and on the user's profile doc.
  ///
  /// Must be called after [ensureSignedIn] has produced a uid. Returns false
  /// (without caching locally) if the remote write fails, so the UI can
  /// retry instead of masking a name that never actually saved.
  Future<bool> setDisplayName(String uid, String displayName) async {
    try {
      debugPrint('SocialService: [3/4] users/$uid write starting…');
      await _client.setDisplayName(uid: uid, displayName: displayName).timeout(_kSocialOpTimeout);
      debugPrint('SocialService: [3/4] users/$uid write done.');
    } catch (e) {
      debugPrint('SocialService: [3/4] users/$uid write FAILED: $e');
      return false;
    }
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_kDisplayNamePrefsKey, displayName);
    return true;
  }

  // ---------------------------------------------------------------------------
  // Groups
  // ---------------------------------------------------------------------------

  /// Create a group. Provisions anonymous auth + profile if needed.
  ///
  /// Returns null on any failure (offline, etc.) — caller shows an error/retry.
  Future<SocialGroup?> createGroup({
    required String groupName,
    required String displayName,
  }) async {
    final uid = await ensureSignedIn();
    if (uid == null) return null;
    if (!await setDisplayName(uid, displayName)) return null;
    try {
      debugPrint('SocialService: [4/4] groups/{id} + codes/{code} write starting…');
      final group = await _client.createGroup(uid: uid, name: groupName).timeout(_kSocialOpTimeout);
      debugPrint('SocialService: [4/4] group created (id=${group.id}, code=${group.code}).');
      return group;
    } catch (e) {
      debugPrint('SocialService: [4/4] createGroup FAILED: $e');
      return null;
    }
  }

  /// Resolve a join code to its group WITHOUT joining — used by the deep-link
  /// confirm screen to show the group name before the player commits.
  /// Provisions anonymous auth (silent) since previewing a group is itself a
  /// social action.
  ///
  /// Returns a [JoinCodeResult] rather than a bare nullable group so the
  /// caller can distinguish "code genuinely doesn't exist" from "couldn't
  /// reach Firebase" — conflating those into one null used to make an
  /// offline/timeout failure show a misleading "invalid or expired link"
  /// message instead of a retryable connection error.
  Future<JoinCodeResult> previewGroupForCode(String code) async {
    final uid = await ensureSignedIn();
    if (uid == null) {
      return const JoinCodeResult(status: JoinCodeStatus.offline);
    }
    try {
      final groupId = await _client.resolveCode(code.trim().toUpperCase()).timeout(_kSocialOpTimeout);
      if (groupId == null) {
        return const JoinCodeResult(status: JoinCodeStatus.codeNotFound);
      }
      final group = await _client.getGroup(groupId).timeout(_kSocialOpTimeout);
      if (group == null) {
        return const JoinCodeResult(status: JoinCodeStatus.codeNotFound);
      }
      return JoinCodeResult(status: JoinCodeStatus.success, group: group);
    } catch (e) {
      debugPrint('SocialService: previewGroupForCode failed: $e');
      return const JoinCodeResult(status: JoinCodeStatus.offline);
    }
  }

  /// Join a group by its shareable code. Provisions anonymous auth + profile
  /// if needed (first-time-user deep-link path).
  Future<JoinCodeResult> joinByCode({
    required String code,
    required String displayName,
  }) async {
    final uid = await ensureSignedIn();
    if (uid == null) {
      return const JoinCodeResult(status: JoinCodeStatus.offline);
    }
    try {
      final groupId = await _client.resolveCode(code.trim().toUpperCase()).timeout(_kSocialOpTimeout);
      if (groupId == null) {
        return const JoinCodeResult(status: JoinCodeStatus.codeNotFound);
      }
      if (!await setDisplayName(uid, displayName)) {
        return const JoinCodeResult(status: JoinCodeStatus.offline);
      }
      await _client.joinGroup(groupId: groupId, uid: uid).timeout(_kSocialOpTimeout);
      final group = await _client.getGroup(groupId).timeout(_kSocialOpTimeout);
      return JoinCodeResult(status: JoinCodeStatus.success, group: group);
    } catch (e) {
      debugPrint('SocialService: joinByCode failed: $e');
      return const JoinCodeResult(status: JoinCodeStatus.offline);
    }
  }

  /// All groups the signed-in player belongs to. Empty (never throws) if
  /// there's no local identity yet or the fetch fails.
  Future<List<SocialGroup>> myGroups() async {
    if (!hasLocalIdentity) return [];
    final uid = _client.currentUid!;
    try {
      return await _client.myGroups(uid).timeout(_kSocialOpTimeout);
    } catch (e) {
      debugPrint('SocialService: myGroups failed: $e');
      return [];
    }
  }

  // ---------------------------------------------------------------------------
  // Results + leaderboard
  // ---------------------------------------------------------------------------

  /// Write today's result to every group the player belongs to.
  ///
  /// Fully self-healing: never throws, never blocks the win/loss screen.
  /// A permission-denied re-write (result already recorded for today) is
  /// treated as a benign no-op, matching the create-only rules contract.
  Future<void> writeResultToAllGroups({
    required String date,
    required String outcome,
    required int guessesUsed,
    required int par,
    required int scoreVsPar,
    required String lang,
  }) async {
    if (!hasLocalIdentity) return; // no social identity — nothing to do.
    final uid = _client.currentUid!;
    try {
      final displayName = await cachedDisplayName();
      if (displayName == null) return; // no profile yet; shouldn't happen post-join.

      final groups = await _client.myGroups(uid).timeout(_kSocialOpTimeout);
      for (final group in groups) {
        try {
          await _client.writeResult(
            groupId: group.id,
            date: date,
            uid: uid,
            displayName: displayName,
            outcome: outcome,
            guessesUsed: guessesUsed,
            par: par,
            scoreVsPar: scoreVsPar,
            lang: lang,
          ).timeout(_kSocialOpTimeout);
        } catch (e) {
          // Already recorded today (create-only rules deny the re-write) or
          // a transient error — log and move on to the next group.
          debugPrint('SocialService: writeResult failed for group ${group.id}: $e');
        }
      }
    } catch (e) {
      debugPrint('SocialService: writeResultToAllGroups failed: $e');
    }
  }

  /// Ranked leaderboard for one group/day, with "not played yet" rows
  /// synthesized for members that have no result doc. Spoiler-safe: those
  /// rows carry no outcome/score fields.
  Future<List<LeaderboardEntry>> leaderboardFor({
    required String groupId,
    required String date,
  }) async {
    final group = await _client.getGroup(groupId).timeout(_kSocialOpTimeout);
    if (group == null) return [];

    final results =
        await _client.fetchResults(groupId: groupId, date: date).timeout(_kSocialOpTimeout);

    final entries = <LeaderboardEntry>[];
    for (final memberUid in group.memberUids) {
      final existing = results[memberUid];
      if (existing != null) {
        entries.add(existing);
        continue;
      }
      final name =
          await _client.getDisplayName(memberUid).timeout(_kSocialOpTimeout) ?? 'Anonymous';
      entries.add(LeaderboardEntry(uid: memberUid, displayName: name, played: false));
    }
    return rankLeaderboard(entries);
  }
}

/// Construct the default [SocialService]. The optional [client] parameter
/// allows tests to inject a fake without touching Firebase.
SocialService buildSocialService({
  SocialClient? client,
  Future<bool> Function()? firebaseInitializer,
}) =>
    SocialService(client: client, firebaseInitializer: firebaseInitializer);
