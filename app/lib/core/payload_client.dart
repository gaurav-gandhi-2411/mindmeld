import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:mindmeld/core/config.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/payload_codec.dart';

/// Describes where a payload was ultimately loaded from.
enum PayloadSource { network, bundledAsset }

/// Result of a payload fetch, including which source was used.
class PayloadResult {
  const PayloadResult({
    required this.payload,
    required this.source,
    this.servedDate,
    this.requestedDate,
  });

  final DailyPayload payload;
  final PayloadSource source;

  /// Date (yyyy-MM-dd) of the puzzle actually served. Null when the producer
  /// did not record it (pack/onboarding fetches, legacy test fakes).
  final String? servedDate;

  /// Date (yyyy-MM-dd) the caller asked for. Null when not recorded.
  final String? requestedDate;

  /// True when an older puzzle was served because the requested day's payload
  /// is missing (B2 lookback).
  bool get isFallbackDate =>
      servedDate != null &&
      requestedDate != null &&
      servedDate != requestedDate;
}

/// Maximum number of days [PayloadClient.fetch] steps back when the requested
/// day's payload is definitively missing. 14 days covers a two-week generator
/// outage while bounding the worst case to 14 quick 404 round-trips and
/// keeping the substitute puzzle reasonably recent.
const int kMaxPayloadLookbackDays = 14;

/// Returns [date] (yyyy-MM-dd) shifted back by [days], using UTC date-only
/// arithmetic so local-timezone DST changes can never skip or repeat a day.
String shiftDateBack(String date, int days) {
  final d = DateTime.parse(date);
  final s = DateTime.utc(d.year, d.month, d.day - days);
  String two(int n) => n.toString().padLeft(2, '0');
  return '${s.year.toString().padLeft(4, '0')}-${two(s.month)}-${two(s.day)}';
}

