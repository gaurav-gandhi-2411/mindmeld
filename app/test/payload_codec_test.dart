import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/payload_codec.dart';

void main() {
  group('PayloadCodec — real en sample (2026-06-12)', () {
    late DailyPayload payload;

    setUpAll(() {
      // Load the bundled sample payload directly from the file system.
      // In test runs the working directory is app/, so assets/ is reachable.
      final bytes = File(
        'assets/payloads/en/2026-06-12.json.gz',
      ).readAsBytesSync();
      payload = PayloadCodec.decode(Uint8List.fromList(bytes));
    });

    test('payload fields parse correctly', () {
      expect(payload.v, equals(2));
      expect(payload.lang, equals('en'));
      expect(payload.date, equals('2026-06-12'));
      expect(payload.n, equals(55000));
      expect(payload.salt, equals('7ca5996a071e2723'));
      expect(payload.words.length, equals(55000));
    });

    test('exactly one rank-1 entry exists', () {
      final rank1 =
          payload.words.values.where((e) => e.rank == 1).toList();
      expect(rank1.length, equals(1));
    });

    test('known word "sea" lookup returns correct rank', () {
      // Verified: sea → rank 3, qsim 61322
      final entry = PayloadCodec.lookupWord('sea', payload);
      expect(entry, isNotNull);
      expect(entry!.rank, equals(3));
      expect(entry.qsim, equals(61322));
    });

    test('known word "music" lookup returns correct rank', () {
      // Verified: music → rank 811, qsim 46018
      final entry = PayloadCodec.lookupWord('music', payload);
      expect(entry, isNotNull);
      expect(entry!.rank, equals(811));
    });

    test('non-vocab word returns null', () {
      // A random gibberish string will not be in the 55k vocab.
      final entry = PayloadCodec.lookupWord('xyzqwerty999', payload);
      expect(entry, isNull);
    });

    test('decodeSecret returns "ocean" (line 1 of secrets_en.txt)', () {
      // The secret for 2026-06-12 is the first line of secrets_en.txt: "ocean"
      final secret = PayloadCodec.decodeSecret(payload);
      expect(secret, equals('ocean'));
    });

    test('dequantize round-trips within 1e-4', () {
      // rank-1 entry (ocean) has qsim=65535 → similarity should be ~1.0
      final rank1Entry =
          payload.words.values.firstWhere((e) => e.rank == 1);
      final sim = PayloadCodec.dequantize(rank1Entry.qsim);
      expect((sim - 1.0).abs(), lessThan(1e-4));
    });

    test('hashWord concatenates word+salt (lowercase)', () {
      // Manual verification: sha1("ocean" + "7ca5996a071e2723")[:12]
      final hash = PayloadCodec.hashWord('ocean', payload.salt);
      expect(hash, equals('8edb3e6fdc86'));
      // The hash must exist in words at rank 1.
      expect(payload.words[hash]?.rank, equals(1));
    });

    test('hints list is non-empty and each has a rank', () {
      expect(payload.hints.isNotEmpty, isTrue);
      for (final h in payload.hints) {
        expect(h.rank, greaterThan(1));
        expect(h.word.isNotEmpty, isTrue);
      }
    });
  });

  group('PayloadCodec — real hi-en sample (2026-06-12)', () {
    late DailyPayload payload;

    setUpAll(() {
      final bytes = File(
        'assets/payloads/hi-en/2026-06-12.json.gz',
      ).readAsBytesSync();
      payload = PayloadCodec.decode(Uint8List.fromList(bytes));
    });

    test('lang is hi-en', () {
      expect(payload.lang, equals('hi-en'));
    });

    test('n is 10445', () {
      // Refreshed 2026-06-12 hi-en payload (with alt map) has n=10445.
      expect(payload.n, equals(10445));
    });

    test('exactly one rank-1 entry exists', () {
      final rank1 =
          payload.words.values.where((e) => e.rank == 1).toList();
      expect(rank1.length, equals(1));
    });

    test('decodeSecret returns "samunder"', () {
      final secret = PayloadCodec.decodeSecret(payload);
      expect(secret, equals('samunder'));
    });
  });

  group('PayloadCodec — synthetic minimal payload', () {
    // Build a tiny in-memory payload to test codec in isolation.
    late DailyPayload miniPayload;

    setUpAll(() {
      // Manually craft a minimal JSON payload, gzip it, decode it.
      final salt = '7ca5996a071e2723'; // reuse en salt for simplicity
      // hash("ocean" + salt)[:12]
      final hash = PayloadCodec.hashWord('ocean', salt);

      // qsim for sim=1.0: round((1.0 + 1.0) * 32767.5) = 65535
      final miniJson = '''{
        "v":2,"lang":"en","date":"2026-06-12",
        "model":"test","n":1,"salt":"$salt",
        "words":{"$hash":[1,65535]},
        "hints":[[2,"sea"]],
        "s":"TbCpaqQ="
      }''';
      final bytes = GZipCodec().encode(miniJson.codeUnits);
      miniPayload = PayloadCodec.decode(Uint8List.fromList(bytes));
    });

    test('mini payload has correct n', () {
      expect(miniPayload.n, equals(1));
    });

    test('mini payload lookup for ocean returns rank 1', () {
      final entry = PayloadCodec.lookupWord('ocean', miniPayload);
      expect(entry?.rank, equals(1));
    });

    test('decodeSecret on mini payload returns ocean', () {
      final secret = PayloadCodec.decodeSecret(miniPayload);
      expect(secret, equals('ocean'));
    });
  });
}
