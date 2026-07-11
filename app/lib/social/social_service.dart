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

import 'package:mindmeld/analytics/app_check_init.dart';
import 'package:mindmeld/analytics/firebase_web_options.dart';
import 'package:mindmeld/social/moderation_blocklist.dart' show isBlockedName;
import 'package:mindmeld/social/name_sanitizer.dart';
import 'package:mindmeld/social/social_client.dart';
import 'package:mindmeld/social/social_models.dart';

export 'package:mindmeld/social/name_sanitizer.dart' show NameRejectionReason, NameSanitizeResult;

const String _kDisplayNamePrefsKey = 'social_display_name';

/// Max length for a display name — MUST match firestore.rules'
/// `isValidDisplayName()` bound (1-40 chars).
const int kDisplayNameMaxLength = 40;

/// Max length for a group name — MUST match firestore.rules' group-create
/// rule bound (1-60 chars).
const int kGroupNameMaxLength = 60;

/// Sanitize + moderate a raw display/group name: strips control/zero-width/
/// bidi characters, enforces [maxLength], then checks the profanity/
/// reserved-word blocklist (with homoglyph folding — see
/// `name_sanitizer.dart` and `moderation_blocklist.dart`).
///
/// Public so UI callers (see `display_name_dialog.dart`) can pre-validate
/// and re-prompt with immediate inline feedback. [setDisplayName] and
/// [SocialService.createGroup] run this SAME check again at the actual
/// write choke point — this function is a UX convenience, not a substitute
/// for that enforcement (a caller could skip it entirely and the service
/// would still reject an invalid name).
NameSanitizeResult validateName(String raw, {required int maxLength}) {
  final sanitized = sanitizeName(raw, maxLength: maxLength);
  if (!sanitized.isOk) return sanitized;
  if (isBlockedName(sanitized.cleaned!)) {
    return const NameSanitizeResult.rejected(NameRejectionReason.blocked);
  }
  return sanitized;
}

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

  /// The display name failed sanitization/moderation (see [validateName]).
  rejectedName,
}

class JoinCodeResult {
  const JoinCodeResult({required this.status, this.group});

  final JoinCodeStatus status;
  final SocialGroup? group;
}

/// Outcome of a display-name write (see [SocialService.setDisplayName]).
enum SetDisplayNameStatus {
  /// Saved both locally and to the profile doc.
  success,

  /// Failed sanitization/moderation (see [validateName]) — never reached
  /// the network.
  rejectedName,

  /// Could not reach Firebase (offline / misconfigured) — degrade gently.
  offline,
}

class SetDisplayNameResult {
  const SetDisplayNameResult(this.status);

  final SetDisplayNameStatus status;

  bool get isSuccess => status == SetDisplayNameStatus.success;
}

/// Outcome of a create-group attempt (see [SocialService.createGroup]).
enum CreateGroupStatus {
  /// Created successfully.
  success,

  /// The group name or display name failed sanitization/moderation (see
  /// [validateName]).
  rejectedName,

  /// Could not reach Firebase (offline / misconfigured) — degrade gently.
  offline,
}

class CreateGroupResult {
  const CreateGroupResult({required this.status, this.group});

  final CreateGroupStatus status;
  final SocialGroup? group;
}

/// Outcome of a "delete my data" attempt (see [SocialService.deleteMyData]).
enum DeleteMyDataStatus {
  /// Deleted (see [SocialService.deleteMyData]'s doc comment for exactly
  /// what "deleted" covers).
  success,

  /// There was no local identity to delete in the first place — a no-op.
  notSignedIn,

  /// Could not reach Firebase (offline / misconfigured) — degrade gently;
  /// nothing was partially deleted in a way the UI needs to reconcile
  /// (each step is itself idempotent/retry-safe).
  offline,
}

class DeleteMyDataResult {
  const DeleteMyDataResult(this.status);

  final DeleteMyDataStatus status;

  bool get isSuccess => status == DeleteMyDataStatus.success;
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

