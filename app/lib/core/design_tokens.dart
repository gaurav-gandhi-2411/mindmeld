import 'package:flutter/material.dart';
import 'package:mindmeld/core/models.dart';

/// A single temperature band's colour treatment: a saturated [base] used for
/// borders/pills, a muted [tintBg] used for row backgrounds, and a
/// high-contrast [text] colour for labels sitting on [tintBg].
class HeatSpec {
  const HeatSpec({required this.base, required this.tintBg, required this.text});

  /// Saturated band colour — used for borders, pill fills, and accents.
  final Color base;

  /// Muted background tint — never a full-saturation fill.
  final Color tintBg;

  /// Text colour with AA contrast against [tintBg].
  final Color text;

  /// Linearly interpolates each channel between [a] and [b].
  static HeatSpec lerp(HeatSpec a, HeatSpec b, double t) {
    return HeatSpec(
      base: Color.lerp(a.base, b.base, t)!,
      tintBg: Color.lerp(a.tintBg, b.tintBg, t)!,
      text: Color.lerp(a.text, b.text, t)!,
    );
  }
}

/// Spacing scale for paddings/gaps, in logical pixels.
///
/// Values are the ones already in repeated use across `app/lib` (confirmed
/// by grepping `EdgeInsets`/`SizedBox` call sites) — not invented. Kept as
/// plain `static const double`s rather than [WarmerTokens] fields because
/// spacing doesn't vary by brightness and so needs no [ThemeExtension.lerp]
/// support; a private constructor keeps this a namespace, not a value type.
class WarmerSpacing {
  const WarmerSpacing._();

  /// 4 — tightest gap (icon-to-label, hairline padding).
  static const double xs = 4;

  /// 8 — default gap between related inline elements.
  static const double sm = 8;

  /// 12 — default gap between stacked elements within a card.
  static const double md = 12;

  /// 16 — default screen-edge/card padding.
  static const double lg = 16;

  /// 24 — section-level padding/gap.
  static const double xl = 24;

  /// 32 — large vertical rhythm between major sections.
  static const double xxl = 32;
}

/// Border-radius scale, in logical pixels.
///
/// Values are the ones already in repeated use across `app/lib` (confirmed
/// by grepping `BorderRadius.circular(`) — not invented. Kept as plain
/// `static const double`s rather than [WarmerTokens] fields for the same
/// reason as [WarmerSpacing]: radii don't need brightness-based lerping.
class WarmerRadius {
  const WarmerRadius._();

  /// 6 — small chips/badges.
  static const double xs = 6;

  /// 8 — inputs, small buttons, snack bars.
  static const double sm = 8;

  /// 12 — default card/button radius.
  static const double md = 12;

  /// 16 — larger cards.
  static const double lg = 16;

  /// 20 — full-surface sheets (dialogs, bottom sheets).
  static const double xl = 20;
}

/// Single source of truth for the "calm-minimal" design palette.
///
/// Accessed via `Theme.of(context).extension<WarmerTokens>()`. See
/// spec-aesthetic-pass.md for the full rationale behind every value.
class WarmerTokens extends ThemeExtension<WarmerTokens> {
  const WarmerTokens({
    required this.canvas,
    required this.surface,
    required this.hairline,
    required this.text1,
    required this.text2,
    required this.text3,
    required this.accent,
    required this.accentText,
    required this.accentInk,
    required this.win,
    required this.scorching,
    required this.hot,
    required this.warm,
    required this.cold,
    required this.freezing,
  });

  /// App-wide background — behind cards/surfaces.
  final Color canvas;

  /// Card/sheet/app-bar surface colour.
  final Color surface;

  /// Hairline border/divider colour.
  final Color hairline;

  /// Primary text colour (headings, body).
  final Color text1;

  /// Secondary text colour (subtitles, labels).
  final Color text2;

  /// Tertiary text colour (micro-labels, placeholders).
  final Color text3;

  /// Brand accent colour (buttons, links, focus rings).
  final Color accent;

  /// Text-on-canvas variant of [accent] (links, outlined-button labels).
  final Color accentText;

