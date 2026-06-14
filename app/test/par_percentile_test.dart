import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/features/win/win_screen.dart';

void main() {
  List<Guess> makeGuesses(int count) => List.generate(
        count,
        (i) => Guess(
          word: 'word$i',
          rank: 1000 - i,
          similarity: 0.5,
          band: TemperatureBand.hot,
        ),
      );

  group('par scoring via buildShareCard', () {
    test('under par shows negative delta', () {
      final text = buildShareCard(
          guesses: makeGuesses(6),
          puzzleNumber: 1,
          lang: 'en',
          parGuesses: 9);
      expect(text, contains('Par -3'));
    });

    test('exactly at par', () {
      final text = buildShareCard(
          guesses: makeGuesses(8),
          puzzleNumber: 1,
          lang: 'en',
          parGuesses: 8);
      // "Par\n" because no delta appended
      expect(text, contains('Par\n'));
    });

    test('over par shows positive delta', () {
      final text = buildShareCard(
          guesses: makeGuesses(12),
          puzzleNumber: 1,
          lang: 'en',
          parGuesses: 8);
      expect(text, contains('Par +4'));
    });

    test('hints count as +1 against par each', () {
      // 5 guesses + 3 hints = 8 effective; 8 - 8 = 0 → Par
      final text = buildShareCard(
          guesses: makeGuesses(5),
          puzzleNumber: 1,
          lang: 'en',
          parGuesses: 8,
          hintsUsed: 3);
      expect(text, contains('Par\n'));
    });

    test('no par line when parGuesses null', () {
      final text = buildShareCard(
          guesses: makeGuesses(5), puzzleNumber: 1, lang: 'en');
      expect(text, isNot(contains('Par')));
    });
  });

  group('percentile math', () {
    double percentile(int rank, int n) => (1.0 - rank / n) * 100;

    test('rank 1 in 55000 is ~100%', () {
      expect(percentile(1, 55000), greaterThan(99.99));
    });

    test('rank 550 in 55000 is ~99%', () {
      expect(percentile(550, 55000).toStringAsFixed(0), '99');
    });

    test('rank 27500 in 55000 is 50%', () {
      expect(percentile(27500, 55000).toStringAsFixed(0), '50');
    });

    test('rank equals n gives 0%', () {
      expect(percentile(55000, 55000), closeTo(0.0, 0.01));
    });
  });
}