  /// True if Firebase has ALREADY been initialised by some other explicit
  /// action — zero network calls, and critically, never triggers
  /// initialisation itself. Same local-only re-derivation as
  /// [hasLocalIdentity] (see its doc comment), extracted as its own getter
  /// for 6b: [NotificationService.currentPermission] is reachable from
  /// `initState` of screens main.dart mounts eagerly via `IndexedStack`
  /// (Settings — always; the win/loss opt-in card — on every win/loss), so
  /// it must be able to answer honestly WITHOUT provisioning Firebase for a
  /// player who has touched neither Social nor Notifications yet. Contrast
  /// with [ensureFirebaseReady], which DOES trigger initialisation — correct
  /// for [ensureSignedIn] and [NotificationService.optIn], both only ever
  /// called after an explicit user action.
  bool get isFirebaseReadyLocally {
    if (!_firebaseReady) _firebaseReady = Firebase.apps.isNotEmpty;
    return _firebaseReady;
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
      await ensureAppCheckActivated();
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
      await ensureAppCheckActivated();
      return true;
    } catch (e) {
      debugPrint('SocialService: [1/4] Firebase.initializeApp() FAILED: $e');
      return false;
    }
  }

  /// Ensure `Firebase.initializeApp()` has run — WITHOUT signing in.
  ///
  /// Added for 6b: [NotificationClient.currentPermission] (checking browser
  /// notification permission status) needs a live [FirebaseApp] to resolve
  /// `FirebaseMessaging.instance` against, but must NOT force an anonymous
  /// sign-in just to read local status — that would make merely opening the
  /// Settings tab (mounted eagerly by main.dart's `IndexedStack`, well before
  /// any explicit social/notification action) silently provision an identity
  /// for every visitor, violating the "Firebase touched only on explicit
  /// action" invariant far more than the bug this fixes. Returns false on any
  /// failure (offline, misconfigured, timed out) — never throws. Idempotent
  /// and safe to call from multiple independent [SocialService]/
  /// [NotificationService] instances (see [hasLocalIdentity]'s doc comment
  /// for why re-deriving from [Firebase.apps] rather than trusting a
  /// per-instance cache matters).
  Future<bool> ensureFirebaseReady() async {
    if (!_firebaseReady) _firebaseReady = Firebase.apps.isNotEmpty;
    if (!_firebaseReady) {
      _firebaseReady = await _firebaseInitializer();
    }
    return _firebaseReady;
  }

  /// Silently provision (or resume) an anonymous identity. Returns null on
  /// any failure (offline, misconfigured, timed out) — never throws.
  Future<String?> ensureSignedIn() async {
    if (!await ensureFirebaseReady()) return null;
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
  /// Must be called after [ensureSignedIn] has produced a uid. Sanitizes and
  /// moderates [displayName] first (see [validateName]) — a name that fails
  /// that check is rejected WITHOUT ever reaching the client/network, and
  /// never cached locally either.
  Future<SetDisplayNameResult> setDisplayName(String uid, String displayName) async {
    final validated = validateName(displayName, maxLength: kDisplayNameMaxLength);
    if (!validated.isOk) {
      return const SetDisplayNameResult(SetDisplayNameStatus.rejectedName);
    }
    final cleaned = validated.cleaned!;
    try {
      debugPrint('SocialService: [3/4] users/$uid write starting…');
      await _client.setDisplayName(uid: uid, displayName: cleaned).timeout(_kSocialOpTimeout);
      debugPrint('SocialService: [3/4] users/$uid write done.');
    } catch (e) {
      debugPrint('SocialService: [3/4] users/$uid write FAILED: $e');
      return const SetDisplayNameResult(SetDisplayNameStatus.offline);
    }
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_kDisplayNamePrefsKey, cleaned);
    return const SetDisplayNameResult(SetDisplayNameStatus.success);
  }

  // ---------------------------------------------------------------------------
  // Groups
  // ---------------------------------------------------------------------------

  /// Create a group. Provisions anonymous auth + profile if needed.
  ///
  /// Sanitizes and moderates [groupName] first (see [validateName]) —
  /// rejected WITHOUT ever reaching the network. [displayName] gets the same
  /// treatment via [setDisplayName].
  Future<CreateGroupResult> createGroup({
    required String groupName,
    required String displayName,
  }) async {
    final validatedGroupName = validateName(groupName, maxLength: kGroupNameMaxLength);
    if (!validatedGroupName.isOk) {
      return const CreateGroupResult(status: CreateGroupStatus.rejectedName);
    }
    final uid = await ensureSignedIn();
    if (uid == null) return const CreateGroupResult(status: CreateGroupStatus.offline);
    final nameResult = await setDisplayName(uid, displayName);
    switch (nameResult.status) {
      case SetDisplayNameStatus.rejectedName:
        return const CreateGroupResult(status: CreateGroupStatus.rejectedName);
      case SetDisplayNameStatus.offline:
        return const CreateGroupResult(status: CreateGroupStatus.offline);
      case SetDisplayNameStatus.success:
        break;
    }
    try {
      debugPrint('SocialService: [4/4] groups/{id} + codes/{code} write starting…');
      final group = await _client
          .createGroup(uid: uid, name: validatedGroupName.cleaned!)
          .timeout(_kSocialOpTimeout);
      debugPrint('SocialService: [4/4] group created (id=${group.id}, code=${group.code}).');
      return CreateGroupResult(status: CreateGroupStatus.success, group: group);
    } catch (e) {
      debugPrint('SocialService: [4/4] createGroup FAILED: $e');
      return const CreateGroupResult(status: CreateGroupStatus.offline);
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
      final nameResult = await setDisplayName(uid, displayName);
      switch (nameResult.status) {
        case SetDisplayNameStatus.rejectedName:
          return const JoinCodeResult(status: JoinCodeStatus.rejectedName);
        case SetDisplayNameStatus.offline:
          return const JoinCodeResult(status: JoinCodeStatus.offline);
        case SetDisplayNameStatus.success:
          break;
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

  // ---------------------------------------------------------------------------
  // Data deletion (Play/GDPR)
  // ---------------------------------------------------------------------------

  /// "Delete my data": removes the player's server-side social identity.
  ///
  /// Concretely deletes/removes, in this order (order matters — see
  /// [SocialClient.deleteOwnResultsBestEffort]'s doc comment):
  ///   1. Every past result doc (score + displayName) this uid wrote, across
  ///      every group/day, on a BEST-EFFORT basis (a collection-group query
  ///      that may need a one-time production index — failures here are
  ///      logged and non-fatal, never block steps 2-4).
  ///   2. This uid's own entry in every group's `memberUids` (leave every
  ///      group).
  ///   3. The `users/{uid}` profile doc itself (displayName, notification
  ///      subscription state, etc).
  ///   4. The locally-cached display name (SharedPreferences).
  ///
  /// Returns [DeleteMyDataStatus.notSignedIn] as a no-op when there is no
  /// local identity at all — nothing to delete. Returns
  /// [DeleteMyDataStatus.offline] if the CORE deletion (steps 2-4) fails;
  /// step 1 failing alone still counts as [DeleteMyDataStatus.success]
  /// since it's explicitly best-effort (see docs/privacy-policy.md for what
  /// this does and doesn't cover).
  ///
  /// Root-caused live 2026-07-11: this used to gate on [hasLocalIdentity]
  /// alone, which is false on every fresh page load until Firebase is
  /// explicitly initialised THIS session (by design — see this class's own
  /// "degradation guarantee" doc comment). A RETURNING social user who opens
  /// Settings and taps "Delete my data" without first taking another social
  /// action in the same session hit that false negative and got told there
  /// was "nothing to delete," when in fact their profile/group data was
  /// still live server-side. [cachedDisplayName] is a local, zero-network
  /// SharedPreferences read that survives across page loads (unlike
  /// [hasLocalIdentity]), so it correctly distinguishes "never used Social,
  /// ever" from "used it before, just haven't re-initialised Firebase this
  /// load yet." [ensureSignedIn] is safe to call here even when already
  /// signed in — [SocialClient.signInAnonymously] returns the EXISTING
  /// persisted uid rather than minting a new one (verified live: the same
  /// uid was recovered after a full fresh browser-process reload of a
  /// persisted profile) — so this can never orphan the original identity.
  Future<DeleteMyDataResult> deleteMyData() async {
    if (!hasLocalIdentity && await cachedDisplayName() == null) {
      return const DeleteMyDataResult(DeleteMyDataStatus.notSignedIn);
    }
    final uid = await ensureSignedIn();
    if (uid == null) {
      return const DeleteMyDataResult(DeleteMyDataStatus.offline);
    }

    try {
      await _client.deleteOwnResultsBestEffort(uid).timeout(_kSocialOpTimeout);
    } catch (e) {
      // Best-effort by design -- log and continue to the steps that matter
      // most (profile + membership deletion below).
      debugPrint('SocialService: deleteOwnResultsBestEffort failed (non-fatal): $e');
    }

    try {
      final groups = await _client.myGroups(uid).timeout(_kSocialOpTimeout);
      for (final group in groups) {
        await _client.removeSelfFromGroup(groupId: group.id, uid: uid).timeout(_kSocialOpTimeout);
      }
      await _client.deleteOwnProfile(uid).timeout(_kSocialOpTimeout);
    } catch (e) {
      debugPrint('SocialService: deleteMyData FAILED: $e');
      return const DeleteMyDataResult(DeleteMyDataStatus.offline);
    }

    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_kDisplayNamePrefsKey);
    return const DeleteMyDataResult(DeleteMyDataStatus.success);
  }
}

/// Construct the default [SocialService]. The optional [client] parameter
/// allows tests to inject a fake without touching Firebase.
SocialService buildSocialService({
  SocialClient? client,
  Future<bool> Function()? firebaseInitializer,
}) =>
    SocialService(client: client, firebaseInitializer: firebaseInitializer);
