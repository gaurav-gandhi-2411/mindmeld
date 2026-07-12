import 'package:flutter/material.dart';
import 'package:mindmeld/core/design_tokens.dart';

/// Locked heat-rings identity palette — must match scripts/make_app_icon.py
/// and warmer_heat_rings_identity.svg exactly. See spec-aesthetic-pass.md.
///
/// Sourced from [WarmerTokens.light]/[WarmerTokens.dark] rather than
/// re-declared literals so the identity palette can never drift from the
/// design tokens it happens to coincide with. Deliberately pinned to fixed
/// light/dark tokens (not the theme's current brightness) — the mark must
/// read identically regardless of app theme.
class WarmerColors {
  const WarmerColors._();

  static final Color cold = WarmerTokens.light.freezing.base;
  static final Color cool = WarmerTokens.light.cold.base;
  static final Color warm = WarmerTokens.light.warm.base;
  static final Color hot = WarmerTokens.light.scorching.base;
  static final Color wordmarkAccent = WarmerTokens.light.accent;
  static final Color ground = WarmerTokens.dark.canvas;
}

/// The heat-rings mark: concentric rings (cold blue outer -> cyan -> amber)
/// closing to a hot-red centre. It IS the mechanic — closing in, getting
/// warmer. Pure vector (CustomPaint) so it stays crisp at any size, unlike a
/// rasterised app-icon asset.
class HeatRingsMark extends StatelessWidget {
  const HeatRingsMark({super.key, this.size = 32});

  final double size;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: size,
      height: size,
      child: CustomPaint(painter: _HeatRingsPainter()),
    );
  }
}

class _HeatRingsPainter extends CustomPainter {
  const _HeatRingsPainter();

  // Same ratios as scripts/make_app_icon.py's _draw_rings — keep in sync so
  // the in-app mark reads identically to the app icon/favicon/OG card.
  static const double _rOuterFrac = 0.30;
  static const double _rMidFrac = 0.22;
  static const double _rInnerFrac = 0.14;
  static const double _rDotFrac = 0.065;
  static const double _strokeFrac = 0.05;

  @override
  void paint(Canvas canvas, Size size) {
    final s = size.shortestSide;
    final center = Offset(size.width / 2, size.height / 2);
    final strokeWidth = s * _strokeFrac;

    final stroke = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = strokeWidth;

    for (final (frac, color) in [
      (_rOuterFrac, WarmerColors.cold),
      (_rMidFrac, WarmerColors.cool),
      (_rInnerFrac, WarmerColors.warm),
    ]) {
      canvas.drawCircle(center, s * frac, stroke..color = color);
    }

    canvas.drawCircle(
      center,
      s * _rDotFrac,
      Paint()..color = WarmerColors.hot,
    );
  }

  @override
  bool shouldRepaint(covariant _HeatRingsPainter oldDelegate) => false;
}

/// Lockup: heat-rings mark + "warmer" wordmark ("warm" in the ambient text
/// color, "er" in the wordmark-accent orange), matching
/// warmer_heat_rings_identity.svg's wordmark composition.
class WarmerWordmark extends StatelessWidget {
  const WarmerWordmark({super.key, this.markSize = 24, this.fontSize = 20});

  final double markSize;
  final double fontSize;

  @override
  Widget build(BuildContext context) {
    final baseColor = DefaultTextStyle.of(context).style.color ??
        Theme.of(context).colorScheme.onSurface;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        HeatRingsMark(size: markSize),
        SizedBox(width: markSize * 0.3),
        RichText(
          text: TextSpan(
            style: TextStyle(
              fontSize: fontSize,
              fontWeight: FontWeight.bold,
              color: baseColor,
            ),
            children: [
              const TextSpan(text: 'warm'),
              TextSpan(
                text: 'er',
                style: TextStyle(
                  color: Theme.of(context).extension<WarmerTokens>()?.accent ??
                      WarmerColors.wordmarkAccent,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