  /// Text/icon colour to place on top of a solid [accent] fill.
  final Color accentInk;

  /// Win band (rank 1 — the secret word itself).
  final HeatSpec win;

  /// Scorching band.
  final HeatSpec scorching;

  /// Hot band.
  final HeatSpec hot;

  /// Warm band.
  final HeatSpec warm;

  /// Cold band.
  final HeatSpec cold;

  /// Freezing band.
  final HeatSpec freezing;

  /// Looks up the [HeatSpec] for a given [TemperatureBand].
  HeatSpec heatFor(TemperatureBand band) {
    switch (band) {
      case TemperatureBand.win:
        return win;
      case TemperatureBand.scorching:
        return scorching;
      case TemperatureBand.hot:
        return hot;
      case TemperatureBand.warm:
        return warm;
      case TemperatureBand.cold:
        return cold;
      case TemperatureBand.freezing:
        return freezing;
    }
  }

  @override
  WarmerTokens copyWith({
    Color? canvas,
    Color? surface,
    Color? hairline,
    Color? text1,
    Color? text2,
    Color? text3,
    Color? accent,
    Color? accentText,
    Color? accentInk,
    HeatSpec? win,
    HeatSpec? scorching,
    HeatSpec? hot,
    HeatSpec? warm,
    HeatSpec? cold,
    HeatSpec? freezing,
  }) {
    return WarmerTokens(
      canvas: canvas ?? this.canvas,
      surface: surface ?? this.surface,
      hairline: hairline ?? this.hairline,
      text1: text1 ?? this.text1,
      text2: text2 ?? this.text2,
      text3: text3 ?? this.text3,
      accent: accent ?? this.accent,
      accentText: accentText ?? this.accentText,
      accentInk: accentInk ?? this.accentInk,
      win: win ?? this.win,
      scorching: scorching ?? this.scorching,
      hot: hot ?? this.hot,
      warm: warm ?? this.warm,
      cold: cold ?? this.cold,
      freezing: freezing ?? this.freezing,
    );
  }

  @override
  WarmerTokens lerp(ThemeExtension<WarmerTokens>? other, double t) {
    if (other is! WarmerTokens) return this;
    return WarmerTokens(
      canvas: Color.lerp(canvas, other.canvas, t)!,
      surface: Color.lerp(surface, other.surface, t)!,
      hairline: Color.lerp(hairline, other.hairline, t)!,
      text1: Color.lerp(text1, other.text1, t)!,
      text2: Color.lerp(text2, other.text2, t)!,
      text3: Color.lerp(text3, other.text3, t)!,
      accent: Color.lerp(accent, other.accent, t)!,
      accentText: Color.lerp(accentText, other.accentText, t)!,
      accentInk: Color.lerp(accentInk, other.accentInk, t)!,
      win: HeatSpec.lerp(win, other.win, t),
      scorching: HeatSpec.lerp(scorching, other.scorching, t),
      hot: HeatSpec.lerp(hot, other.hot, t),
      warm: HeatSpec.lerp(warm, other.warm, t),
      cold: HeatSpec.lerp(cold, other.cold, t),
      freezing: HeatSpec.lerp(freezing, other.freezing, t),
    );
  }

