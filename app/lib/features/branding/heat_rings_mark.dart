import 'package:flutter/material.dart';
import 'package:mindmeld/core/design_tokens.dart';

/// Locked heat-rings identity palette — must match scripts/make_app_icon.py
/// and warmer_heat_rings_identity.svg exactly. See spec-aesthetic-pass.md.
class WarmerColors {
  const WarmerColors._();

  static const Color cold = Color(0xFF6B89A8);
  static const Color cool = Color(0xFF7E9BB5);
  static const Color warm = Color(0xFFD9AE6B);
  static const Color hot = Color(0xFFD65F49);
  static const Color wordmarkAccent = Color(0xFFDD6B4D);
  static const Color ground = Color(0xFF171614);
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