/// Fetches daily puzzle payloads from the network, falling back to bundled assets.
///
/// Network fetch: GET {baseUrl}/payloads/{lang}/{date}.json.gz
/// Fallback:      assets/payloads/{lang}/{date}.json.gz bundled in APK
///
/// On any network failure (timeout, HTTP error, parse error) the bundled
/// asset is served transparently. [PayloadResult.source] tells the caller
/// which path was used.
class PayloadClient {
  PayloadClient({
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

  /// The source used by the most recent [fetch] call.
  ///
  /// Null before the first call completes.  Updated atomically inside [fetch]
  /// so integration tests can assert which path was taken without needing to
  /// thread a result value back through the widget tree.
  PayloadSource? lastSource;

  /// Fetch the payload for [lang] and [date] (format: yyyy-MM-dd).
  ///
  /// Tries network first; falls back to bundled asset on any error.
  /// Throws [Exception] only if both sources fail.
  /// Sets [lastSource] to reflect which path was used.
  Future<PayloadResult> fetch(String lang, String date) async {
    // 1. Try network
    var missing = false;
    try {
      final (result, status) = await _fetchNetwork(lang, date, date);
      if (result != null) {
        lastSource = result.source;
        return result;
      }
      // Only a 404 means "no puzzle for this day"; other statuses are errors.
      missing = status == 404;
    } catch (_) {
      // Fall through to bundled asset. Transport errors/timeouts never look
      // back: an offline user must not wait up to 14 x timeout.
    }

    // 2. Fall back to bundled asset
    try {
      final result = await _loadFromAsset(lang, date, date);
      lastSource = result.source;
      return result;
    } catch (_) {
      if (!missing) rethrow;
    }

    // 3. Day definitively missing on network and in assets: step back to the
    // latest available puzzle (B2).
    for (var i = 1; i <= kMaxPayloadLookbackDays; i++) {
      final prev = shiftDateBack(date, i);
      var prevMissing = false;
      try {
        final (result, status) = await _fetchNetwork(lang, prev, date);
        if (result != null) {
          lastSource = result.source;
          return result;
        }
        prevMissing = status == 404;
      } catch (_) {
        // Not a definite miss; still try the bundled asset below.
      }
      try {
        final result = await _loadFromAsset(lang, prev, date);
        lastSource = result.source;
        return result;
      } catch (_) {
        if (!prevMissing) break;
      }
    }
    throw Exception(
      'No puzzle available for $lang on $date '
      '(looked back $kMaxPayloadLookbackDays days)',
    );
  }

  /// GETs the network payload for [date]. Returns a null result (with the
  /// HTTP status) on a non-200 reply; throws on transport/decode errors.
  Future<(PayloadResult?, int)> _fetchNetwork(
    String lang,
    String date,
    String requested,
  ) async {
    final url = Uri.parse('$_baseUrl/$lang/$date.json.gz');
    final response = await _http.get(url).timeout(_timeout);
    if (response.statusCode != 200) return (null, response.statusCode);
    final payload = PayloadCodec.decode(Uint8List.fromList(response.bodyBytes));
    return (
      PayloadResult(
        payload: payload,
        source: PayloadSource.network,
        servedDate: date,
        requestedDate: requested,
      ),
      200,
    );
  }

  /// Load payload directly from bundled assets (used by tests and offline mode).
  Future<PayloadResult> _loadFromAsset(
    String lang,
    String date, [
    String? requested,
  ]) async {
    final assetKey = 'assets/payloads/$lang/$date.json.gz';
    final byteData = await _assets.load(assetKey);
    final bytes = byteData.buffer.asUint8List();
    final payload = PayloadCodec.decode(bytes);
    return PayloadResult(
      payload: payload,
      source: PayloadSource.bundledAsset,
      servedDate: date,
      requestedDate: requested ?? date,
    );
  }

  /// Explicitly load from the bundled asset (public for testing).
  Future<PayloadResult> loadBundled(String lang, String date) =>
      _loadFromAsset(lang, date);

  /// Fetch puzzle [idx] (1-based) of themed pack [packId] for [lang].
  ///
  /// Network fetch: GET {baseUrl}/packs/{packId}/{lang}/{NNN}.json.gz
  /// Fallback:      assets/payloads/packs/{packId}/{lang}/{NNN}.json.gz
  ///
  /// [idx] is zero-padded to 3 digits (e.g. 1 -> "001") to match the
  /// generator-side naming contract. Same timeout/fallback semantics as
  /// [fetch].
  Future<PayloadResult> fetchPack(String packId, int idx, String lang) async {
    final idxStr = idx.toString().padLeft(3, '0');
    try {
      final url = Uri.parse('$_baseUrl/packs/$packId/$lang/$idxStr.json.gz');
      final response = await _http.get(url).timeout(_timeout);
      if (response.statusCode == 200) {
        final payload = PayloadCodec.decode(
          Uint8List.fromList(response.bodyBytes),
        );
        final result =
            PayloadResult(payload: payload, source: PayloadSource.network);
        lastSource = result.source;
        return result;
      }
    } catch (_) {
      // Fall through to bundled asset.
    }

    final result = await _loadPackFromAsset(packId, idx, lang);
    lastSource = result.source;
    return result;
  }

  /// Load a pack payload directly from bundled assets (used by tests).
  Future<PayloadResult> _loadPackFromAsset(
      String packId, int idx, String lang) async {
    final idxStr = idx.toString().padLeft(3, '0');
    final assetKey = 'assets/payloads/packs/$packId/$lang/$idxStr.json.gz';
    final byteData = await _assets.load(assetKey);
    final bytes = byteData.buffer.asUint8List();
    final payload = PayloadCodec.decode(bytes);
    return PayloadResult(payload: payload, source: PayloadSource.bundledAsset);
  }

  /// Explicitly load a pack payload from the bundled asset (public for testing).
  Future<PayloadResult> loadBundledPack(String packId, int idx, String lang) =>
      _loadPackFromAsset(packId, idx, lang);

  /// Fetch the dedicated first-session onboarding puzzle for [lang]
  /// (first-session-hook wave).
  ///
  /// Asset-FIRST, network fallback — the INVERSE order of [fetch]/[fetchPack].
  /// A brand-new player's very first paint must never depend on the CDN being
  /// reachable; the bundled asset ships with the app and changes far less
  /// often than a daily puzzle, so serving it first costs nothing in practice
  /// while removing "the onboarding puzzle wouldn't load on a bad connection"
  /// as a failure mode entirely.
  ///
  /// Network fetch (only reached if the bundled asset itself fails to load —
  /// should never happen in a shipped build, but keeps a future-app-update
  /// refresh path open): GET {baseUrl}/onboarding/{lang}.json.gz
  Future<PayloadResult> fetchOnboarding(String lang) async {
    try {
      final result = await _loadOnboardingFromAsset(lang);
      lastSource = result.source;
      return result;
    } catch (_) {
      // Fall through to network.
    }

    final url = Uri.parse('$_baseUrl/onboarding/$lang.json.gz');
    final response = await _http.get(url).timeout(_timeout);
    if (response.statusCode == 200) {
      final payload = PayloadCodec.decode(
        Uint8List.fromList(response.bodyBytes),
      );
      final result =
          PayloadResult(payload: payload, source: PayloadSource.network);
      lastSource = result.source;
      return result;
    }
    throw Exception(
        'Failed to fetch onboarding payload for $lang: HTTP ${response.statusCode}');
  }

  /// Load the onboarding payload directly from bundled assets (used by tests
  /// and as [fetchOnboarding]'s primary path).
  Future<PayloadResult> _loadOnboardingFromAsset(String lang) async {
    final assetKey = 'assets/payloads/onboarding/$lang.json.gz';
    final byteData = await _assets.load(assetKey);
    final bytes = byteData.buffer.asUint8List();
    final payload = PayloadCodec.decode(bytes);
    return PayloadResult(payload: payload, source: PayloadSource.bundledAsset);
  }

  /// Explicitly load the onboarding payload from the bundled asset (public
  /// for testing).
  Future<PayloadResult> loadBundledOnboarding(String lang) =>
      _loadOnboardingFromAsset(lang);
}
