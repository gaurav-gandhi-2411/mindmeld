/// Tests for [PayloadClient.fetchPack] (phase 6c themed packs) — pack/idx
/// field parsing and the network-then-bundled-asset fallback contract.
library;

import 'dart:convert';
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mindmeld/core/payload_client.dart';
import 'package:mindmeld/core/payload_codec.dart';

/// An in-memory [AssetBundle] mapping a single fixed key to fixed bytes —
/// used to test the pack asset-fallback path without needing real bundled
/// per-puzzle payloads (only manifest.json ships bundled — see spec-phase6c.md).
class _FixedKeyAssetBundle extends AssetBundle {
  _FixedKeyAssetBundle(this._key, this._bytes);

  final String _key;
  final Uint8List _bytes;

  @override
  Future<ByteData> load(String key) async {
    if (key != _key) throw Exception('Asset not found: $key');
    return ByteData.view(_bytes.buffer);
  }

  @override
  Future<String> loadString(String key, {bool cache = true}) =>
      throw UnimplementedError();

  @override
  Future<T> loadStructuredData<T>(
    String key,
    Future<T> Function(String value) parser,
  ) =>
      throw UnimplementedError();
}

/// Builds a minimal gzip-encoded pack payload JSON with the given [pack]/[idx].
Uint8List _buildPackPayloadBytes({
  required String pack,
  required int idx,
  String lang = 'en',
}) {
  const salt = '7ca5996a071e2723';
  final hash = PayloadCodec.hashWord('ocean', salt);
  final json = '''{
    "v":3,"lang":"$lang","date":"$pack-${idx.toString().padLeft(3, '0')}",
    "model":"test","n":1,"salt":"$salt",
    "words":{"$hash":[1,65535]},
    "hints":[[2,"sea"]],
    "s":"TbCpaqQ=",
    "pack":"$pack","idx":$idx
  }''';
  return Uint8List.fromList(GZipCodec().encode(utf8.encode(json)));
}

void main() {
  group('DailyPayload pack/idx fields', () {
    test('present on a pack payload', () {
      final bytes = _buildPackPayloadBytes(pack: 'bollywood', idx: 3);
      final payload = PayloadCodec.decode(bytes);
      expect(payload.pack, equals('bollywood'));
      expect(payload.idx, equals(3));
      expect(payload.date, equals('bollywood-003'));
    });

    test('absent (null) on a daily payload', () {
      final bytes =
          File('assets/payloads/en/2026-06-12.json.gz').readAsBytesSync();
      final payload = PayloadCodec.decode(Uint8List.fromList(bytes));
      expect(payload.pack, isNull);
      expect(payload.idx, isNull);
    });
  });

  group('PayloadClient.fetchPack', () {
    test('successful HTTP response reports network source and parses pack/idx',
        () async {
      final bytes = _buildPackPayloadBytes(pack: 'bollywood', idx: 1);
      final mockHttp = MockClient((request) async {
        expect(request.url.toString(),
            equals('https://example.com/packs/bollywood/en/001.json.gz'));
        return http.Response.bytes(bytes, 200);
      });
      final client = PayloadClient(
        baseUrl: 'https://example.com',
        httpClient: mockHttp,
      );

      final result = await client.fetchPack('bollywood', 1, 'en');

      expect(result.source, equals(PayloadSource.network));
      expect(result.payload.pack, equals('bollywood'));
      expect(result.payload.idx, equals(1));
    });

    test('network failure falls back to the bundled pack asset', () async {
      final bytes = _buildPackPayloadBytes(pack: 'bollywood', idx: 7);
      final mockHttp = MockClient((_) async {
        throw const SocketException('Network unreachable');
      });
      final client = PayloadClient(
        baseUrl: 'https://unreachable.invalid',
        httpClient: mockHttp,
        assetBundle: _FixedKeyAssetBundle(
          'assets/payloads/packs/bollywood/en/007.json.gz',
          bytes,
        ),
      );

      final result = await client.fetchPack('bollywood', 7, 'en');

      expect(result.source, equals(PayloadSource.bundledAsset));
      expect(result.payload.idx, equals(7));
    });

    test('idx is zero-padded to 3 digits in both URL and asset key', () async {
      final bytes = _buildPackPayloadBytes(pack: 'bollywood', idx: 25);
      final client = PayloadClient(
        baseUrl: 'https://unreachable.invalid',
        assetBundle: _FixedKeyAssetBundle(
          'assets/payloads/packs/bollywood/en/025.json.gz',
          bytes,
        ),
      );

      final result = await client.loadBundledPack('bollywood', 25, 'en');
      expect(result.payload.idx, equals(25));
    });

    test('missing bundled asset throws (no silent fallback beyond asset)',
        () async {
      final client = PayloadClient(
        baseUrl: 'https://unreachable.invalid',
        assetBundle: _FixedKeyAssetBundle(
          'assets/payloads/packs/bollywood/en/999.json.gz',
          Uint8List(0),
        ),
      );

      await expectLater(
        client.fetchPack('bollywood', 1, 'en'),
        throwsA(anything),
        reason:
            'Only manifest.json ships bundled for phase 6c — a missing pack '
            'payload with no network must surface as an error to the caller.',
      );
    });
  });
}
