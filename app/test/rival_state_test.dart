import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/rival_state.dart';

void main() {
  RivalTierData makeTierData() => RivalTierData(
        path: [
          RivalStep(rank: 10000, band: 5),
          RivalStep(rank: 3000, band: 4),
          RivalStep(rank: 800, band: 3),
          RivalStep(rank: 100, band: 2),
          RivalStep(rank: 1, band: 0),
        ],
        solveAt: 5,
      );

  Guess makeGuess(int rank, TemperatureBand band) => Guess(
        word: 'word$rank',
        rank: rank,
        similarity: 0.5,
        band: band,
      );

  group('RivalState.fromGuesses', () {
    test('racing when no guesses', () {
      final state = RivalState.fromGuesses(
          guesses: [], tierData: makeTierData(), playerWon: false);
      expect(state.outcome, RivalOutcome.racing);
      expect(state.guessCount, 0);
      expect(state.rivalSolved, false);
      expect(state.rivalCurrentStep, isNull);
    });

    test('racing after 2 guesses on 5-step path', () {
      final guesses =
          List.generate(2, (i) => makeGuess(5000 - i * 100, TemperatureBand.cold));
      final state = RivalState.fromGuesses(
          guesses: guesses, tierData: makeTierData(), playerWon: false);
      expect(state.outcome, RivalOutcome.racing);
      expect(state.rivalSolved, false);
    });

    test('rival current step is latest revealed', () {
      final guesses =
          List.generate(2, (i) => makeGuess(5000, TemperatureBand.cold));
      final state = RivalState.fromGuesses(
          guesses: guesses, tierData: makeTierData(), playerWon: false);
      // path[1].rank == 3000
      expect(state.rivalCurrentStep?.rank, 3000);
    });

    test('rival best rank tracks lowest seen', () {
      // After 3 guesses: revealed path[0]=10000, path[1]=3000, path[2]=800
      final guesses =
          List.generate(3, (i) => makeGuess(5000, TemperatureBand.cold));
      final state = RivalState.fromGuesses(
          guesses: guesses, tierData: makeTierData(), playerWon: false);
      expect(state.rivalBestRank, 800);
    });

    test('rival solved after all 5 steps revealed', () {
      final guesses =
          List.generate(5, (i) => makeGuess(5000 - i * 100, TemperatureBand.cold));
      final state = RivalState.fromGuesses(
          guesses: guesses, tierData: makeTierData(), playerWon: false);
      expect(state.rivalSolved, true);
      expect(state.outcome, RivalOutcome.rivalWon);
    });

    test('player wins before rival: playerWon', () {
      // Player wins on guess 3; rival solves at step 5
      final guesses =
          List.generate(3, (i) => makeGuess(i + 2, TemperatureBand.hot));
      final state = RivalState.fromGuesses(
          guesses: guesses, tierData: makeTierData(), playerWon: true);
      expect(state.outcome, RivalOutcome.playerWon);
    });

    test('tie when both solve at same step count', () {
      // Player wins on guess 5; rival solves at step 5
      final guesses =
          List.generate(5, (i) => makeGuess(i + 2, TemperatureBand.hot));
      final state = RivalState.fromGuesses(
          guesses: guesses, tierData: makeTierData(), playerWon: true);
      expect(state.outcome, RivalOutcome.tie);
    });

    test('rival won when player needs more guesses', () {
      // Player at guess 7 (rival solved at 5) without winning
      final guesses =
          List.generate(7, (i) => makeGuess(1000 - i * 50, TemperatureBand.cold));
      final state = RivalState.fromGuesses(
          guesses: guesses, tierData: makeTierData(), playerWon: false);
      expect(state.rivalSolved, true);
      expect(state.outcome, RivalOutcome.rivalWon);
    });

    test('solveAt matches tier data', () {
      final state = RivalState.fromGuesses(
          guesses: [], tierData: makeTierData(), playerWon: false);
      expect(state.solveAt, 5);
    });

    test('rival best band matches lowest rank step band', () {
      // After 3 guesses: best step is path[2] (rank 800, band 3 = warm)
      final guesses =
          List.generate(3, (i) => makeGuess(5000, TemperatureBand.cold));
      final state = RivalState.fromGuesses(
          guesses: guesses, tierData: makeTierData(), playerWon: false);
      expect(state.rivalBestBand, TemperatureBand.warm);
    });
  });

  group('RivalStep.temperatureBand', () {
    test('band 0 is win', () {
      expect(RivalStep(rank: 1, band: 0).temperatureBand, TemperatureBand.win);
    });
    test('band 5 is freezing', () {
      expect(
          RivalStep(rank: 10000, band: 5).temperatureBand, TemperatureBand.freezing);
    });
    test('out-of-range band is clamped', () {
      // band 99 → clamped to 5 (freezing)
      expect(
          RivalStep(rank: 1, band: 99).temperatureBand, TemperatureBand.freezing);
    });
  });

  group('RivalData.forTier', () {
    test('even tier returned by default', () {
      final even = RivalTierData(path: [RivalStep(rank: 1, band: 0)], solveAt: 1);
      final chill = RivalTierData(path: [RivalStep(rank: 1, band: 0), RivalStep(rank: 1, band: 0)], solveAt: 2);
      final sharp = RivalTierData(path: [], solveAt: 0);
      final data = RivalData(even: even, chill: chill, sharp: sharp);
      expect(data.forTier('even').solveAt, 1);
      expect(data.forTier('unknown').solveAt, 1);
    });

    test('chill tier returned for chill', () {
      final even = RivalTierData(path: [], solveAt: 1);
      final chill = RivalTierData(path: [], solveAt: 5);
      final sharp = RivalTierData(path: [], solveAt: 0);
      final data = RivalData(even: even, chill: chill, sharp: sharp);
      expect(data.forTier('chill').solveAt, 5);
    });
  });
}
