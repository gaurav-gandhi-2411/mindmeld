import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/core/config.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/features/win/win_screen.dart';

void main() {
  group('buildShareCard', () {
    // Helper to build a list of guesses with known bands.
    List<Guess> makeGuesses(List<TemperatureBand> bands) {
      return bands.asMap().entries.map((e) {
        return Guess(
          word: 'word${e.key}',
          rank: e.key + 2,
          similarity: 0.5,
          band: e.value,
        );
      }).toList();
    }

    test('share text contains guess count', () {
      final guesses = makeGuesses([
        TemperatureBand.freezing,
        TemperatureBand.cold,
        TemperatureBand.warm,
        TemperatureBand.hot,
        TemperatureBand.scorching,
      ]);
      final text = buildShareCard(guesses: guesses, puzzleNumber: 1);
      expect(text, contains('5 guesses'));
    });

    test('share text contains puzzle number', () {
      final guesses = makeGuesses([TemperatureBand.scorching]);
      final text = buildShareCard(guesses: guesses, puzzleNumber: 42);
      expect(text, contains('#42'));
    });

    test('share text contains emoji grid', () {
      final guesses = makeGuesses([
        TemperatureBand.freezing,
        TemperatureBand.cold,
        TemperatureBand.warm,
        TemperatureBand.hot,
        TemperatureBand.scorching,
      ]);
      final text = buildShareCard(guesses: guesses, puzzleNumber: 1);
      expect(text, contains('🟦')); // freezing
      expect(text, contains('🟩')); // cold
      expect(text, contains('🟨')); // warm
      expect(text, contains('🟧')); // hot
      expect(text, contains('🟥')); // scorching
    });

    test('share text does NOT contain secret word "ocean"', () {
      final guesses = makeGuesses([
        TemperatureBand.freezing,
        TemperatureBand.hot,
        TemperatureBand.scorching,
      ]);
      final text = buildShareCard(guesses: guesses, puzzleNumber: 1);
      expect(text, isNot(contains('ocean')));
    });

    test('share text does NOT contain any word from guesses list', () {
      // The actual guess words must never appear in share text.
      final guesses = [
        Guess(
          word: 'water',
          rank: 79,
          similarity: 0.558,
          band: TemperatureBand.hot,
        ),
        Guess(
          word: 'river',
          rank: 200,
          similarity: 0.48,
          band: TemperatureBand.warm,
        ),
      ];
      final text = buildShareCard(guesses: guesses, puzzleNumber: 5);
      expect(text, isNot(contains('water')));
      expect(text, isNot(contains('river')));
    });

    test('single guess uses singular "guess"', () {
      final guesses = makeGuesses([TemperatureBand.win]);
      final text = buildShareCard(guesses: guesses, puzzleNumber: 1);
      expect(text, contains('1 guess'));
      expect(text, isNot(contains('1 guesses')));
    });

    test('share card contains brain emoji', () {
      final guesses = makeGuesses([TemperatureBand.scorching]);
      final text = buildShareCard(guesses: guesses, puzzleNumber: 1);
      expect(text, contains('🧠'));
    });

    test('emoji order matches guess order (not sorted)', () {
      // The share card preserves guess chronological order.
      final guesses = makeGuesses([
        TemperatureBand.freezing,  // first guess
        TemperatureBand.scorching, // second guess
      ]);
      final text = buildShareCard(guesses: guesses, puzzleNumber: 1);
      // 🟦 should appear before 🟥 in the emoji string.
      final freezingIdx = text.indexOf('🟦');
      final scorchingIdx = text.indexOf('🟥');
      expect(freezingIdx, lessThan(scorchingIdx));
    });

    test('share text contains play URL for viral loop', () {
      // The play URL is always appended so recipients can start playing.
      final guesses = makeGuesses([TemperatureBand.scorching]);
      final text = buildShareCard(guesses: guesses, puzzleNumber: 1);
      expect(text, contains(AppConfig.playUrl));
    });

    test('play URL does not contain the secret word', () {
      // Validate the URL itself is not a spoiler vector.
      // The URL is a static constant — this test asserts it forever.
      expect(AppConfig.playUrl, isNot(contains('ocean')));
      expect(AppConfig.playUrl, isNot(contains('word0')));
    });
  });
}
