/// Regression test for the design-token dedup audit (chore/dedup-design-
/// tokens): asserts that every value formerly hardcoded as a `Color(0x...)`
/// literal outside [WarmerTokens] still resolves to the exact same ARGB
/// int now that it's sourced from a named token — i.e. zero visual-behavior
/// change from the dedup.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/core/design_tokens.dart';
import 'package:mindmeld/core/packs.dart';
import 'package:mindmeld/features/branding/heat_rings_mark.dart';

void main() {
  group('WarmerColors (heat_rings_mark.dart) — byte-identical to prior literals', () {
    test('cold == former Color(0xFF6B89A8)', () {
      expect(WarmerColors.cold.toARGB32(), 0xFF6B89A8);
      expect(WarmerColors.cold, WarmerTokens.light.freezing.base);
    });

    test('cool == former Color(0xFF7E9BB5)', () {
      expect(WarmerColors.cool.toARGB32(), 0xFF7E9BB5);
      expect(WarmerColors.cool, WarmerTokens.light.cold.base);
    });

    test('warm == former Color(0xFFD9AE6B)', () {
      expect(WarmerColors.warm.toARGB32(), 0xFFD9AE6B);
      expect(WarmerColors.warm, WarmerTokens.light.warm.base);
    });

    test('hot == former Color(0xFFD65F49)', () {
      expect(WarmerColors.hot.toARGB32(), 0xFFD65F49);
      expect(WarmerColors.hot, WarmerTokens.light.scorching.base);
    });

    test('wordmarkAccent == former Color(0xFFDD6B4D)', () {
      expect(WarmerColors.wordmarkAccent.toARGB32(), 0xFFDD6B4D);
      expect(WarmerColors.wordmarkAccent, WarmerTokens.light.accent);
    });

    test('ground == former Color(0xFF171614)', () {
      expect(WarmerColors.ground.toARGB32(), 0xFF171614);
      expect(WarmerColors.ground, WarmerTokens.dark.canvas);
    });
  });

  group('kPackFallbackAccent (packs.dart) — byte-identical to former literal', () {
    test('== former Color(0xFFDD6B4D)', () {
      expect(kPackFallbackAccent.toARGB32(), 0xFFDD6B4D);
      expect(kPackFallbackAccent, WarmerTokens.light.accent);
    });
  });

  group('WarmerTokens.light.accentInk (pack_puzzle_list_screen.dart) '
      '— byte-identical to former literal', () {
    test('== former const Color(0xFF26231F)', () {
      expect(WarmerTokens.light.accentInk.toARGB32(), 0xFF26231F);
    });
  });
}
