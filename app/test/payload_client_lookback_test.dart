import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mindmeld/core/payload_client.dart';

/// [AssetBundle] with no assets: every load throws, like a missing asset key.
class _EmptyAssetBundle extends AssetBundle {
  @override
  Future<ByteData> load(String key) async =>
      throw Exception('Asset not found: $key');

  @override
  Future<String> loadString(String key, {bool cache = true}) async =>
      throw UnimplementedError();

  @override
  Future<T> loadStructuredData<T>(
    String key,
    Future<T> Function(String value) parser,
  ) => throw UnimplementedError();
}

/// Builds a client whose network serves 200 only for [available] dates and
/// 404 for everything else; records requested URLs in [requests].
PayloadClient _client(Set<String> available, List<String> requests) {
  final bytes = File('assets/payloads/en/2026-06-12.json.gz').readAsBytesSync();
  final mock = MockClient((req) async {
    requests.add(req.url.path);
    final date = req.url.pathSegments.last.replaceAll('.json.gz', '');
    return available.contains(date)
        ? http.Response.bytes(bytes, 200)
        : http.Response('Not Found', 404);
  });
  return PayloadClient(
    baseUrl: 'https://example.com/payloads',
    httpClient: mock,
    assetBundle: _EmptyAssetBundle(),
  );
}

void main() {
  group('shiftDateBack', () {
    test('crosses month and year boundaries', () {
      expect(shiftDateBack('2027-01-01', 1), '2026-12-31');
      expect(shiftDateBack('2026-03-01', 1), '2026-02-28');
      expect(shiftDateBack('2028-03-01', 1), '2028-02-29');
      expect(shiftDateBack('2026-11-03', 14), '2026-10-20');
    });
  });

  group('PayloadClient lookback (B2)', () {
    test('today 200 is not a fallback', () async {
      final reqs = <String>[];
      final r = await _client({'2099-05-10'}, reqs).fetch('en', '2099-05-10');
      expect(r.isFallbackDate, isFalse);
      expect(r.servedDate, '2099-05-10');
      expect(reqs, hasLength(1));
    });

    test('today 404 steps back to yesterday', () async {
      final r = await _client({'2099-05-09'}, []).fetch('en', '2099-05-10');
      expect(r.isFallbackDate, isTrue);
      expect(r.servedDate, '2099-05-09');
      expect(r.requestedDate, '2099-05-10');
      expect(r.source, PayloadSource.network);
    });

    test('finds the Nth previous day', () async {
      final reqs = <String>[];
      final r = await _client({'2099-05-05'}, reqs).fetch('en', '2099-05-10');
      expect(r.servedDate, '2099-05-05');
      expect(reqs, hasLength(6));
    });

    test('lookback crosses a year boundary', () async {
      final r = await _client({'2026-12-31'}, []).fetch('en', '2027-01-01');
      expect(r.servedDate, '2026-12-31');
    });

    test(
      'throws when nothing is available within the lookback window',
      () async {
        final reqs = <String>[];
        // 15 days back is outside the 14-day window.
        final c = _client({'2099-04-25'}, reqs);
        await expectLater(c.fetch('en', '2099-05-10'), throwsException);
        expect(reqs, hasLength(1 + kMaxPayloadLookbackDays));
      },
    );

    test('network error does not step back', () async {
      final reqs = <String>[];
      final c = PayloadClient(
        baseUrl: 'https://example.com/payloads',
        httpClient: MockClient((req) async {
          reqs.add(req.url.path);
          throw const SocketException('offline');
        }),
        assetBundle: _EmptyAssetBundle(),
      );
      await expectLater(c.fetch('en', '2099-05-10'), throwsException);
      expect(reqs, hasLength(1));
    });

    test('HTTP 500 does not step back', () async {
      final reqs = <String>[];
      final c = PayloadClient(
        baseUrl: 'https://example.com/payloads',
        httpClient: MockClient((req) async {
          reqs.add(req.url.path);
          return http.Response('boom', 500);
        }),
        assetBundle: _EmptyAssetBundle(),
      );
      await expectLater(c.fetch('en', '2099-05-10'), throwsException);
      expect(reqs, hasLength(1));
    });
  });
}
