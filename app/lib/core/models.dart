import 'package:mindmeld/core/config.dart';

/// Temperature band for a guess based on its rank.
enum TemperatureBand {
  /// Rank 1 — the secret word itself.
  win,

  /// Very close: rank ≤ max(50, n * 0.001).
  scorching,

  /// Close: rank ≤ max(500, n * 0.01).
  hot,

  /// Nearby: rank ≤ max(900, n * 0.05).
  warm,

  /// Far: rank ≤ n * 0.25.
  cold,

  /// Very far: rank > n * 0.25.
  freezing;

  /// Human-readable label shown in the UI.
  String get label {
    switch (this) {
      case TemperatureBand.win:
        return 'You got it!';
      case TemperatureBand.scorching:
        return 'Scorching';
      case TemperatureBand.hot:
        return 'Hot';
      case TemperatureBand.warm:
        return 'Warm';
      case TemperatureBand.cold:
        return 'Cold';
      case TemperatureBand.freezing:
        return 'Freezing';
    }
  }

  /// Emoji used in share-card rendering.
  String get emoji {
    switch (this) {
      case TemperatureBand.win:
        return '🧠';
      case TemperatureBand.scorching:
        return '🟥';
      case TemperatureBand.hot:
        return '🟧';
      case TemperatureBand.warm:
        return '🟨';
      case TemperatureBand.cold:
        return '🟩';
      case TemperatureBand.freezing:
        return '🟦';
    }
  }
}

/// Determine the temperature band for [rank] given a vocab of size [n].
///
/// Thresholds (rank is 1-based, rank 1 = secret):
///   - rank == 1                          → win
///   - rank ≤ max(50, n × 0.001)         → scorching
///   - rank ≤ max(500, n × 0.01)         → hot
///   - rank ≤ max(1050, n × 0.05)        → warm
///   - rank ≤ n × 0.25                   → cold
///   - else                               → freezing
///
/// Pure function — safe to unit-test without Flutter context.
TemperatureBand bandForRank(int rank, int n) {
  if (rank == 1) return TemperatureBand.win;

  final scorchingMax = (AppConfig.scorchingFraction * n)
      .floor()
      .clamp(AppConfig.scorchingFloor, n);
  if (rank <= scorchingMax) return TemperatureBand.scorching;

  final hotMax =
      (AppConfig.hotFraction * n).floor().clamp(AppConfig.hotFloor, n);
  if (rank <= hotMax) return TemperatureBand.hot;

  final warmMax =
      (AppConfig.warmFraction * n).floor().clamp(AppConfig.warmFloor, n);
  if (rank <= warmMax) return TemperatureBand.warm;

  final coldMax = (AppConfig.coldFraction * n).floor();
  if (rank <= coldMax) return TemperatureBand.cold;

  return TemperatureBand.freezing;
}

/// A single word entry from the payload [words] map after decoding.
class WordEntry {
  const WordEntry({required this.rank, required this.qsim});

  final int rank;
  final int qsim;

  /// Dequantized cosine similarity: (qsim / 32767.5) - 1.0
  double get similarity => (qsim / 32767.5) - 1.0;
}

/// The full decoded payload for one day's puzzle.
class DailyPayload {
  const DailyPayload({
    required this.v,
    required this.lang,
    required this.date,
    required this.model,
    required this.n,
    required this.salt,
    required this.words,
    required this.hints,
    required this.s,
    this.alt = const {},
    this.rival,
    this.parGuesses,
    this.clue,
    this.maxGuesses,
    this.pack,
    this.idx,
  });

  /// Payload schema version.
  final int v;

  /// Language key, e.g. "en" or "hi-en".
  final String lang;

  /// Puzzle date string, e.g. "2026-06-12".
  final String date;

  /// Model name used to generate the payload.
  final String model;

  /// Vocabulary size — used for rank threshold computation.
  final int n;

  /// Per-(date,lang) salt, 16 hex chars.
  final String salt;

  /// Word lookup: 12-char hash → [rank, qsim].
  final Map<String, WordEntry> words;

  /// Alt-spelling lookup (hi-en only): hash of normalized variant → [rank, qsim]
  /// of the canonical word. Absent in non-hi-en payloads; defaults to empty map.
  final Map<String, WordEntry> alt;

  /// Ordered hint list: each entry is [rank, plaintext_word].
  final List<({int rank, String word})> hints;

  /// Obfuscated secret field (base64-encoded XOR).
  final String s;

  /// Rival precomputed paths; null for pre-v2 payloads.
  final RivalData? rival;

