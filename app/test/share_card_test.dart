import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/features/win/win_screen.dart';

void main() {
  group('buildShareCard', () {
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

    test('share text contains puzzle number', () {
      final guesses = makeGuesses([TemperatureBand.scorching]);
      final text = buildShareCard(
          guesses: guesses, puzzleNumber: 42, lang: 'en');
      expect(text, contains('#42'));
    });

    test('share text contains emoji trail', () {
      final guesses = makeGuesses([
        TemperatureBand.freezing,
        TemperatureBand.cold,
        TemperatureBand.warm,
        TemperatureBand.hot,
        TemperatureBand.scorching,
      ]);
      final text = buildShareCard(
          guesses: guesses, puzzleNumber: 1, lang: 'en');
      expect(text, contains('🟦'));
      expect(text, contains('🟩'));
      expect(text, contains('🟨'));
      expect(text, contains('🟧'));
      expect(text, contains('🟥'));
    });

    test('won guess replaced by star emoji', () {
      final guesses = [
        Guess(
            word: 'sea',
            rank: 1,
            similarity: 1.0,
            band: TemperatureBand.win),
      ];
      final text =
          buildShareCard(guesses: guesses, puzzleNumber: 1, lang: 'en');
      expect(text, contains('⭐'));
    });

    test('share text does NOT contain secret word "ocean"', () {
      final guesses = makeGuesses([
        TemperatureBand.freezing,
        TemperatureBand.hot,
        TemperatureBand.scorching,
      ]);
      final text = buildShareCard(
          guesses: guesses, puzzleNumber: 1, lang: 'en');
      expect(text, isNot(contains('ocean')));
    });

    test('share text does NOT contain any word from guesses list', () {
      final guesses = [
        Guess(
            word: 'water',
            rank: 79,
            similarity: 0.558,
            band: TemperatureBand.hot),
        Guess(
            word: 'river',
            rank: 200,
            similarity: 0.48,
            band: TemperatureBand.warm),
      ];
      final text = buildShareCard(
          guesses: guesses, puzzleNumber: 5, lang: 'en');
      expect(text, isNot(contains('water')));
      expect(text, isNot(contains('river')));
    });

    test('share text contains play URL', () {
      final guesses = makeGuesses([TemperatureBand.scorching]);
      final text = buildShareCard(
          guesses: guesses, puzzleNumber: 1, lang: 'en');
      expect(text, contains('playmindmeld.vercel.app'));
    });

    test('URL does not contain secret word', () {
      expect('playmindmeld.vercel.app', isNot(contains('ocean')));
    });

    test('emoji order matches guess chronological order', () {
      final guesses = makeGuesses([
        TemperatureBand.freezing,
        TemperatureBand.scorching,
      ]);
      final text = buildShareCard(
          guesses: guesses, puzzleNumber: 1, lang: 'en');
      final freezingIdx = text.indexOf('🟦');
      final scorchingIdx = text.indexOf('🟥');
      expect(freezingIdx, lessThan(scorchingIdx));
    });

    test('English label in share text for en lang', () {
      final guesses = makeGuesses([TemperatureBand.hot]);
      final text = buildShareCard(
          guesses: guesses, puzzleNumber: 1, lang: 'en');
      expect(text, contains('(English)'));
    });

    test('Hinglish label in share text for hi-en lang', () {
      final guesses = makeGuesses([TemperatureBand.hot]);
      final text = buildShareCard(
          guesses: guesses, puzzleNumber: 1, lang: 'hi-en');
      expect(text, contains('(Hinglish)'));
    });

    test('par under par shows negative delta', () {
      // 5 guesses - par 8 = -3
      final guesses = makeGuesses(List.generate(5, (_) => TemperatureBand.hot));
      final text = buildShareCard(
          guesses: guesses, puzzleNumber: 1, lang: 'en', parGuesses: 8);
      expect(text, contains('Par -3'));
    });

    test('par at par shows Par with no delta', () {
      final guesses = makeGuesses(List.generate(8, (_) => TemperatureBand.hot));
      final text = buildShareCard(
          guesses: guesses, puzzleNumber: 1, lang: 'en', parGuesses: 8);
      expect(text, contains('Par\n'));
    });

    test('par over par shows positive delta', () {
      final guesses =
          makeGuesses(List.generate(12, (_) => TemperatureBand.hot));
      final text = buildShareCard(
          guesses: guesses, puzzleNumber: 1, lang: 'en', parGuesses: 8);
      expect(text, contains('Par +4'));
    });

    test('hints count against par', () {
      // 5 guesses + 2 hints = 7; 7 - 8 = -1
      final guesses = makeGuesses(List.generate(5, (_) => TemperatureBand.hot));
      final text = buildShareCard(
          guesses: guesses,
          puzzleNumber: 1,
          lang: 'en',
          parGuesses: 8,
          hintsUsed: 2);
      expect(text, contains('Par -1'));
    });

    test('no par line when parGuesses is null', () {
      final guesses = makeGuesses(List.generate(5, (_) => TemperatureBand.hot));
      final text = buildShareCard(
          guesses: guesses, puzzleNumber: 1, lang: 'en');
      expect(text, isNot(contains('Par')));
    });

    test('beat the bot shown when player guesses < rivalSolveAt', () {
      final guesses = makeGuesses(List.generate(5, (_) => TemperatureBand.hot));
      final text = buildShareCard(
          guesses: guesses,
          puzzleNumber: 1,
          lang: 'en',
          parGuesses: 8,
          rivalSolveAt: 8);
      expect(text, contains('Beat the bot'));
    });

    test('tie shown when player guesses == rivalSolveAt', () {
      final guesses = makeGuesses(List.generate(8, (_) => TemperatureBand.hot));
      final text = buildShareCard(
          guesses: guesses,
          puzzleNumber: 1,
          lang: 'en',
          parGuesses: 8,
          rivalSolveAt: 8);
      expect(text, contains('Tied the bot'));
    });

    test('bot won shown when player guesses > rivalSolveAt', () {
      final guesses =
          makeGuesses(List.generate(12, (_) => TemperatureBand.hot));
      final text = buildShareCard(
          guesses: guesses,
          puzzleNumber: 1,
          lang: 'en',
          parGuesses: 8,
          rivalSolveAt: 8);
      expect(text, contains('Bot won'));
    });

    test('streak shown when currentStreak > 1', () {
      final guesses = makeGuesses([TemperatureBand.hot]);
      final text = buildShareCard(
          guesses: guesses,
          puzzleNumber: 1,
          lang: 'en',
          currentStreak: 5);
      expect(text, contains('5 day streak'));
    });

    test('streak not shown when currentStreak <= 1', () {
      final guesses = makeGuesses([TemperatureBand.hot]);
      final text = buildShareCard(
          guesses: guesses,
          puzzleNumber: 1,
          lang: 'en',
          currentStreak: 1);
      expect(text, isNot(contains('streak')));
    });
  });
}
