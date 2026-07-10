import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:archive/archive.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/payload_codec.dart';

// ---------------------------------------------------------------------------
// Helpers to build synthetic gzip payloads from raw JSON strings.
// ---------------------------------------------------------------------------

DailyPayload _makePayload(String jsonStr) {
  final encoded = GZipEncoder().encode(utf8.encode(jsonStr));
  return PayloadCodec.decode(Uint8List.fromList(encoded));
}

// Synthetic hi-en mini payload.
// Secret: gaana (rank 1), vocab also has: nadi (rank 200).
// Alt map: gana (fold of gaana) → [1, 65535].
//
// Values produced by generator/config.py for date 2099-01-01 / hi-en:
//   salt        = 7b7759076622ab9e
//   gaana_hash  = 68e12a87f56c   (sha1('gaana'+'salt')[:12])
//   nadi_hash   = d4cca5defa60
//   gana_hash   = 9defd718b182   (sha1('gana'+'salt')[:12])
//   s_field     = OL7r1vc=
const _hiEnMiniJson = '''
{
  "v":1,"lang":"hi-en","date":"2099-01-01","model":"test","n":2,
  "salt":"7b7759076622ab9e",
  "words":{"68e12a87f56c":[1,65535],"d4cca5defa60":[200,50000]},
  "alt":{"9defd718b182":[1,65535]},
  "hints":[[200,"nadi"]],
  "s":"OL7r1vc="
}
''';

// Synthetic en mini payload — NO alt map.
// Secret: coffee (rank 1), water (rank 2).
//   salt         = 30f53d2c5691918c
//   coffee_hash  = 28d244c610b9
//   water_hash   = 15340a06b430
//   s_field      = pKoFd2/C
const _enMiniJson = '''
{
  "v":1,"lang":"en","date":"2099-01-02","model":"test","n":2,
  "salt":"30f53d2c5691918c",
  "words":{"28d244c610b9":[1,65535],"15340a06b430":[2,60000]},
  "hints":[[2,"water"]],
  "s":"pKoFd2/C"
}
''';

// Synthetic hi-en payload WITHOUT alt field (simulates older payload format).
const _hiEnNoAltJson = '''
{
  "v":1,"lang":"hi-en","date":"2099-01-03","model":"test","n":1,
  "salt":"7b7759076622ab9e",
  "words":{"68e12a87f56c":[1,65535]},
  "hints":[],
  "s":"OL7r1vc="
}
''';