  /// Par guess count; null for pre-v2 payloads.
  final int? parGuesses;

  /// Optional clue string shown to the player from the start of the puzzle.
  /// Null for pre-v3 payloads.
  final String? clue;

  /// Maximum guesses (guesses + hints) before budget exhaustion triggers a
  /// loss. Null for pre-v3 payloads (no budget limit).
  final int? maxGuesses;

  /// Themed-pack id this puzzle belongs to (phase 6c); null for daily payloads.
  final String? pack;

  /// 1-based puzzle index within [pack] (phase 6c); null for daily payloads.
  final int? idx;

  factory DailyPayload.fromJson(Map<String, dynamic> json) {
    final rawWords = json['words'] as Map<String, dynamic>;
    final words = rawWords.map((hash, value) {
      final list = value as List<dynamic>;
      return MapEntry(
        hash,
        WordEntry(rank: list[0] as int, qsim: list[1] as int),
      );
    });

    // Parse optional alt map; absent in en payloads and older hi-en payloads.
    final Map<String, WordEntry> alt;
    if (json.containsKey('alt')) {
      final rawAlt = json['alt'] as Map<String, dynamic>;
      alt = rawAlt.map((hash, value) {
        final list = value as List<dynamic>;
        return MapEntry(
          hash,
          WordEntry(rank: list[0] as int, qsim: list[1] as int),
        );
      });
    } else {
      alt = const {};
    }

    final rawHints = json['hints'] as List<dynamic>;
    final hints = rawHints.map((h) {
      final list = h as List<dynamic>;
      return (rank: list[0] as int, word: list[1] as String);
    }).toList();

    // v2+ optional fields — present only when v >= 2.
    RivalData? rival;
    int? parGuesses;
    if ((json['v'] as int) >= 2) {
      if (json.containsKey('rival')) {
        rival = RivalData.fromJson(json['rival'] as Map<String, dynamic>);
      }
      parGuesses = json['parGuesses'] as int?;
    }

    // v3+ optional fields — clue and budget cap.
    String? clue;
    int? maxGuesses;
    if ((json['v'] as int) >= 3) {
      clue = json['clue'] as String?;
      maxGuesses = json['maxGuesses'] as int?;
    }

    return DailyPayload(
      v: json['v'] as int,
      lang: json['lang'] as String,
      date: json['date'] as String,
      model: json['model'] as String,
      n: json['n'] as int,
      salt: json['salt'] as String,
      words: words,
      alt: alt,
      hints: hints,
      s: json['s'] as String,
      rival: rival,
      parGuesses: parGuesses,
      clue: clue,
      maxGuesses: maxGuesses,
      // Phase 6c themed-pack fields — absent on daily payloads.
      pack: json['pack'] as String?,
      idx: json['idx'] as int?,
    );
  }
}

/// A single player guess with its result.
class Guess {
  const Guess({
    required this.word,
    required this.rank,
    required this.similarity,
    required this.band,
  });

  final String word;
  final int rank;
  final double similarity;
  final TemperatureBand band;
}

/// Player statistics persisted across sessions.
class PlayerStats {
  const PlayerStats({
    required this.played,
    required this.wins,
    required this.currentStreak,
    required this.maxStreak,
    required this.guessDistribution,
  });

  final int played;
  final int wins;
  final int currentStreak;
  final int maxStreak;

  /// Map of guess count → win count, e.g. {"5": 3, "12": 1}.
  final Map<String, int> guessDistribution;

  double get winPct => played == 0 ? 0 : wins / played;

  PlayerStats copyWith({
    int? played,
    int? wins,
    int? currentStreak,
    int? maxStreak,
    Map<String, int>? guessDistribution,
  }) {
    return PlayerStats(
      played: played ?? this.played,
      wins: wins ?? this.wins,
      currentStreak: currentStreak ?? this.currentStreak,
      maxStreak: maxStreak ?? this.maxStreak,
      guessDistribution: guessDistribution ?? this.guessDistribution,
    );
  }

  static const empty = PlayerStats(
    played: 0,
    wins: 0,
    currentStreak: 0,
    maxStreak: 0,
    guessDistribution: {},
  );
}

/// A revealed hint entry stored in [DayState.revealedHints].
///
/// Mirrors the shape of [DailyPayload.hints] elements so serialisation is
/// straightforward.
class RevealedHint {
  const RevealedHint({required this.rank, required this.word});

  final int rank;
  final String word;
}

/// Persisted daily game state for one (date, lang) pair.
class DayState {
  const DayState({
    required this.date,
    required this.lang,
    required this.guesses,
    required this.hintsUsed,
    required this.won,
    required this.gaveUp,
    this.revealedHints = const [],
  });