  /// Light-mode "calm-minimal" palette.
  static const WarmerTokens light = WarmerTokens(
    canvas: Color(0xFFFAF8F4),
    surface: Color(0xFFFFFFFF),
    hairline: Color(0xFFECE8E1),
    text1: Color(0xFF26231F),
    // text2/text3 darkened from the original 8A857C/B4AEA4 — launch-1 wave's
    // design-reviewer pass measured those at 3.46-3.67:1 / 2.08-2.20:1 against
    // canvas/surface, both failing WCAG AA (text3 failing even the large-text
    // 3.0:1 floor). These clear 4.5:1 against both canvas and surface with a
    // small margin (text2 5.37/5.70, text3 4.71/4.99) — see
    // design_tokens_test.dart's contrast tests. Same warm-neutral hue, just
    // darker; hierarchy (text1 > text2 > text3 lightness) preserved.
    text2: Color(0xFF6B665D),
    text3: Color(0xFF756F62),
    accent: Color(0xFFDD6B4D),
    accentText: Color(0xFFB04429),
    accentInk: Color(0xFF26231F),
    freezing: HeatSpec(
      base: Color(0xFF6B89A8),
      tintBg: Color(0xFFEDF0F2),
      text: Color(0xFF45586B),
    ),
    cold: HeatSpec(
      base: Color(0xFF7E9BB5),
      tintBg: Color(0xFFEDF0F2),
      text: Color(0xFF3F5163),
    ),
    warm: HeatSpec(
      base: Color(0xFFD9AE6B),
      tintBg: Color(0xFFF3EFE6),
      text: Color(0xFF6E6653),
    ),
    hot: HeatSpec(
      base: Color(0xFFE0895F),
      tintBg: Color(0xFFFCF3EA),
      text: Color(0xFF92601F),
    ),
    scorching: HeatSpec(
      base: Color(0xFFD65F49),
      tintBg: Color(0xFFFBF1EC),
      text: Color(0xFFB9472F),
    ),
    win: HeatSpec(
      base: Color(0xFFDD6B4D),
      tintBg: Color(0xFFF9EAE5),
      text: Color(0xFFB04429),
    ),
  );

  /// Dark-mode palette — purpose-derived, not a mechanical inversion of
  /// [light].
  static const WarmerTokens dark = WarmerTokens(
    canvas: Color(0xFF171614),
    surface: Color(0xFF201E1B),
    hairline: Color(0xFF302D29),
    text1: Color(0xFFF2EFE9),
    text2: Color(0xFF9C968C),
    // Lightened from 6E6960 — same launch-1 WCAG pass found dark-mode text3
    // failing too (3.05-3.32:1 against canvas/surface). 8C8579 clears 4.5:1
    // against both (4.95/4.55) with a small margin. text2 already passed
    // (6.16/5.67), unchanged.
    text3: Color(0xFF8C8579),
    accent: Color(0xFFE87A5C),
    accentText: Color(0xFFE87A5C),
    accentInk: Color(0xFF171614),
    freezing: HeatSpec(
      base: Color(0xFF7FA0BE),
      tintBg: Color(0xFF20272E),
      text: Color(0xFFA9C0D6),
    ),
    cold: HeatSpec(
      base: Color(0xFF8FB0CC),
      tintBg: Color(0xFF222A32),
      text: Color(0xFFB7CCE0),
    ),
    warm: HeatSpec(
      base: Color(0xFFC9A05E),
      tintBg: Color(0xFF2A2620),
      text: Color(0xFFDCC08A),
    ),
    hot: HeatSpec(
      base: Color(0xFFD98D5C),
      tintBg: Color(0xFF2D241D),
      text: Color(0xFFE8A87A),
    ),
    scorching: HeatSpec(
      base: Color(0xFFDE7258),
      tintBg: Color(0xFF2E201C),
      text: Color(0xFFEF8D75),
    ),
    win: HeatSpec(
      base: Color(0xFFE87A5C),
      tintBg: Color(0xFF2E211D),
      text: Color(0xFFEF9070),
    ),
  );
}

