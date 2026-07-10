/// Tests for phase 6c themed-pack manifest parsing and [PackCatalog]
/// fetch/fallback semantics — mirrors payload_client_fallback_test.dart's
/// approach for the daily payload client.
library;

import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mindmeld/core/packs.dart';
import 'package:mindmeld/iap/entitlements.dart';

/// A minimal [AssetBundle] that loads files directly from the file system
/// (relative to app/) so tests run without the Flutter asset system.
class _FileSystemAssetBundle extends AssetBundle {
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
  group('Pack manifest parsing (bundled fixture)', () {
    late PackManifest manifest;

    setUpAll(() {
      final bytes = File('assets/payloads/packs/manifest.json').readAsBytesSync();
      final json = jsonDecode(utf8.decode(bytes)) as Map<String, dynamic>;
      manifest = PackManifest.fromJson(json);
    });

    test('parses all four packs from the frozen lineup', () {
      expect(manifest.v, equals(1));
      expect(manifest.packs, hasLength(4));
      expect(manifest.packs.map((p) => p.id),
          containsAll(['bollywood', 'cricket', 'indian-food', 'nature-wild']));
    });

    test('bollywood is free, live, count 25, icon film', () {
      final bollywood = manifest.packs.firstWhere((p) => p.id == 'bollywood');
      expect(bollywood.free, isTrue);
      expect(bollywood.isLive, isTrue);
      expect(bollywood.count, equals(25));
      expect(bollywood.iconData, equals(Icons.movie_filter));
      expect(bollywood.titleFor('en'), equals('Bollywood'));
      expect(bollywood.titleFor('hi-en'), equals('Bollywood'));
    });

    test('cricket is paid, live, count 25, icon sports_cricket', () {
      final cricket = manifest.packs.firstWhere((p) => p.id == 'cricket');
      expect(cricket.free, isFalse);
      expect(cricket.isLive, isTrue);
      expect(cricket.count, equals(25));
      expect(cricket.iconData, equals(Icons.sports_cricket));
      expect(cricket.titleFor('en'), equals('Cricket'));
      expect(cricket.titleFor('hi-en'), equals('Cricket'));
    });

    test('indian-food/nature-wild are paid and coming_soon', () {
      for (final id in ['indian-food', 'nature-wild']) {
        final pack = manifest.packs.firstWhere((p) => p.id == id);
        expect(pack.free, isFalse, reason: '$id must not be free');
        expect(pack.isLive, isFalse, reason: '$id must be coming_soon');
        expect(pack.count, equals(0));
      }
    });
  });

  group('Pack.fromJson tolerance', () {
    test('unknown icon key falls back to Icons.extension', () {
      final pack = Pack.fromJson({
        'id': 'mystery',
        'title': {'en': 'Mystery'},
        'tagline': <String, dynamic>{},
        'free': false,
        'status': 'coming_soon',
        'accent': '#123456',
        'accentDark': '#000000',
        'icon': 'unknown_key',
        'langs': ['en'],
        'count': 0,
      });
      expect(pack.iconData, equals(Icons.extension));
    });

    test('missing tagline resolves to empty string', () {
      final pack = Pack.fromJson({
        'id': 'mystery',
        'title': {'en': 'Mystery'},
        'free': false,
        'status': 'coming_soon',
        'accent': '#123456',
        'accentDark': '#000000',
        'icon': 'film',
        'langs': ['en'],
        'count': 0,
      });
      expect(pack.taglineFor('en'), equals(''));
    });

    test('malformed accent color falls back to the app purple', () {
      final pack = Pack.fromJson({
        'id': 'broken',
        'title': {'en': 'Broken'},
        'tagline': {'en': 'x'},
        'free': false,
        'status': 'live',
        'accent': 'not-a-color',
        'accentDark': '#zzzzzz',
        'icon': 'film',
        'langs': ['en'],
        'count': 1,
      });
      expect(pack.accent, equals(kPackFallbackAccent));
      expect(pack.accentDark, equals(kPackFallbackAccent));
    });

    test('missing status defaults to coming_soon', () {
      final pack = Pack.fromJson({
        'id': 'x',
        'title': {'en': 'X'},
        'tagline': {'en': 'x'},
        'free': false,
        'accent': '#123456',
        'accentDark': '#000000',
        'icon': 'film',
        'langs': ['en'],
        'count': 0,
      });
      expect(pack.isLive, isFalse);
    });
  });

