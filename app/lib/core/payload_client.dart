import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:mindmeld/core/config.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/payload_codec.dart';

/// Describes where a payload was ultimately loaded from.
enum PayloadSource { network, bundledAsset }

/// Result of a payload fetch, including which source was used.
class PayloadResult {
  const PayloadResult({required this.payload, required this.source});

  final DailyPayload payload;
  final PayloadSource source;
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

  /// Fetch the payload for [lang] and [date] (format: yyyy-MM-dd).
  ///
  /// Tries network first; falls back to bundled asset on any error.
  /// Throws [Exception] only if both sources fail.
  Future<PayloadResult> fetch(String lang, String date) async {
    // 1. Try network
    try {
      final url = Uri.parse('$_baseUrl/$lang/$date.json.gz');
      final response = await _http.get(url).timeout(_timeout);
      if (response.statusCode == 200) {
        final payload = PayloadCodec.decode(
          Uint8List.fromList(response.bodyBytes),
        );
        return PayloadResult(payload: payload, source: PayloadSource.network);
      }
    } catch (_) {
      // Fall through to bundled asset.
    }

    // 2. Fall back to bundled asset
    return _loadFromAsset(lang, date);
  }

  /// Load payload directly from bundled assets (used by tests and offline mode).
  Future<PayloadResult> _loadFromAsset(String lang, String date) async {
    final assetKey = 'assets/payloads/$lang/$date.json.gz';
    final byteData = await _assets.load(assetKey);
    final bytes = byteData.buffer.asUint8List();
    final payload = PayloadCodec.decode(bytes);
    return PayloadResult(payload: payload, source: PayloadSource.bundledAsset);
  }

  /// Explicitly load from the bundled asset (public for testing).
  Future<PayloadResult> loadBundled(String lang, String date) =>
      _loadFromAsset(lang, date);
}
