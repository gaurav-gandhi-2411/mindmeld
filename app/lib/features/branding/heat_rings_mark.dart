import 'package:flutter/material.dart';

/// Locked heat-rings identity palette — must match scripts/make_app_icon.py
/// and warmer_heat_rings_identity.svg exactly. See spec-warmer-rename.md.
class WarmerColors {
  const WarmerColors._();

  static const Color cold = Color(0xFF2563EB);
  static const Color cool = Color(0xFF06B6D4);
  static const Color warm = Color(0xFFF59E0B);
  static const Color hot = Color(0xFFEF4444);
  static const Color wordmarkAccent = Color(0xFFF97316);
  static const Color ground = Color(0xFF0F172A);
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
            children: const [
              TextSpan(text: 'warm'),
              TextSpan(
                text: 'er',
                style: TextStyle(color: WarmerColors.wordmarkAccent),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
