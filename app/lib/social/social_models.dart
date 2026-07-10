/// Value types for the 6a Social feature (groups + daily leaderboards).
///
/// These are plain Dart classes — no Firestore/Auth SDK types leak out of
/// [SocialClient] (see social_client.dart), mirroring the thin-client
/// injection pattern used by [AnalyticsExporter] / [IapGateway].
library;

/// A friend group. Membership is by uid; display names live on [users/{uid}]
/// and are resolved separately (see [LeaderboardEntry]).
class SocialGroup {
  const SocialGroup({
    required this.id,
    required this.name,
    required this.code,
    required this.createdBy,
    required this.memberUids,
  });

  /// Firestore document ID (`groups/{id}`).
  final String id;

  /// Creator-chosen group name.
  final String name;

  /// Short shareable join code (`codes/{code}` -> this group).
  final String code;

  /// uid of the group's creator.
  final String createdBy;

  /// All member uids, including the creator.
  final List<String> memberUids;

  /// Shareable join link for this group.
  String get joinLink => 'https://playwarmer.vercel.app/join/$code';
}

/// One row in a per-group, per-day leaderboard.
///
/// Spoiler-safe by construction: this type never carries guesses or the
/// secret word — only the outcome/score fields defined in spec.md #6a.
class LeaderboardEntry {
  const LeaderboardEntry({
    required this.uid,
    required this.displayName,
    required this.played,
    this.outcome,
    this.guessesUsed,
    this.par,
    this.scoreVsPar,
    this.lang,
    this.finishedAt,
  });

  final String uid;
  final String displayName;

  /// False when this member has no result doc for the day yet — i.e. a
  /// missing Firestore document, not merely a zero/empty one. Rendered as
  /// "not played yet" and MUST NOT be spoiled with any outcome data.
  final bool played;

  /// 'win' or 'loss'; null when [played] is false.
  final String? outcome;
  final int? guessesUsed;
  final int? par;
  final int? scoreVsPar;
  final String? lang;
  final DateTime? finishedAt;

  bool get isWin => outcome == 'win';

  /// Ranking key: wins sort by fewest guesses (best first); losses and
  /// not-played sort after all wins. Lower is better within wins.
  ///
  /// Used by [rankLeaderboard] — exposed here as a pure comparator so it's
  /// unit-testable without any Firestore round-trip.
  static int compare(LeaderboardEntry a, LeaderboardEntry b) {
    int tier(LeaderboardEntry e) {
      if (e.isWin) return 0;
      if (e.played) return 1; // loss
      return 2; // not played yet
    }

    final ta = tier(a);
    final tb = tier(b);
    if (ta != tb) return ta.compareTo(tb);
    if (ta == 0) {
      // Both wins: fewest guesses first (guessesUsed is non-null for wins).
      return (a.guessesUsed ?? 1 << 30).compareTo(b.guessesUsed ?? 1 << 30);
    }
    // Losses / not-played: stable by display name for determinism.
    return a.displayName.compareTo(b.displayName);
  }
}

/// Sort [entries] per the leaderboard ranking rules (see [LeaderboardEntry.compare]).
///
/// Pure function — safe to unit-test without Flutter/Firestore context.
List<LeaderboardEntry> rankLeaderboard(List<LeaderboardEntry> entries) {
  final sorted = List<LeaderboardEntry>.from(entries)
    ..sort(LeaderboardEntry.compare);
  return sorted;
}