  final String date;
  final String lang;
  final List<Guess> guesses;
  final int hintsUsed;
  final bool won;
  final bool gaveUp;

  /// Hints the player has revealed, in the order they were unlocked.
  ///
  /// Pinned tiles are sorted by rank (lowest = closest to secret = top) in the
  /// UI; the list itself retains insertion order for serialisation fidelity.
  final List<RevealedHint> revealedHints;

  bool get isFinished => won || gaveUp;

  DayState copyWith({
    List<Guess>? guesses,
    int? hintsUsed,
    bool? won,
    bool? gaveUp,
    List<RevealedHint>? revealedHints,
  }) {
    return DayState(
      date: date,
      lang: lang,
      guesses: guesses ?? this.guesses,
      hintsUsed: hintsUsed ?? this.hintsUsed,
      won: won ?? this.won,
      gaveUp: gaveUp ?? this.gaveUp,
      revealedHints: revealedHints ?? this.revealedHints,
    );
  }
}

/// Persisted game state for one themed-pack puzzle (phase 6c).
///
/// Mirrors [DayState]'s shape exactly but is keyed by (packId, idx, lang)
/// instead of (date, lang), and is persisted to a dedicated `pack_progress`
/// table/store — never `day_state` or `stats` — so pack play can never affect
/// the daily streak or stats.
class PackPuzzleState {
  const PackPuzzleState({
    required this.packId,
    required this.idx,
    required this.lang,
    required this.guesses,
    required this.hintsUsed,
    required this.won,
    required this.gaveUp,
    this.revealedHints = const [],
  });

  final String packId;
  final int idx;
  final String lang;
  final List<Guess> guesses;
  final int hintsUsed;
  final bool won;
  final bool gaveUp;
  final List<RevealedHint> revealedHints;

  bool get isFinished => won || gaveUp;

  PackPuzzleState copyWith({
    List<Guess>? guesses,
    int? hintsUsed,
    bool? won,
    bool? gaveUp,
    List<RevealedHint>? revealedHints,
  }) {
    return PackPuzzleState(
      packId: packId,
      idx: idx,
      lang: lang,
      guesses: guesses ?? this.guesses,
      hintsUsed: hintsUsed ?? this.hintsUsed,
      won: won ?? this.won,
      gaveUp: gaveUp ?? this.gaveUp,
      revealedHints: revealedHints ?? this.revealedHints,
    );
  }
}

/// A single step in the rival's precomputed path.
///
/// Contains only rank and band ordinal — no word strings (spoiler-safe).
class RivalStep {
  const RivalStep({required this.rank, required this.band});

  final int rank;

  /// TemperatureBand ordinal: 0=win, 1=scorching, 2=hot, 3=warm, 4=cold, 5=freezing.
  final int band;

  TemperatureBand get temperatureBand =>
      TemperatureBand.values[band.clamp(0, TemperatureBand.values.length - 1)];

  factory RivalStep.fromJson(Map<String, dynamic> json) => RivalStep(
        rank: json['rank'] as int,
        band: json['band'] as int,
      );
}

/// Precomputed path data for one difficulty tier.
class RivalTierData {
  const RivalTierData({required this.path, required this.solveAt});

  final List<RivalStep> path;

  /// Step count for the rival to solve (= path.length).
  final int solveAt;

  factory RivalTierData.fromJson(Map<String, dynamic> json) {
    final rawPath = json['path'] as List<dynamic>;
    return RivalTierData(
      path: rawPath
          .map((s) => RivalStep.fromJson(s as Map<String, dynamic>))
          .toList(),
      solveAt: json['solveAt'] as int,
    );
  }
}

/// All rival data for one day's puzzle (three difficulty tiers).
class RivalData {
  const RivalData({
    required this.even,
    required this.chill,
    required this.sharp,
  });

  final RivalTierData even;
  final RivalTierData chill;
  final RivalTierData sharp;

  RivalTierData forTier(String tier) {
    switch (tier) {
      case 'chill':
        return chill;
      case 'sharp':
        return sharp;
      default:
        return even;
    }
  }

  factory RivalData.fromJson(Map<String, dynamic> json) => RivalData(
        even: RivalTierData.fromJson(json['even'] as Map<String, dynamic>),
        chill: RivalTierData.fromJson(json['chill'] as Map<String, dynamic>),
        sharp: RivalTierData.fromJson(json['sharp'] as Map<String, dynamic>),
      );
}