/// Builds the app's [ThemeData] for a given [brightness] from
/// [WarmerTokens], with a manually-specified [ColorScheme] (no
/// `colorSchemeSeed`) so every colour traces back to a named token.
ThemeData buildWarmerTheme(Brightness brightness) {
  final tokens = brightness == Brightness.light
      ? WarmerTokens.light
      : WarmerTokens.dark;
  final isLight = brightness == Brightness.light;

  final colorScheme = ColorScheme(
    brightness: brightness,
    primary: tokens.accent,
    onPrimary: tokens.accentInk,
    primaryContainer: tokens.win.tintBg,
    onPrimaryContainer:
        isLight ? const Color(0xFFB04429) : const Color(0xFFEF9070),
    secondary: tokens.text2,
    onSecondary: tokens.canvas,
    secondaryContainer:
        isLight ? const Color(0xFFF3F0EA) : const Color(0xFF262421),
    onSecondaryContainer: tokens.text1,
    tertiary: tokens.text3,
    onTertiary: tokens.canvas,
    surface: tokens.surface,
    onSurface: tokens.text1,
    surfaceContainerHighest:
        isLight ? const Color(0xFFF3F0EA) : const Color(0xFF262421),
    onSurfaceVariant: tokens.text2,
    outline: tokens.text3,
    outlineVariant: tokens.hairline,
    error: isLight ? const Color(0xFFB9472F) : const Color(0xFFEF8D75),
    onError: isLight ? const Color(0xFFFFFFFF) : const Color(0xFF171614),
    errorContainer: tokens.scorching.tintBg,
    onErrorContainer: tokens.scorching.text,
    inverseSurface: tokens.text1,
    onInverseSurface: tokens.canvas,
    shadow: Colors.black,
    scrim: Colors.black,
  );

  final baseTextTheme = brightness == Brightness.light
      ? Typography.material2021().black
      : Typography.material2021().white;
  final textTheme = baseTextTheme
      .apply(bodyColor: tokens.text1, displayColor: tokens.text1)
      .copyWith(
        labelSmall: baseTextTheme.labelSmall?.copyWith(color: tokens.text2),
      );

  return ThemeData(
    useMaterial3: true,
    brightness: brightness,
    colorScheme: colorScheme,
    scaffoldBackgroundColor: tokens.canvas,
    extensions: [tokens],
    textTheme: textTheme,
    appBarTheme: AppBarThemeData(
      backgroundColor: tokens.canvas,
      foregroundColor: tokens.text1,
      elevation: 0,
      scrolledUnderElevation: 0,
      surfaceTintColor: Colors.transparent,
      centerTitle: false,
    ),
    cardTheme: CardThemeData(
      color: tokens.surface,
      elevation: 0,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: BorderSide(color: tokens.hairline, width: 1),
      ),
    ),
    dividerTheme: DividerThemeData(
      color: tokens.hairline,
      thickness: 0.5,
      space: 12,
    ),
    inputDecorationTheme: InputDecorationThemeData(
      filled: true,
      fillColor: tokens.surface,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide(color: tokens.hairline, width: 1),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide(color: tokens.hairline, width: 1),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide(color: tokens.accent, width: 1.5),
      ),
      errorBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide(color: colorScheme.error, width: 1),
      ),
      focusedErrorBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide(color: colorScheme.error, width: 1.5),
      ),
      hintStyle: TextStyle(color: tokens.text3),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: ButtonStyle(
        backgroundColor: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.disabled)) return tokens.hairline;
          return tokens.accent;
        }),
        foregroundColor: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.disabled)) return tokens.text3;
          return tokens.accentInk;
        }),
        shape: WidgetStatePropertyAll(
          RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        ),
        textStyle: const WidgetStatePropertyAll(
          TextStyle(fontWeight: FontWeight.w600),
        ),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: ButtonStyle(
        foregroundColor: WidgetStatePropertyAll(tokens.accentText),
        side: WidgetStatePropertyAll(BorderSide(color: tokens.hairline)),
        shape: WidgetStatePropertyAll(
          RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        ),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: ButtonStyle(
        foregroundColor: WidgetStatePropertyAll(tokens.accentText),
      ),
    ),
    floatingActionButtonTheme: FloatingActionButtonThemeData(
      backgroundColor: tokens.accent,
      foregroundColor: tokens.accentInk,
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: tokens.surface,
      elevation: 0,
      surfaceTintColor: Colors.transparent,
      indicatorColor: tokens.win.tintBg,
      iconTheme: WidgetStateProperty.resolveWith((states) {
        return IconThemeData(
          color: states.contains(WidgetState.selected)
              ? tokens.accentText
              : tokens.text2,
        );
      }),
      labelTextStyle: WidgetStateProperty.resolveWith((states) {
        return states.contains(WidgetState.selected)
            ? TextStyle(color: tokens.text1, fontWeight: FontWeight.w600, fontSize: 12)
            : TextStyle(color: tokens.text2, fontSize: 12);
      }),
    ),
    snackBarTheme: SnackBarThemeData(
      backgroundColor: tokens.text1,
      contentTextStyle: TextStyle(color: tokens.canvas, fontSize: 14),
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: tokens.surface,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
    ),
    bottomSheetTheme: BottomSheetThemeData(
      backgroundColor: tokens.surface,
      surfaceTintColor: Colors.transparent,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
    ),
    chipTheme: ChipThemeData(
      backgroundColor: tokens.canvas,
      side: BorderSide(color: tokens.hairline),
      labelStyle: TextStyle(color: tokens.text2),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
    ),
    progressIndicatorTheme: ProgressIndicatorThemeData(color: tokens.accent),
    segmentedButtonTheme: SegmentedButtonThemeData(
      style: ButtonStyle(
        backgroundColor: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.selected)) return tokens.win.tintBg;
          return null;
        }),
        foregroundColor: WidgetStateProperty.resolveWith((states) {
          return states.contains(WidgetState.selected)
              ? tokens.text1
              : tokens.text2;
        }),
      ),
    ),
    switchTheme: SwitchThemeData(
      thumbColor: WidgetStateProperty.resolveWith((states) {
        return states.contains(WidgetState.selected) ? tokens.accent : tokens.surface;
      }),
      trackColor: WidgetStateProperty.resolveWith((states) {
        return states.contains(WidgetState.selected)
            ? tokens.win.tintBg
            : tokens.hairline;
      }),
    ),
    listTileTheme: ListTileThemeData(
      iconColor: tokens.text2,
      textColor: tokens.text1,
    ),
  );
}

