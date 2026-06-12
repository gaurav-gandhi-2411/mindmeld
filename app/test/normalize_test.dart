import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/core/normalize.dart';
import 'package:mindmeld/core/payload_codec.dart';
import 'package:mindmeld/core/models.dart';

void main() {
  group('normalizeHiEn — rule unit tests', () {
    test('lowercase + strip whitespace', () {
      expect(normalizeHiEn('  HELLO  '), equals('hello'));
      expect(normalizeHiEn('BAARISH'), equals('barish'));
    });

    test('chh → ch (step 2)', () {
      // 'chhhata': replaceAll('chh','ch') on 'chhhata' matches 'chh' at pos 0
      // → 'ch' + 'hata' = 'chhata' (one pass, non-overlapping left-to-right)
      expect(normalizeHiEn('chhhata'), equals('chhata'));
      expect(normalizeHiEn('chhata'), equals('chata'));
      expect(normalizeHiEn('parchhain'), equals('parchain'));
    });

    test('aa → a (step 3)', () {
      expect(normalizeHiEn('baarish'), equals('barish'));
      expect(normalizeHiEn('gaana'), equals('gana'));
      expect(normalizeHiEn('diyaa'), equals('diya'));
    });

    test('ee → i (step 4)', () {
      expect(normalizeHiEn('tasveer'), equals('tasvir'));
      expect(normalizeHiEn('bageecha'), equals('bagicha'));
    });

    test('oo → u (step 5)', () {
      expect(normalizeHiEn('khushboo'), equals('khushbu'));
      expect(normalizeHiEn('loot'), equals('lut'));
    });

    test('rules apply left-to-right in order (chh before aa)', () {
      // "chha" → chh→ch first → "cha", no aa to collapse
      expect(normalizeHiEn('chha'), equals('cha'));
      // "chhaat" → chh→ch → "chaat" → aa→a → "chat"
      expect(normalizeHiEn('chhaat'), equals('chat'));
    });

    test('replaceAll is non-overlapping left-to-right (aaa → aa, not a)', () {
      // Python re.sub('aa', 'a', 'aaa') matches positions 0-1, leaving 'a' at 2
      // → result 'aa'. Dart replaceAll matches identically (non-overlapping).
      expect(normalizeHiEn('aaa'), equals('aa'));
      // 'aaaa' → two non-overlapping matches → 'aa'
      expect(normalizeHiEn('aaaa'), equals('aa'));
    });

    test('no-op when word already normalized', () {
      expect(normalizeHiEn('barish'), equals('barish'));
      expect(normalizeHiEn('gana'), equals('gana'));
      expect(normalizeHiEn('pani'), equals('pani'));
    });

    test('combined: chh + aa + ee + oo in one word', () {
      // Constructed test: 'chhaabeel' → chh→ch 'chaabeel' → aa→a 'chabeel' → ee→i 'chabil'
      expect(normalizeHiEn('chhaabeel'), equals('chabil'));
    });
  });

  group('normalizeHiEn — normalization fixture cases', () {
    // Load the fixture and verify normalize(input) matches what the Python
    // generator computes (both use the same rule set).
    // Fixture: app/test/fixtures/normalization_fixture.json
    // NOTE: normalize(input) != canonical for many cases — canonical is
    // resolved via the payload alt/words lookup, not normalize alone.
    // These tests verify the FOLD step in isolation.

    // Expected normalize() outputs derived from running Python normalize.normalize()
    // on each fixture input — kept inline so the test is self-contained.
    final expectedFolds = <String, String>{
      'barish': 'barish',
      'bageecha': 'bagicha',
      'GANA  ': 'gana',
      'chand': 'chand',
      'khushboo': 'khushbu',
      'razai': 'razai',
      'rajai': 'rajai',
      'gyan': 'gyan',
      'parchhayi': 'parchayi',
      'aina': 'aina',
      'tasvir': 'tasvir',
      'chata': 'chata',
      'ayna': 'ayna',
      'mombati': 'mombati',
      'hasi': 'hasi',
      'pahar': 'pahar',
      'parchhai': 'parchai',
      'tasweer': 'taswir',
      'diyaa': 'diya',
      'gaana': 'gana',
      'mombatti': 'mombatti',
      'chaata': 'chata',
    };

    for (final entry in expectedFolds.entries) {
      test('normalizeHiEn("${entry.key}") == "${entry.value}"', () {
        expect(normalizeHiEn(entry.key), equals(entry.value));
      });
    }
  });

  group('normalization fixture — payload round-trip (bundled hi-en assets)', () {
    // Load any bundled hi-en payload. We use 2026-06-13 because its secret
    // 'gaana' appears in the fixture (input 'GANA  ' → canonical 'gaana').
    // All 22 fixture cases reference words in the shared hi-en vocab.
    late DailyPayload payload;
    late List<Map<String, dynamic>> fixtureCases;

    setUpAll(() {
      final bytes = File(
        'assets/payloads/hi-en/2026-06-13.json.gz',
      ).readAsBytesSync();
      payload = PayloadCodec.decode(Uint8List.fromList(bytes));

      final fixtureJson = File(
        'test/fixtures/normalization_fixture.json',
      ).readAsStringSync();
      final decoded = jsonDecode(fixtureJson) as Map<String, dynamic>;
      fixtureCases = (decoded['cases'] as List<dynamic>)
          .cast<Map<String, dynamic>>();
    });

    test('fixture file loads with 22 cases', () {
      expect(fixtureCases.length, equals(22));
    });

    test('every fixture case: lookup(input) resolves to same rank as lookup(canonical)', () {
      for (final c in fixtureCases) {
        final input = c['input'] as String;
        final canonical = c['canonical'] as String;

        final canonicalEntry = PayloadCodec.lookupWord(canonical, payload);
        expect(
          canonicalEntry,
          isNotNull,
          reason: 'canonical "$canonical" should be in the payload vocab',
        );

        final inputEntry = PayloadCodec.lookupWord(input, payload);
        expect(
          inputEntry,
          isNotNull,
          reason:
              'input "$input" should resolve via 4-step lookup (canonical: $canonical)',
        );

        expect(
          inputEntry!.rank,
          equals(canonicalEntry!.rank),
          reason:
              '"$input" resolves to rank ${inputEntry.rank} '
              'but "$canonical" has rank ${canonicalEntry.rank}',
        );
      }
    });
  });
}
