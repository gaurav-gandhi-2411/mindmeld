// ignore_for_file: avoid_classes_with_only_static_members

/// Romanized-Hindi spelling normalization for Mindmeld hi-en payloads.
///
/// This is a LOOKUP-FOLDING function for hi-en — not a linguistic transcription
/// system or phonology model. The sole purpose is to collapse common romanization
/// variants onto a single canonical form so that hash lookups in the payload
/// `words` map succeed regardless of which common spelling the player typed.
///
/// Normalization pass order (applied once, left-to-right):
///   1. Strip whitespace + lowercase
///   2. chh → ch          (chh is a common over-romanized aspirate cluster)
///   3. aa  → a           (long-a marker that many writers omit)
///   4. ee  → i           (long-i marker)
///   5. oo  → u           (long-u marker)
///
/// Each substitution is applied globally (replaceAll). The order is fixed so
/// that "chha" → "cha" (chh→ch first, then no "aa" remains).
///
/// Mirrors generator/normalize.py EXACTLY (same rule order, same semantics).
/// The Python implementation uses re.Pattern.sub() which replaces all
/// non-overlapping occurrences left-to-right — identical to Dart's replaceAll.
///
/// Edge case: 'aaa' → 'a' (Python: re.sub('aa', 'a', 'aaa') = 'aa' → wait,
/// actually Python replaces left-to-right non-overlapping: 'aaa' → 'a' + 'a'
/// trailing = 'aa'... let's check: 'aaa': positions 0-1 match 'aa' → 'a',
/// leaving 'a' at position 2 → result 'aa'. Dart replaceAll matches
/// non-overlapping left-to-right identically. So 'aaa' → 'aa' in both.
/// The docstring above that says "collapse runs" would require iteration;
/// the Python code does NOT iterate — it calls sub() exactly once per rule.
/// Dart matches this with a single replaceAll() per rule.
String normalizeHiEn(String word) {
  // Step 1: strip whitespace + lowercase
  var result = word.trim().toLowerCase();
  // Step 2: chh → ch
  result = result.replaceAll('chh', 'ch');
  // Step 3: aa → a
  result = result.replaceAll('aa', 'a');
  // Step 4: ee → i
  result = result.replaceAll('ee', 'i');
  // Step 5: oo → u
  result = result.replaceAll('oo', 'u');
  return result;
}
