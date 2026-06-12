import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:mindmeld/core/models.dart';

/// Mirrors the Python generator's codec exactly.
///
/// Generator references:
///   - payload.py: _word_hash, decode_secret, dequantize
///   - config.py:  QSIM_SCALE, QSIM_OFFSET, OBFUSCATE_SUFFIX, derive_obfuscate_key
class PayloadCodec {
  static const double _qsimScale = 32767.5;
  static const double _qsimOffset = 1.0;
  static const String _obfuscateSuffix = 'mindmeld-secret-v1';

  /// Decompress gzip bytes and parse JSON into a [DailyPayload].
  static DailyPayload decode(Uint8List gzBytes) {
    final decompressed = GZipCodec().decode(gzBytes);
    final jsonStr = utf8.decode(decompressed);
    final json = jsonDecode(jsonStr) as Map<String, dynamic>;
    return DailyPayload.fromJson(json);
  }

  /// Compute the 12-hex-char hash used to look up a word in the payload.
  ///
  /// Mirrors Python:
  ///   hashlib.sha1(f"{word.lower()}{salt}".encode()).hexdigest()[:12]
  static String hashWord(String word, String salt) {
    final input = '${word.toLowerCase()}$salt';
    final bytes = utf8.encode(input);
    final digest = sha1.convert(bytes);
    return digest.toString().substring(0, 12);
  }

  /// Look up a (lowercased, trimmed) word in the payload.
  ///
  /// Returns null if the word is not in the vocab (i.e. hash not found).
  static WordEntry? lookupWord(String word, DailyPayload payload) {
    final hash = hashWord(word, payload.salt);
    return payload.words[hash];
  }

  /// Decode the obfuscated secret field.
  ///
  /// Mirrors Python decode_secret / derive_obfuscate_key:
  ///   seed = sha1(salt + OBFUSCATE_SUFFIX)
  ///   key  = seed tiled to length of xored bytes
  ///   plain = XOR(xored, key)
  ///
  /// MUST only be called on win or give-up — never eagerly decode.
  static String decodeSecret(DailyPayload payload) {
    final xored = base64Decode(payload.s);
    final key = _deriveObfuscateKey(payload.salt, xored.length);
    final plain = Uint8List(xored.length);
    for (int i = 0; i < xored.length; i++) {
      plain[i] = xored[i] ^ key[i];
    }
    return utf8.decode(plain);
  }

  /// Dequantize a stored qsim integer back to a cosine similarity float.
  ///
  /// Mirrors Python: (qsim / QSIM_SCALE) - QSIM_OFFSET
  static double dequantize(int qsim) => (qsim / _qsimScale) - _qsimOffset;

  /// Derive the repeating XOR key for secret obfuscation.
  ///
  /// Mirrors Python derive_obfuscate_key:
  ///   seed = sha1(salt + OBFUSCATE_SUFFIX).digest()   # 20 bytes
  ///   key  = seed tiled to `length` bytes
  static Uint8List _deriveObfuscateKey(String salt, int length) {
    final input = '$salt$_obfuscateSuffix';
    final seed = sha1.convert(utf8.encode(input)).bytes;
    final key = Uint8List(length);
    for (int i = 0; i < length; i++) {
      key[i] = seed[i % seed.length];
    }
    return key;
  }
}
