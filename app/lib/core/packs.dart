/// Themed puzzle packs (phase 6c) — model, manifest parsing, and catalog
/// fetch/fallback.
///
/// Frozen generator/app contract:
///   Manifest:  GET {baseUrl}/packs/manifest.json
///              fallback assets/payloads/packs/manifest.json
///   Payloads:  GET {baseUrl}/packs/{packId}/{lang}/{NNN}.json.gz
///              fallback assets/payloads/packs/{packId}/{lang}/{NNN}.json.gz
///              (see [PayloadClient.fetchPack])
library;

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:mindmeld/core/config.dart';
import 'package:mindmeld/iap/entitlements.dart';

/// Describes where a pack manifest was ultimately loaded from.
enum PackManifestSource { network, bundledAsset }

/// A single themed puzzle pack described by the manifest.
///
/// Parsing is tolerant of a drifted/partial manifest entry: unknown icon keys
/// fall back to [Icons.extension] (via [iconData]) and a missing tagline
/// resolves to an empty string, rather than throwing and blanking the whole
/// pack selector over one bad entry.
class Pack {
  const Pack({
    required this.id,
    required this.title,
    required this.tagline,
    required this.free,
    required this.status,
    required this.accent,
    required this.accentDark,
    required this.icon,
    required this.langs,
    required this.count,
  });

  final String id;

  /// Lang key -> localized title, e.g. {"en": "Bollywood", "hi-en": "Bollywood"}.
  final Map<String, String> title;

  /// Lang key -> localized tagline. Missing entries resolve to ''.
  final Map<String, String> tagline;

  /// Whether the pack is playable without a purchase.
  final bool free;

  /// "live" or "coming_soon" (any other/missing value treated as coming_soon).
  final String status;
  final Color accent;
  final Color accentDark;

  /// Raw icon key from the manifest ("film" | "cricket" | "food" | "nature").
  final String icon;
  final List<String> langs;
  final int count;

  bool get isLive => status == 'live';

  IconData get iconData => packIconForKey(icon);

  String titleFor(String lang) => title[lang] ?? title['en'] ?? id;

  String taglineFor(String lang) => tagline[lang] ?? tagline['en'] ?? '';

  factory Pack.fromJson(Map<String, dynamic> json) {
    final rawTitle = json['title'] as Map<String, dynamic>? ?? {};
    final rawTagline = json['tagline'] as Map<String, dynamic>? ?? {};
    return Pack(
      id: json['id'] as String,
      title: rawTitle.map((k, v) => MapEntry(k, v as String)),
      tagline: rawTagline.map((k, v) => MapEntry(k, v as String)),
      free: json['free'] as bool? ?? false,
      status: json['status'] as String? ?? 'coming_soon',
      accent: colorFromHex(json['accent'] as String?),
      accentDark: colorFromHex(json['accentDark'] as String?),
      icon: json['icon'] as String? ?? '',
      langs: (json['langs'] as List<dynamic>? ?? const <dynamic>[])
          .cast<String>(),
      count: json['count'] as int? ?? 0,
    );
  }
}

/// Fallback accent used when a manifest entry has a missing/malformed color —
/// the app's core purple, so a bad manifest entry degrades gracefully instead
/// of crashing the pack selector.
const Color kPackFallbackAccent = Color(0xFF6200EE);

/// Parses "#RRGGBB" into a [Color]; tolerant of null/malformed input.
Color colorFromHex(String? hex) {
  if (hex == null) return kPackFallbackAccent;
  final cleaned = hex.replaceFirst('#', '');
  if (cleaned.length != 6) return kPackFallbackAccent;
  final value = int.tryParse(cleaned, radix: 16);
  if (value == null) return kPackFallbackAccent;
  return Color(0xFF000000 | value);
}

/// Maps a manifest icon key to a concrete [IconData].
///
/// Unknown keys (future pack categories, typos) fall back to [Icons.extension]
/// so a new pack category never crashes the selector while it waits on an
/// app update.
IconData packIconForKey(String key) {
  switch (key) {
    case 'film':
      return Icons.movie_filter;
    case 'cricket':
      return Icons.sports_cricket;
    case 'food':
      return Icons.restaurant;
    case 'nature':
      return Icons.forest;
    default:
      return Icons.extension;
  }
}

