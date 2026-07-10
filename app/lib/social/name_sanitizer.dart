/// Sanitization for user-chosen display names and group names (6a Social).
///
/// This is the FIRST of two layers: this module cleans and length-bounds raw
/// input; `moderation_blocklist.dart` applies the profanity/reserved-word
/// check on top of the cleaned result. `firestore.rules` re-enforces length
/// (and, separately, a charset constraint) server-side as defense in depth --
/// see the launch-hardening spec's part 2 for why the richer moderation stays
/// client-side only.
library;

/// Why a name was rejected. Exposed for tests/logging ONLY -- the UI must
/// always show a single generic friendly message regardless of which reason
/// fired (never echo "contains profanity" etc. back to the player).
enum NameRejectionReason {
  /// Nothing was left after trimming/stripping control, zero-width, and
  /// bidi-override characters.
  empty,

  /// Exceeded the caller-supplied max length after cleaning.
  tooLong,

  /// Matched the profanity or reserved-word blocklist (see
  /// `moderation_blocklist.dart`).
  blocked,
}

/// Outcome of [sanitizeName] (and, via `SocialService.validateName`, of the
/// combined sanitize+moderate check).
class NameSanitizeResult {
  const NameSanitizeResult.ok(this.cleaned) : rejectionReason = null;

  const NameSanitizeResult.rejected(NameRejectionReason reason)
      : cleaned = null,
        rejectionReason = reason;

  /// The cleaned name. Present only when sanitization succeeded.
  final String? cleaned;

  /// Present only when sanitization/moderation rejected the input.
  final NameRejectionReason? rejectionReason;

  bool get isOk => cleaned != null;
}

// Unicode ranges/codepoints stripped unconditionally, regardless of script
// or language:
//   - Cc control characters: C0 controls (U+0000-U+001F), DEL (U+007F), and
//     C1 controls (U+0080-U+009F).
//   - Zero-width / invisible characters that can pad a name or hide extra
//     content inside it: ZERO WIDTH SPACE (U+200B), ZERO WIDTH NON-JOINER
//     (U+200C), ZERO WIDTH JOINER (U+200D), ZERO WIDTH NO-BREAK SPACE / BOM
//     (U+FEFF), WORD JOINER (U+2060).
//   - RTL/bidi embedding, override, and isolate control characters, plus
//     ARABIC LETTER MARK (U+061C) -- a known vector for visually reversing or
//     disguising a name (e.g. to spoof a reserved word or another player's
//     name): LRE/RLE/PDF/LRO/RLO (U+202A-U+202E), LRI/RLI/FSI/PDI
//     (U+2066-U+2069).
final RegExp _strippablePattern = RegExp(
  '[' // one combined character class, built from three named ranges below
  '\u0000-\u001F\u007F-\u009F' // Cc control chars: C0, DEL, C1
  '\u200B\u200C\u200D\uFEFF\u2060' // zero-width / invisible chars
  '\u061C\u202A-\u202E\u2066-\u2069'
  ']',
);

/// Clean a raw user-entered name for storage/display.
///
/// Trims whitespace, strips the control/zero-width/bidi-override characters
/// documented on [_strippablePattern], and enforces [maxLength] on the
/// RESULT (post-strip) -- this REJECTS rather than truncates an over-length
/// name, so a caller can show a clear "too long" message instead of silently
/// saving a mangled version of what the user typed.
///
/// Scope limitation (documented, not an oversight): this does NOT perform
/// full Unicode NFC/NFKC normalization. `pubspec.yaml` has no existing
/// normalization package, and pulling one in purely for this launch-security
/// pass wasn't judged worth the new dependency -- accepted as a residual gap.
/// The control/zero-width/bidi stripping above is unconditional and is the
/// load-bearing part of this function (invisible/disguising characters are
/// the realistic threat this pass targets); see [foldConfusablesForModeration]
/// for the separate, narrowly-scoped homoglyph handling used only by the
/// blocklist check in `moderation_blocklist.dart`.
NameSanitizeResult sanitizeName(String raw, {required int maxLength}) {
  final cleaned = raw.replaceAll(_strippablePattern, '').trim();
  if (cleaned.isEmpty) {
    return const NameSanitizeResult.rejected(NameRejectionReason.empty);
  }
  if (cleaned.length > maxLength) {
    return const NameSanitizeResult.rejected(NameRejectionReason.tooLong);
  }
  return NameSanitizeResult.ok(cleaned);
}

/// Confusable-character -> Latin mapping for ONE specific threat: dodging a
/// literal string-match reserved-word/profanity filter by substituting a
/// visually-identical character from another script (e.g. a Cyrillic
/// lookalike in place of Latin "a", to make an impersonation attempt read as
/// "admin" to a human but not match a naive `== 'admin'` check).
///
/// Scope limitation (documented, not exhaustive): this is a small,
/// hand-written map of the common Cyrillic/Greek lookalikes for Latin a-z --
/// NOT a full Unicode confusables table (see Unicode Technical Report #39
/// for what a complete implementation would cover). That's out of scope for
/// this launch-security pass; this covers the realistic impersonation
/// vector against the reserved-word list, not exhaustive Unicode security.
///
/// Applied ONLY inside [foldConfusablesForModeration], which itself is used
/// ONLY for building a throwaway lowercase copy for the blocklist
/// comparison in `moderation_blocklist.dart` -- it never rewrites the name
/// that is actually stored or displayed, so a legitimate Cyrillic, Greek, or
/// any other non-Latin-script display name still saves and renders exactly
/// as typed.
final Map<String, String> confusablesToLatin = {
  '\u0430': 'a', // CYRILLIC SMALL LETTER A
  '\u0410': 'a', // CYRILLIC CAPITAL LETTER A
  '\u0435': 'e', // CYRILLIC SMALL LETTER IE
  '\u0415': 'e', // CYRILLIC CAPITAL LETTER IE
  '\u043E': 'o', // CYRILLIC SMALL LETTER O
  '\u041E': 'o', // CYRILLIC CAPITAL LETTER O
  '\u0440': 'p', // CYRILLIC SMALL LETTER ER
  '\u0420': 'p', // CYRILLIC CAPITAL LETTER ER
  '\u0441': 'c', // CYRILLIC SMALL LETTER ES
  '\u0421': 'c', // CYRILLIC CAPITAL LETTER ES
  '\u0445': 'x', // CYRILLIC SMALL LETTER HA
  '\u0425': 'x', // CYRILLIC CAPITAL LETTER HA
  '\u0443': 'y', // CYRILLIC SMALL LETTER U
  '\u0423': 'y', // CYRILLIC CAPITAL LETTER U
  '\u0399': 'i', // GREEK CAPITAL LETTER IOTA
  '\u03B9': 'i', // GREEK SMALL LETTER IOTA
  '\u0391': 'a', // GREEK CAPITAL LETTER ALPHA
  '\u03B1': 'a', // GREEK SMALL LETTER ALPHA
  '\u039F': 'o', // GREEK CAPITAL LETTER OMICRON
  '\u03BF': 'o', // GREEK SMALL LETTER OMICRON
};

/// Build a lowercase copy of [s] with the [confusablesToLatin] substitutions
/// applied -- for blocklist comparison ONLY (see [confusablesToLatin]'s doc
/// comment for the scope limitation and why this never touches the
/// stored/displayed name).
String foldConfusablesForModeration(String s) {
  final buffer = StringBuffer();
  for (final rune in s.runes) {
    final ch = String.fromCharCode(rune);
    buffer.write(confusablesToLatin[ch] ?? ch);
  }
  return buffer.toString().toLowerCase();
}
