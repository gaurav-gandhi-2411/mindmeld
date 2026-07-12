import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/core/design_tokens.dart';

/// WCAG 2.x relative-luminance contrast ratio between [a] and [b], computed
/// with [Color.computeLuminance] per https://www.w3.org/TR/WCAG21/#dfn-contrast-ratio.
double contrastRatio(Color a, Color b) {
  final la = a.computeLuminance();
  final lb = b.computeLuminance();
  final lighter = la > lb ? la : lb;
  final darker = la > lb ? lb : la;
  return (lighter + 0.05) / (darker + 0.05);
}

void main() {
  const wcagAA = 4.5;

  group('WarmerTokens contrast — WCAG AA (4.5:1)', () {
    for (final MapEntry(key: name, value: tokens) in {
      'light': WarmerTokens.light,
      'dark': WarmerTokens.dark,
    }.entries) {
      final heatBands = {
        'win': tokens.win,
        'scorching': tokens.scorching,
        'hot': tokens.hot,
        'warm': tokens.warm,
        'cold': tokens.cold,
        'freezing': tokens.freezing,
      };

      for (final MapEntry(key: bandName, value: heat) in heatBands.entries) {
        test('$name/$bandName: text on tintBg >= $wcagAA', () {
          final ratio = contrastRatio(heat.text, heat.tintBg);
          expect(
            ratio,
            greaterThanOrEqualTo(wcagAA),
            reason: '$name/$bandName contrast was ${ratio.toStringAsFixed(2)}',
          );
        });
      }

      test('$name: accentInk on accent >= $wcagAA', () {
        final ratio = contrastRatio(tokens.accentInk, tokens.accent);
        expect(ratio, greaterThanOrEqualTo(wcagAA));
      });

      test('$name: accentText on canvas >= $wcagAA', () {
        final ratio = contrastRatio(tokens.accentText, tokens.canvas);
        expect(ratio, greaterThanOrEqualTo(wcagAA));
      });

      test('$name: text1 on canvas >= $wcagAA', () {
        final ratio = contrastRatio(tokens.text1, tokens.canvas);
        expect(ratio, greaterThanOrEqualTo(wcagAA));
      });

      test('$name: text1 on surface >= $wcagAA', () {
        final ratio = contrastRatio(tokens.text1, tokens.surface);
        expect(ratio, greaterThanOrEqualTo(wcagAA));
      });
    }
  });

  group('buildWarmerTheme smoke tests', () {
    test('light theme wires tokens through ThemeData', () {
      final theme = buildWarmerTheme(Brightness.light);
      expect(theme.scaffoldBackgroundColor, WarmerTokens.light.canvas);
      expect(theme.extension<WarmerTokens>(), isNotNull);
      expect(theme.colorScheme.primary, WarmerTokens.light.accent);
    });

    test('dark theme wires tokens through ThemeData', () {
      final theme = buildWarmerTheme(Brightness.dark);
      expect(theme.scaffoldBackgroundColor, WarmerTokens.dark.canvas);
      expect(theme.extension<WarmerTokens>(), isNotNull);
      expect(theme.colorScheme.primary, WarmerTokens.dark.accent);
    });
  });

  group('buildPackTheme', () {
    test('light accent gets dark ink', () {
      final base = buildWarmerTheme(Brightness.light);
      const lightAccent = Color(0xFFC0913F);
      final packTheme = buildPackTheme(base, lightAccent, lightAccent);
      expect(packTheme.colorScheme.onPrimary, const Color(0xFF26231F));
    });

    test('dark accent gets white ink', () {
      final base = buildWarmerTheme(Brightness.light);
      const darkAccent = Color(0xFF2F4C36);
      final packTheme = buildPackTheme(base, darkAccent, darkAccent);
      expect(packTheme.colorScheme.onPrimary, Colors.white);
    });
  });
}