/// True when [pack] should be playable without a purchase:
///   - free packs are always unlocked
///   - web builds never gate packs behind IAP (purchases_flutter is native-only)
///   - native builds require [pack.id] to be present in [entitlements.packs]
///
/// [iapEnabledEffective] defaults to [AppConfig.iapEnabledEffective] (the real
/// compile-time flag) but can be overridden — used in tests to simulate a
/// native build without needing a --dart-define at `flutter test` invocation.
bool packUnlocked(
  Pack pack,
  Entitlements entitlements, {
  bool? iapEnabledEffective,
}) {
  final gated = iapEnabledEffective ?? AppConfig.iapEnabledEffective;
  return pack.free || !gated || entitlements.packs.contains(pack.id);
}

/// The full pack manifest (`{"v":1,"packs":[...]}`).
class PackManifest {
  const PackManifest({required this.v, required this.packs});

  final int v;
  final List<Pack> packs;

  factory PackManifest.fromJson(Map<String, dynamic> json) {
    final rawPacks = json['packs'] as List<dynamic>? ?? const <dynamic>[];
    return PackManifest(
      v: json['v'] as int? ?? 1,
      packs: rawPacks
          .map((p) => Pack.fromJson(p as Map<String, dynamic>))
          .toList(),
    );
  }
}

/// Result of a [PackCatalog.fetch] call, including which source was used.
class PackManifestResult {
  const PackManifestResult({required this.manifest, required this.source});

  final PackManifest manifest;
  final PackManifestSource source;
}

/// Fetches the themed-pack manifest from the network, falling back to the
/// bundled asset — mirrors [PayloadClient]'s network-then-asset contract and
/// constructor-injection shape so tests can inject a fake [http.Client] /
/// [AssetBundle] exactly as they do for [PayloadClient].
class PackCatalog {
  PackCatalog({
    String? baseUrl,
    http.Client? httpClient,
    AssetBundle? assetBundle,
  })  : _baseUrl = baseUrl ?? AppConfig.payloadBaseUrl,
        _http = httpClient ?? http.Client(),
        _assets = assetBundle ?? rootBundle;

  final String _baseUrl;
  final http.Client _http;
  final AssetBundle _assets;

  static const Duration _timeout = Duration(seconds: 10);
  static const String _assetKey = 'assets/payloads/packs/manifest.json';

  /// The source used by the most recent [fetch] call. Null before first call.
  PackManifestSource? lastSource;

  /// Fetch the pack manifest.
  ///
  /// Tries network first; falls back to the bundled asset on any error
  /// (timeout, HTTP error, parse error) — the pack selector never shows a
  /// blank screen just because the CDN is briefly unreachable.
  Future<PackManifestResult> fetch() async {
    try {
      final url = Uri.parse('$_baseUrl/packs/manifest.json');
      final response = await _http.get(url).timeout(_timeout);
      if (response.statusCode == 200) {
        final json = jsonDecode(response.body) as Map<String, dynamic>;
        final manifest = PackManifest.fromJson(json);
        final result = PackManifestResult(
          manifest: manifest,
          source: PackManifestSource.network,
        );
        lastSource = result.source;
        return result;
      }
    } catch (_) {
      // Fall through to bundled asset.
    }

    final result = await _loadFromAsset();
    lastSource = result.source;
    return result;
  }

  Future<PackManifestResult> _loadFromAsset() async {
    final byteData = await _assets.load(_assetKey);
    final raw = utf8.decode(byteData.buffer.asUint8List());
    final json = jsonDecode(raw) as Map<String, dynamic>;
    final manifest = PackManifest.fromJson(json);
    return PackManifestResult(
      manifest: manifest,
      source: PackManifestSource.bundledAsset,
    );
  }

  /// Explicitly load from the bundled asset (public for testing).
  Future<PackManifestResult> loadBundled() => _loadFromAsset();
}
