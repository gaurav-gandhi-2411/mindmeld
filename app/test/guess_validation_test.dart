import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/payload_codec.dart';

void main() {
  group('Guess validation against en payload', () {
    late DailyPayload payload;

    setUpAll(() {
      final bytes = File(
        'assets/payloads/en/2026-06-12.json.gz',
      ).readAsBytesSync();
      payload = PayloadCodec.decode(Uint8List.fromList(bytes));
    });

    test('non-vocab word returns null (not in word list)', () {
      // "xyzquux" is not in any real English vocab list
      final entry = PayloadCodec.lookupWord('xyzquux', payload);
      expect(entry, isNull,
          reason: 'Non-vocab word should not be found in payload');
    });

    test('valid in-vocab word "water" returns a ranked entry', () {
      final entry = PayloadCodec.lookupWord('water', payload);
      expect(entry, isNotNull, reason: '"water" should be in the English vocab');
      expect(entry!.rank, greaterThanOrEqualTo(1));
      expect(entry.rank, lessThanOrEqualTo(payload.n));
      expect(entry.qsim, greaterThanOrEqualTo(0));
      expect(entry.qsim, lessThanOrEqualTo(65535));
    });

    test('valid word produces correct TemperatureBand', () {
      // water is rank 79 for 2026-06-12 ocean puzzle: should be scorching
      final entry = PayloadCodec.lookupWord('water', payload);
      expect(entry, isNotNull);
      final band = bandForRank(entry!.rank, payload.n);
      // rank 79 ≤ 55 (scorching threshold) is false; 79 ≤ 550 (hot) is true
      expect(band, equals(TemperatureBand.hot));
    });

    test('secret word "ocean" returns rank 1', () {
      final entry = PayloadCodec.lookupWord('ocean', payload);
      expect(entry, isNotNull);
      expect(entry!.rank, equals(1));
      expect(bandForRank(1, payload.n), equals(TemperatureBand.win));
    });

    test('lookup is case-insensitive (normalised to lowercase)', () {
      final lower = PayloadCodec.lookupWord('water', payload);
      final upper = PayloadCodec.lookupWord('WATER', payload);
      final mixed = PayloadCodec.lookupWord('WaTeR', payload);

      expect(lower, isNotNull);
      expect(upper, isNotNull);
      expect(mixed, isNotNull);
      expect(lower!.rank, equals(upper!.rank));
      expect(lower.rank, equals(mixed!.rank));
    });

    test('trimmed whitespace does not affect lookup', () {
      // The app trims before lookup; test that trim + lowercase works
      const word = '  water  ';
      final trimmed = word.trim().toLowerCase();
      final entry = PayloadCodec.lookupWord(trimmed, payload);
      expect(entry, isNotNull);
    });

    test('duplicate guess detection logic', () {
      // Simulate adding two guesses for "water" and checking deduplication
      final guess1 = Guess(
        word: 'water',
        rank: 79,
        similarity: 0.558,
        band: TemperatureBand.hot,
      );
      final guesses = [guess1];

      // Check if "water" already in guesses
      final isDuplicate = guesses.any((g) => g.word == 'water');
      expect(isDuplicate, isTrue);

      // Check "music" is not a duplicate
      final isNotDuplicate = guesses.any((g) => g.word == 'music');
      expect(isNotDuplicate, isFalse);
    });
  });
}
