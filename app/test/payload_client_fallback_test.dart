import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mindmeld/core/payload_client.dart';

/// A minimal [AssetBundle] that loads .json.gz files directly from the
/// file system (relative to app/) so tests run without the Flutter asset system.
class FileSystemAssetBundle extends AssetBundle {
  @override
  Future<ByteData> load(String key) async {
    final file = File(key);
    if (!file.existsSync()) {
      throw Exception('Asset not found: $key');
    }
    final bytes = await file.readAsBytes();
    return ByteData.view(bytes.buffer);
  }

  @override
  Future<String> loadString(String key, {bool cache = true}) async {
    throw UnimplementedError();
  }

  @override
  Future<T> loadStructuredData<T>(
    String key,
    Future<T> Function(String value) parser,
  ) {
    throw UnimplementedError();
  }
}

void main() {
  group('PayloadClient fallback', () {
    test('unreachable base URL falls back to bundled asset', () async {
      // Use a mock HTTP client that always throws a connection error.
      final mockHttp = MockClient((_) async {
        throw const SocketException('Network unreachable');
      });

      final client = PayloadClient(
        baseUrl: 'https://unreachable.invalid',
        httpClient: mockHttp,
        assetBundle: FileSystemAssetBundle(),
      );

      final result = await client.fetch('en', '2026-06-12');

      expect(result.source, equals(PayloadSource.bundledAsset));
      expect(result.payload.lang, equals('en'));
      expect(result.payload.date, equals('2026-06-12'));
      expect(result.payload.n, equals(55000));
    });

    test('HTTP 404 falls back to bundled asset', () async {
      final mockHttp = MockClient((_) async {
        return http.Response('Not Found', 404);
      });

      final client = PayloadClient(
        baseUrl: 'https://unreachable.invalid',
        httpClient: mockHttp,
        assetBundle: FileSystemAssetBundle(),
      );

      final result = await client.fetch('en', '2026-06-12');
      expect(result.source, equals(PayloadSource.bundledAsset));
    });

    test('successful HTTP response reports network source', () async {
      // Load the real bytes and serve them via mock HTTP.
      final realBytes =
          File('assets/payloads/en/2026-06-12.json.gz').readAsBytesSync();

      final mockHttp = MockClient((_) async {
        return http.Response.bytes(realBytes, 200);
      });

      final client = PayloadClient(
        baseUrl: 'https://example.com/payloads',
        httpClient: mockHttp,
        assetBundle: FileSystemAssetBundle(),
      );

      final result = await client.fetch('en', '2026-06-12');
      expect(result.source, equals(PayloadSource.network));
      expect(result.payload.n, equals(55000));
    });

    test('hi-en payload also loads from bundled asset on failure', () async {
      final mockHttp = MockClient((_) async {
        throw const SocketException('Network unreachable');
      });

      final client = PayloadClient(
        baseUrl: 'https://unreachable.invalid',
        httpClient: mockHttp,
        assetBundle: FileSystemAssetBundle(),
      );

      final result = await client.fetch('hi-en', '2026-06-12');
      expect(result.source, equals(PayloadSource.bundledAsset));
      expect(result.payload.lang, equals('hi-en'));
      // Refreshed 2026-06-12 hi-en payload (with alt map) has n=10445.
      expect(result.payload.n, equals(10445));
    });
  });
}
