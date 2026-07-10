/// Profanity + impersonation blocklist for user-chosen display names and
/// group names (6a Social). Runs AFTER `name_sanitizer.dart`'s
/// [sanitizeName] on the already-cleaned string.
///
/// Scope (documented, not exhaustive):
///   - EN profanity: a curated, reasonably-sized list of common
///     obscenities/slurs that would clearly need blocking on a public
///     leaderboard — not an exhaustive academic list.
///   - Hinglish (romanized Hindi) profanity: same curation standard,
///     romanized consistent with `generator/vocab/hinglish.txt`'s spelling
///     conventions (plain lowercase romanization, no diacritics).
///   - Reserved words: blocks impersonation of app staff/system identities.
///
/// Matching strategy (documented reasoning): names are split into tokens on
/// non-alphanumeric boundaries (so "the_admin" -> ["the", "admin"], but
/// "admin123" stays one token since digits aren't a boundary), then each
/// token is folded through [foldConfusablesForModeration] before comparison.
/// A token is blocked if it EQUALS a listed word, or — for the specific
/// impersonation pattern of a reserved word decorated with trailing digits
/// (e.g. "admin123", "support007") — if it is the reserved word immediately
/// followed by one or more digits. Deliberately NOT a bare substring/prefix
/// match: the spec's own caution about "mod" also matching "moderate" or
/// "modern" is real, and a bare prefix match on short reserved words like
/// "mod" would false-positive on plenty of legitimate words. Profanity words
/// use the same equals-or-decorated-with-trailing-digits rule for the same
/// reason (avoids the "Scunthorpe problem" of blocking legitimate words that
/// merely contain a profanity word as a substring).
library;

import 'package:mindmeld/social/name_sanitizer.dart' show foldConfusablesForModeration;

/// Impersonation-flavored reserved words — matched case-insensitively via
/// [_tokenMatchesReserved]. "warmer" is the app's own name.
const List<String> reservedWords = [
  'admin',
  'official',
  'moderator',
  'mod',
  'support',
  'warmer',
  'staff',
  'system',
];

/// Curated EN profanity/slur list. Intentionally not exhaustive — see the
/// library doc comment above for the sizing rationale.
const List<String> _profanityEn = [
  'fuck',
  'shit',
  'bitch',
  'bastard',
  'asshole',
  'cunt',
  'dick',
  'pussy',
  'whore',
  'slut',
  'nigger',
  'nigga',
  'faggot',
  'fag',
  'retard',
  'cock',
  'twat',
  'wanker',
  'motherfucker',
  'dyke',
  'spic',
  'chink',
  'gook',
];

/// Curated Hinglish (romanized Hindi) profanity/slur list. Romanization
/// follows the same plain-lowercase convention as
/// `generator/vocab/hinglish.txt` (e.g. "yaar", "gussa", "jhooth") — no
/// diacritics, common transliteration spellings.
const List<String> _profanityHinglish = [
  'chutiya',
  'chutiye',
  'madarchod',
  'behenchod',
  'bhosdike',
  'bhosdiwala',
  'gandu',
  'gaand',
  'lund',
  'lauda',
  'laude',
  'randi',
  'harami',
  'haramzada',
  'kamina',
  'kamini',
  'chinaal',
  'kutiya',
  'saali',
  'bhenchod',
];

/// True if [token] is exactly [word], or [word] immediately followed by one
/// or more digits (the "admin123" / "chutiya1" impersonation-decoration
/// pattern) — see the library doc comment for why this is NOT a bare prefix
/// match.
bool _tokenMatchesDecorated(String token, String word) {
  if (token == word) return true;
  if (token.length <= word.length || !token.startsWith(word)) return false;
  final suffix = token.substring(word.length);
  return RegExp(r'^[0-9]+$').hasMatch(suffix);
}

/// Splits [s] into alphanumeric tokens (non-alphanumeric runs are
/// boundaries), after folding confusable characters to their Latin
/// lookalike and lowercasing (see [foldConfusablesForModeration]).
///
/// A token built entirely from characters outside a-z0-9 (e.g. a legitimate
/// Devanagari name with no Latin/digit content at all) simply never appears
/// in the returned list — it can't match anything on the blocklist below,
/// which is the correct, safe outcome (no false positives on non-Latin
/// legitimate names).
List<String> _tokenize(String s) {
  final folded = foldConfusablesForModeration(s);
  return folded.split(RegExp('[^a-z0-9]+')).where((t) => t.isNotEmpty).toList();
}

/// True if [name] should be rejected as impersonation or profanity/abuse.
///
/// Callers should pass the ALREADY-SANITIZED name (post [sanitizeName]) —
/// this function does not itself strip control/zero-width/bidi characters.
bool isBlockedName(String name) {
  final tokens = _tokenize(name);
  for (final token in tokens) {
    for (final word in reservedWords) {
      if (_tokenMatchesDecorated(token, word)) return true;
    }
    for (final word in _profanityEn) {
      if (_tokenMatchesDecorated(token, word)) return true;
    }
    for (final word in _profanityHinglish) {
      if (_tokenMatchesDecorated(token, word)) return true;
    }
  }
  return false;
}
