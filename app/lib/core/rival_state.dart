import 'package:mindmeld/core/models.dart';

/// The rival's display name — light personality only (spec-warmer-closeout.md
/// WORKSTREAM 2c: a name + a few reaction lines, deliberately NOT a
/// leaderboard/persona/progression system, since the rival is unvalidated).
/// Used only in live in-app UI (the rival strip, the win-screen badge) —
/// NOT in buildShareCard's external, tested share-text format, which stays
/// "the bot" to avoid touching a stable externally-visible string.
const String kRivalName = 'Ember';

/// Race outcome between player and rival.
enum RivalOutcome {
  racing,    // Game in progress — neither has solved yet (or rival solved, player continuing)
  playerWon, // Player reached rank 1 in strictly fewer guesses than the rival
  rivalWon,  // Rival reached rank 1 in fewer guesses than the player
  tie,       // Both reached rank 1 in exactly the same number of guesses
}

/// Live rival state, derived from current guesses and the selected tier's path.
///
/// Not persisted — recomputed on every rebuild from [DayState.guesses].
class RivalState {
  const RivalState({
    required this.guessCount,
    required this.rivalCurrentStep,
    required this.rivalBestRank,
    required this.rivalBestBand,
    required this.rivalSolved,
    required this.outcome,
    required this.solveAt,
  });

  /// Number of player guesses so far (equals rival steps revealed).
  final int guessCount;

  /// The rival's most recently revealed step, or null before the first guess.
  final RivalStep? rivalCurrentStep;

  /// Rival's best (lowest) rank in its revealed steps.
  final int rivalBestRank;

  /// Temperature band of the rival's best rank.
  final TemperatureBand rivalBestBand;

  /// Whether the rival has reached rank 1 in its revealed steps.
  final bool rivalSolved;

  /// Current race outcome.
  final RivalOutcome outcome;

  /// Total steps for the rival to solve (from payload tier data).
  final int solveAt;

  /// Build rival state from the current list of player guesses and tier data.
  static RivalState fromGuesses({
    required List<Guess> guesses,
    required RivalTierData tierData,
    required bool playerWon,
  }) {
    final path = tierData.path;
    final guessCount = guesses.length;

    // Reveal rival steps equal to the number of player guesses
    final revealedSteps =
        guessCount > 0 ? path.take(guessCount).toList() : <RivalStep>[];

    final rivalCurrentStep =
        revealedSteps.isNotEmpty ? revealedSteps.last : null;

    // Rival best rank: lowest rank seen in revealed steps
    int rivalBestRank = path.isNotEmpty ? path.first.rank : 1;
    for (final step in revealedSteps) {
      if (step.rank < rivalBestRank) rivalBestRank = step.rank;
    }
    final rivalBestBand = revealedSteps.isEmpty
        ? TemperatureBand.freezing
        : revealedSteps
            .reduce((a, b) => a.rank < b.rank ? a : b)
            .temperatureBand;

    final rivalSolved = revealedSteps.any((s) => s.rank == 1);

    final RivalOutcome outcome;
    if (!playerWon && !rivalSolved) {
      outcome = RivalOutcome.racing;
    } else if (playerWon && !rivalSolved) {
      outcome = RivalOutcome.playerWon;
    } else if (!playerWon && rivalSolved) {
      outcome = RivalOutcome.rivalWon;
    } else {
      // Both solved — compare guess counts
      if (guessCount < tierData.solveAt) {
        outcome = RivalOutcome.playerWon;
      } else if (guessCount == tierData.solveAt) {
        outcome = RivalOutcome.tie;
      } else {
        outcome = RivalOutcome.rivalWon;
      }
    }

    return RivalState(
      guessCount: guessCount,
      rivalCurrentStep: rivalCurrentStep,
      rivalBestRank: rivalBestRank,
      rivalBestBand: rivalBestBand,
      rivalSolved: rivalSolved,
      outcome: outcome,
      solveAt: tierData.solveAt,
    );
  }
}