void main() {
  // -------------------------------------------------------------------------
  group('DailyPayload.fromJson — alt map parsing', () {
    test('alt map is parsed when present', () {
      final payload = _makePayload(_hiEnMiniJson);
      expect(payload.alt.length, equals(1));
      expect(payload.alt['9defd718b182']?.rank, equals(1));
      expect(payload.alt['9defd718b182']?.qsim, equals(65535));
    });

    test('alt map is empty (not null) when field is absent', () {
      final payload = _makePayload(_hiEnNoAltJson);
      expect(payload.alt, isNotNull);
      expect(payload.alt, isEmpty);
    });

    test('en payload has no alt field — alt is empty', () {
      final payload = _makePayload(_enMiniJson);
      expect(payload.alt, isEmpty);
    });
  });

  // -------------------------------------------------------------------------
  group('PayloadCodec.lookupWord — 4-step lookup order (hi-en)', () {
    late DailyPayload payload;
    setUpAll(() => payload = _makePayload(_hiEnMiniJson));

    test('step 1: exact lower match in words returns entry', () {
      // 'gaana' is directly in words
      final entry = PayloadCodec.lookupWord('gaana', payload);
      expect(entry, isNotNull);
      expect(entry!.rank, equals(1));
    });

    test('step 1: case-insensitive (GAANA → gaana in words)', () {
      final entry = PayloadCodec.lookupWord('GAANA', payload);
      expect(entry?.rank, equals(1));
    });

    test('step 2: exact lower hash in alt returns entry', () {
      // 'gana' is NOT in words but IS in alt (its fold = 'gana' which is itself)
      // The alt map key is hash('gana'+salt) = 9defd718b182
      final entry = PayloadCodec.lookupWord('gana', payload);
      expect(entry, isNotNull);
      expect(entry!.rank, equals(1));
    });

    test('step 3: normalized form in words (via fold)', () {
      // Build a payload where norm(input) hits words but input itself doesn't.
      // 'diyaa' normalizes to 'diya'; we build a payload where 'diya' is in words.
      // Use 2026-06-13 for this — the shared vocab has 'diya' and 'diyaa' folds to it.
      final bytes = File(
        'assets/payloads/hi-en/2026-06-13.json.gz',
      ).readAsBytesSync();
      final real = PayloadCodec.decode(Uint8List.fromList(bytes));

      // 'bageecha' normalizes to 'bagicha' which is in words
      final entry = PayloadCodec.lookupWord('bageecha', real);
      expect(entry, isNotNull, reason: 'bageecha (step 3) should fold to bagicha in words');

      final canonEntry = PayloadCodec.lookupWord('bagicha', real);
      expect(entry?.rank, equals(canonEntry?.rank));
    });

    test('step 4: normalized form in alt map', () {
      // Use 2026-06-13 real payload.
      // 'chaata' normalizes to 'chata'. 'chata' is in alt → resolves to 'chhata'.
      final bytes = File(
        'assets/payloads/hi-en/2026-06-13.json.gz',
      ).readAsBytesSync();
      final real = PayloadCodec.decode(Uint8List.fromList(bytes));

      final entry = PayloadCodec.lookupWord('chaata', real);
      expect(entry, isNotNull, reason: 'chaata (step 4) should resolve via norm+alt');

      final canonEntry = PayloadCodec.lookupWord('chhata', real);
      expect(entry?.rank, equals(canonEntry?.rank));
    });

    test('non-vocab word returns null', () {
      final entry = PayloadCodec.lookupWord('xyzqwerty', payload);
      expect(entry, isNull);
    });
  });

  // -------------------------------------------------------------------------
  group('PayloadCodec.lookupWord — en path has no fold', () {
    late DailyPayload payload;
    setUpAll(() => payload = _makePayload(_enMiniJson));

    test('exact match in en words succeeds', () {
      final entry = PayloadCodec.lookupWord('coffee', payload);
      expect(entry?.rank, equals(1));
    });

    test('fold variant "cofi" does NOT match in en (no fold applied)', () {
      // normalizeHiEn('cofi') would not change it — but 'cofi' is not in vocab
      // The key test: 'oo'→'u' fold would give 'cofi'→'cofi' (no oo).
      // More precisely: 'cofee' normalizes to 'cofi' (ee→i), but en never folds.
      // So we try 'cofee' which is not in en words and should return null.
      final entry = PayloadCodec.lookupWord('cofee', payload);
      expect(entry, isNull, reason: '"cofee" must not match en payload even though fold → cofi');
    });

    test('only exact en words lookup — variant returns null', () {
      // 'coffoo' is not in the mini en vocab
      final entry = PayloadCodec.lookupWord('coffoo', payload);
      expect(entry, isNull);
    });
  });

  // -------------------------------------------------------------------------
  group('Duplicate detection — by resolved rank', () {
    late DailyPayload payload;
    setUpAll(() => payload = _makePayload(_hiEnMiniJson));

    // Simulate the puzzle screen's duplicate logic using rank comparison.
    // The real _submitGuess now does: state.guesses.any((g) => g.rank == entry.rank)
    // We use TemperatureBand.freezing as a placeholder to avoid calling bandForRank
    // with the mini payload (n=2 < scorchingFloor=50 → invalid clamp).
    List<Guess> simulateGuess(List<Guess> guesses, String word) {
      final entry = PayloadCodec.lookupWord(word, payload);
      if (entry == null) return guesses; // not in vocab
      // Duplicate: same rank already guessed
      if (guesses.any((g) => g.rank == entry.rank)) return guesses;
      return [
        ...guesses,
        Guess(
          word: word,
          rank: entry.rank,
          similarity: entry.similarity,
          band: TemperatureBand.freezing, // placeholder; n=2 is too small for real band calc
        ),
      ];
    }

    test('guessing "gaana" then "gana" — second is flagged duplicate (same rank)', () {
      var guesses = <Guess>[];
      guesses = simulateGuess(guesses, 'gaana');
      expect(guesses.length, equals(1));
      expect(guesses.first.rank, equals(1));

      // 'gana' resolves to rank 1 (same canonical) — should NOT add a new tile
      final beforeLen = guesses.length;
      guesses = simulateGuess(guesses, 'gana');
      expect(guesses.length, equals(beforeLen),
          reason: '"gana" resolves to rank 1 (same as gaana) → duplicate');
    });

    test('guessing "gana" then "gaana" — second is also a duplicate', () {
      var guesses = <Guess>[];
      guesses = simulateGuess(guesses, 'gana');
      expect(guesses.length, equals(1));

      guesses = simulateGuess(guesses, 'gaana');
      expect(guesses.length, equals(1),
          reason: '"gaana" resolves to rank 1 (same as gana) → duplicate');
    });

    test('guessing "nadi" after "gaana" — new entry added (different rank)', () {
      var guesses = <Guess>[];
      guesses = simulateGuess(guesses, 'gaana');
      guesses = simulateGuess(guesses, 'nadi');
      expect(guesses.length, equals(2));
      expect(guesses.last.rank, equals(200));
    });
  });

  // -------------------------------------------------------------------------
  group('Win via variant', () {
    late DailyPayload payload;
    setUpAll(() => payload = _makePayload(_hiEnMiniJson));

    test('guessing variant "gana" on secret "gaana" → resolves to rank 1 (win)', () {
      // The secret is gaana (rank 1). Player types 'gana' (a variant).
      // PayloadCodec.lookupWord should resolve via step 2 (alt map) → rank 1.
      final entry = PayloadCodec.lookupWord('gana', payload);
      expect(entry, isNotNull);
      expect(entry!.rank, equals(1),
          reason: 'Variant "gana" should resolve to rank 1 — triggering win');
    });

    test('decoded secret for hi-en mini payload is "gaana"', () {
      final secret = PayloadCodec.decodeSecret(payload);
      expect(secret, equals('gaana'));
    });

    test('win detection: rank == 1 from variant guess', () {
      final entry = PayloadCodec.lookupWord('gana', payload);
      final isWin = entry?.rank == 1;
      expect(isWin, isTrue);
    });
  });

  // -------------------------------------------------------------------------
  group('PayloadCodec — real hi-en/2026-06-13 alt map', () {
    late DailyPayload payload;
    setUpAll(() {
      final bytes = File(
        'assets/payloads/hi-en/2026-06-13.json.gz',
      ).readAsBytesSync();
      payload = PayloadCodec.decode(Uint8List.fromList(bytes));
    });

    test('alt map is non-empty for hi-en/2026-06-13', () {
      expect(payload.alt.isNotEmpty, isTrue);
      expect(payload.alt.length, equals(462));
    });

    test('secret is gaana (rank 1)', () {
      final secret = PayloadCodec.decodeSecret(payload);
      expect(secret, equals('gaana'));
    });

    test('"gana" resolves to rank 1 via alt map lookup', () {
      final entry = PayloadCodec.lookupWord('gana', payload);
      expect(entry?.rank, equals(1),
          reason: '"gana" is in alt map pointing to gaana (rank 1)');
    });

    test('"GANA  " (trimmed/cased variant) also resolves to rank 1', () {
      final entry = PayloadCodec.lookupWord('GANA  ', payload);
      expect(entry?.rank, equals(1));
    });
  });
}