  group('PackCatalog fetch/fallback', () {
    test('unreachable base URL falls back to the bundled manifest asset', () async {
      final mockHttp = MockClient((_) async {
        throw const SocketException('Network unreachable');
      });
      final catalog = PackCatalog(
        baseUrl: 'https://unreachable.invalid',
        httpClient: mockHttp,
        assetBundle: _FileSystemAssetBundle(),
      );

      final result = await catalog.fetch();

      expect(result.source, equals(PackManifestSource.bundledAsset));
      expect(result.manifest.packs, hasLength(4));
      expect(catalog.lastSource, equals(PackManifestSource.bundledAsset));
    });

    test('HTTP 404 falls back to bundled asset', () async {
      final mockHttp = MockClient((_) async => http.Response('Not Found', 404));
      final catalog = PackCatalog(
        baseUrl: 'https://unreachable.invalid',
        httpClient: mockHttp,
        assetBundle: _FileSystemAssetBundle(),
      );

      final result = await catalog.fetch();
      expect(result.source, equals(PackManifestSource.bundledAsset));
    });

    test('successful HTTP response reports network source', () async {
      final realBytes =
          File('assets/payloads/packs/manifest.json').readAsBytesSync();
      final mockHttp =
          MockClient((_) async => http.Response.bytes(realBytes, 200));
      final catalog = PackCatalog(
        baseUrl: 'https://example.com',
        httpClient: mockHttp,
        assetBundle: _FileSystemAssetBundle(),
      );

      final result = await catalog.fetch();
      expect(result.source, equals(PackManifestSource.network));
      expect(result.manifest.packs, hasLength(4));
    });

    test('loadBundled loads the manifest directly without network', () async {
      final catalog = PackCatalog(
        baseUrl: 'https://unreachable.invalid',
        assetBundle: _FileSystemAssetBundle(),
      );
      final result = await catalog.loadBundled();
      expect(result.source, equals(PackManifestSource.bundledAsset));
      expect(result.manifest.packs, hasLength(4));
    });
  });

  group('packUnlocked', () {
    final freePack = Pack.fromJson({
      'id': 'bollywood',
      'title': {'en': 'Bollywood'},
      'tagline': {'en': 'x'},
      'free': true,
      'status': 'live',
      'accent': '#E8B23A',
      'accentDark': '#8E1A2B',
      'icon': 'film',
      'langs': ['en'],
      'count': 25,
    });

    final paidPack = Pack.fromJson({
      'id': 'cricket',
      'title': {'en': 'Cricket'},
      'tagline': {'en': 'x'},
      'free': false,
      'status': 'live',
      'accent': '#2E7D32',
      'accentDark': '#1B4D20',
      'icon': 'cricket',
      'langs': ['en'],
      'count': 10,
    });

    test('free pack is always unlocked, even when IAP is gated natively', () {
      expect(
        packUnlocked(freePack, Entitlements.empty, iapEnabledEffective: true),
        isTrue,
      );
    });

    test('web (iapEnabledEffective=false) unlocks every pack regardless of entitlements', () {
      expect(
        packUnlocked(paidPack, Entitlements.empty, iapEnabledEffective: false),
        isTrue,
      );
    });

    test('native + not entitled + not free → locked', () {
      expect(
        packUnlocked(paidPack, Entitlements.empty, iapEnabledEffective: true),
        isFalse,
      );
    });

    test('native + entitled → unlocked', () {
      const entitled = Entitlements(packs: {'cricket'});
      expect(
        packUnlocked(paidPack, entitled, iapEnabledEffective: true),
        isTrue,
      );
    });

    test('native + entitled to a DIFFERENT pack → still locked', () {
      const entitled = Entitlements(packs: {'indian-food'});
      expect(
        packUnlocked(paidPack, entitled, iapEnabledEffective: true),
        isFalse,
      );
    });
  });
}