/// Visual-only re-accent for themed-pack play: swaps [ThemeData.colorScheme]
/// primary/container colours (plus the widgets that hard-derive from them)
/// for [accent], while everything else — surfaces, text, hairlines — stays on
/// the calm-minimal [base] theme.
///
/// [accentDark] is currently unused by the re-derivation below (accent alone
/// determines ink via [_relativeLuminance]) but is accepted for API
/// forward-compatibility with callers that track a light/dark accent pair.
ThemeData buildPackTheme(ThemeData base, Color accent, Color accentDark) {
  final ink = _relativeLuminance(accent) < 0.25
      ? Colors.white
      : const Color(0xFF26231F);
  final primaryContainer =
      Color.alphaBlend(accent.withValues(alpha: 0.14), base.colorScheme.surface);

  return base.copyWith(
    colorScheme: base.colorScheme.copyWith(
      primary: accent,
      onPrimary: ink,
      primaryContainer: primaryContainer,
      onPrimaryContainer: base.colorScheme.onSurface,
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: ButtonStyle(
        backgroundColor: WidgetStatePropertyAll(accent),
        foregroundColor: WidgetStatePropertyAll(ink),
        shape: WidgetStatePropertyAll(
          RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        ),
        textStyle: const WidgetStatePropertyAll(
          TextStyle(fontWeight: FontWeight.w600),
        ),
      ),
    ),
    floatingActionButtonTheme: FloatingActionButtonThemeData(
      backgroundColor: accent,
      foregroundColor: ink,
    ),
    progressIndicatorTheme: ProgressIndicatorThemeData(color: accent),
    navigationBarTheme: base.navigationBarTheme.copyWith(
      indicatorColor: accent.withValues(alpha: 0.14),
    ),
  );
}

/// Relative luminance of [color], per WCAG — thin wrapper around
/// [Color.computeLuminance] kept as a named helper for readability at call
/// sites.
double _relativeLuminance(Color color) => color.computeLuminance();

/// Uppercase micro-label style ("TODAY'S CLUE") derived from [t].
TextStyle microLabel(WarmerTokens t) {
  return TextStyle(
    fontSize: 11,
    fontWeight: FontWeight.w600,
    letterSpacing: 1.2,
    color: t.text3,
  );
}
