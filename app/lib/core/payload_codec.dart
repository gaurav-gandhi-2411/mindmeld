import 'dart:convert';
import 'dart:typed_data';

import 'package:archive/archive.dart';
import 'package:crypto/crypto.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/normalize.dart';

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
  ///
  /// Uses [archive.GZipDecoder] which works on all platforms including web,
  /// unlike dart:io's [GZipCodec] which is unavailable in browser contexts.
  static DailyPayload decode(Uint8List gzBytes) {
    final decompressed = GZipDecoder().decodeBytes(gzBytes);
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

  /// Look up a player guess in the payload using a 4-step tolerance chain.
  ///
  /// For lang 'hi-en', the lookup order is:
  ///   1. exact:  hash(lower(guess)) in words
  ///   2. alt:    hash(lower(guess)) in alt
  ///   3. fold:   hash(normalizeHiEn(guess)) in words
  ///   4. alt+fold: hash(normalizeHiEn(guess)) in alt
  ///   First hit wins.
  ///
  /// For lang 'en', only step 1 is used (exact words lookup, no fold).
  /// This intentionally prevents e.g. 'cofi' matching 'coffee' via fold
  /// in English mode — the fold rules are hi-en-specific romanization
  /// conventions, not valid English transformations.
  ///
  /// The returned [WordEntry] carries the rank/qsim of the canonical word
  /// (variant spellings resolve to the same rank as their canonical form).
  ///
  /// Returns null if no step finds a match (word not in vocab or alt map).
  static WordEntry? lookupWord(String word, DailyPayload payload) {
    final lower = word.trim().toLowerCase();

    // Step 1: exact match in words map (all langs)
    final h1 = hashWord(lower, payload.salt);
    final step1 = payload.words[h1];
    if (step1 != null) return step1;

    // Steps 2-4 are hi-en only; English uses exact lookup only.
    if (payload.lang != 'hi-en') return null;

    // Step 2: exact lower hash in alt map
    final step2 = payload.alt[h1];
    if (step2 != null) return step2;

    // Steps 3-4: normalize via romanization fold
    final norm = normalizeHiEn(lower);
    if (norm != lower) {
      final h3 = hashWord(norm, payload.salt);

      // Step 3: normalized form in words map
      final step3 = payload.words[h3];
      if (step3 != null) return step3;

      // Step 4: normalized form in alt map
      final step4 = payload.alt[h3];
      if (step4 != null) return step4;
    }

    return null;
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
