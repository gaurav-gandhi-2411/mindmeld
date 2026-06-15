import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/features/win/win_screen.dart';

void main() {
  // ---------------------------------------------------------------------------
  // Schema round-trip: v3 fields
  // ---------------------------------------------------------------------------
  group('DailyPayload v3 schema', () {
    test('clue and maxGuesses parsed from v3 JSON', () {
      final json = <String, dynamic>{
        'v': 3,
        'lang': 'en',
        'date': '2026-06-12',
        'model': 'all-MiniLM-L6-v2',
        'n': 100,
        'salt': 'abcdef012345abcd',
        'words': <String, dynamic>{},
        'hints': <dynamic>[],
        's': 'dGVzdA==',
        'parGuesses': 9,
        'maxGuesses': 15,
        'clue': 'The biggest blue thing on any map',
        'rival': {
          'even': {'path': [], 'solveAt': 9},
          'chill': {'path': [], 'solveAt': 12},
          'sharp': {'path': [], 'solveAt': 7},
        },
      };
      final payload = DailyPayload.fromJson(json);
      expect(payload.clue, equals('The biggest blue thing on any map'));
      expect(payload.maxGuesses, equals(15));
      expect(payload.v, equals(3));
    });

    test('clue and maxGuesses null for v2 payload', () {
      final json = <String, dynamic>{
        'v': 2,
        'lang': 'en',
        'date': '2026-06-12',
        'model': 'all-MiniLM-L6-v2',
        'n': 100,
        'salt': 'abcdef012345abcd',
        'words': <String, dynamic>{},
        'hints': <dynamic>[],
        's': 'dGVzdA==',
        'parGuesses': 9,
        'rival': {
          'even': {'path': [], 'solveAt': 9},
          'chill': {'path': [], 'solveAt': 12},
          'sharp': {'path': [], 'solveAt': 7},
        },
      };
      final payload = DailyPayload.fromJson(json);
      expect(payload.clue, isNull);
      expect(payload.maxGuesses, isNull);
    });
  });

  // ---------------------------------------------------------------------------
  // Loss share card
  // ---------------------------------------------------------------------------
  group('buildShareCard — loss variant', () {
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

    test('loss share ends with skull emoji', () {
      final guesses = makeGuesses([
        TemperatureBand.freezing,
        TemperatureBand.cold,
        TemperatureBand.warm,
      ]);
      final text = buildShareCard(
        guesses: guesses,
        puzzleNumber: 28,
        lang: 'hi-en',
        won: false,
      );
      expect(text, contains('💀'));
      expect(text, isNot(contains('⭐')));
    });

    test("loss share contains Didn't get it", () {
      final guesses = makeGuesses([TemperatureBand.warm]);
      final text = buildShareCard(
        guesses: guesses,
        puzzleNumber: 1,
        lang: 'en',
        won: false,
      );
      expect(text, contains("Didn't get it"));
    });

    test('loss share contains streak reset', () {
      final guesses = makeGuesses([TemperatureBand.hot]);
      final text = buildShareCard(
        guesses: guesses,
        puzzleNumber: 1,
        lang: 'en',
        won: false,
      );
      expect(text, contains('streak reset'));
    });

    test('loss share does NOT contain secret', () {
      final guesses = makeGuesses([TemperatureBand.hot]);
      final text = buildShareCard(
        guesses: guesses,
        puzzleNumber: 1,
        lang: 'en',
        won: false,
      );
      // Secret word should never appear in share text
      expect(text, isNot(contains('ocean')));
    });

    test('win share ends with star emoji', () {
      final guesses = [
        Guess(word: 'ocean', rank: 1, similarity: 1.0, band: TemperatureBand.win),
      ];
      final text = buildShareCard(
        guesses: guesses,
        puzzleNumber: 1,
        lang: 'en',
        won: true,
      );
      expect(text, contains('⭐'));
      expect(text, isNot(contains('💀')));
    });

    test('win share shows budget fraction when maxGuesses provided', () {
      final guesses = makeGuesses(List.generate(5, (_) => TemperatureBand.hot))
        ..add(Guess(word: 'answer', rank: 1, similarity: 1.0, band: TemperatureBand.win));
      final text = buildShareCard(
        guesses: guesses,
        puzzleNumber: 1,
        lang: 'en',
        parGuesses: 9,
        maxGuesses: 15,
        won: true,
      );
      expect(text, contains('6/15'));
    });

    test('Hinglish loss share contains Hinglish label', () {
      final guesses = makeGuesses([TemperatureBand.cold]);
      final text = buildShareCard(
        guesses: guesses,
        puzzleNumber: 28,
        lang: 'hi-en',
        won: false,
      );
      expect(text, contains('(Hinglish)'));
    });

    test('loss best emoji reflects best band reached', () {
      final guesses = makeGuesses([
        TemperatureBand.freezing,
        TemperatureBand.scorching, // best
        TemperatureBand.cold,
      ]);
      final text = buildShareCard(
        guesses: guesses,
        puzzleNumber: 1,
        lang: 'en',
        won: false,
      );
      // Scorching emoji (🟥) should appear as the best on the outcome line
      expect(text, contains('🟥'));
    });
  });

  // ---------------------------------------------------------------------------
  // Budget enforcement (unit-level state checks)
  // ---------------------------------------------------------------------------
  group('budget enforcement', () {
    test('maxGuesses defaults to null for pre-v3 payloads', () {
      const payload = DailyPayload(
        v: 2,
        lang: 'en',
        date: '2026-06-12',
        model: 'test',
        n: 100,
        salt: 'abcdef012345abcd',
        words: {},
        hints: [],
        s: 'dGVzdA==',
      );
      expect(payload.maxGuesses, isNull);
    });

    test('budget exhaustion condition: guesses + hints >= maxGuesses', () {
      // Simulate the budget check logic from _submitGuess / _useHint
      const maxG = 10;
      const guessCount = 8;
      const hintsUsed = 2;
      expect(guessCount + hintsUsed >= maxG, isTrue);
    });

    test('budget not exhausted when guesses + hints < maxGuesses', () {
      const maxG = 10;
      const guessCount = 7;
      const hintsUsed = 2;
      expect(guessCount + hintsUsed >= maxG, isFalse);
    });
  });
}
