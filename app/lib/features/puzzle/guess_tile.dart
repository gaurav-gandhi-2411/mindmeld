import 'package:flutter/material.dart';
import 'package:mindmeld/core/design_tokens.dart';
import 'package:mindmeld/core/models.dart';

// ---------------------------------------------------------------------------
// Hint tile
// ---------------------------------------------------------------------------

/// Key type used to locate [HintTile] widgets in tests without depending on
/// string keys that could collide with guess tiles.
///
/// Usage: `find.byKey(HintTileKey('wave'))` in widget tests.
class HintTileKey extends ValueKey<String> {
  const HintTileKey(super.value);
}

/// Resolves the [HeatSpec] for [band] from the current theme's
/// [WarmerTokens] extension, falling back to [WarmerTokens.light] for bare
/// test harnesses that don't build a themed [MaterialApp].
HeatSpec heatForBand(BuildContext context, TemperatureBand band) {
  final tokens = Theme.of(context).extension<WarmerTokens>() ?? WarmerTokens.light;
  return tokens.heatFor(band);
}

/// A pinned tile displayed above the guess list for a revealed hint.
///
/// Visual identity: lightbulb icon, "Hint" chip badge, temperature-band colour
/// derived from the hint's rank (same palette as [GuessTile]).
class HintTile extends StatelessWidget {
  const HintTile({
    required this.hint,
    required this.vocabSize,
    super.key,
  });

  final RevealedHint hint;

  /// Total vocabulary size — used by [bandForRank] for threshold computation.
  final int vocabSize;

  @override
  Widget build(BuildContext context) {
    final band = bandForRank(hint.rank, vocabSize);
    final heat = heatForBand(context, band);
    final tokens = Theme.of(context).extension<WarmerTokens>() ?? WarmerTokens.light;

    return Container(
      key: HintTileKey(hint.word),
      margin: const EdgeInsets.symmetric(vertical: 3),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: heat.tintBg,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: heat.base.withValues(alpha: 0.25), width: 0.5),
      ),
      child: Row(
        children: [
          Icon(Icons.lightbulb_outline, size: 18, color: heat.text),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              hint.word,
              style: const TextStyle(fontWeight: FontWeight.w500),
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
            decoration: BoxDecoration(
              color: tokens.surface,
              borderRadius: BorderRadius.circular(6),
              border: Border.all(color: tokens.hairline, width: 1),
            ),
            child: Text(
              'Hint',
              style: TextStyle(
                fontSize: 10,
                fontWeight: FontWeight.w600,
                letterSpacing: 0.8,
                color: tokens.text2,
              ),
            ),
          ),
          const Spacer(),
          Text(
            '#${hint.rank}',
            style: TextStyle(fontWeight: FontWeight.w600, color: heat.text),
          ),
          const SizedBox(width: 8),
          Text(
            band.label,
            style: Theme.of(context)
                .textTheme
                .labelSmall
                ?.copyWith(color: heat.text),
          ),
        ],
      ),
    );
  }
}

/// A single row in the guess history list.
///
/// Visual identity: word on the left; rank + temperature pill on the right;
/// row tinted by the guess's temperature band (soft tint background + the
/// band's deepest text shade — never black-on-color, never a full-saturation
/// fill).
class GuessTile extends StatelessWidget {
  const GuessTile({
    super.key,
    required this.guess,
    required this.vocabSize,
    this.isHighlighted = false,
  });

  final Guess guess;
  final int vocabSize;
  final bool isHighlighted;

  @override
  Widget build(BuildContext context) {
    final heat = heatForBand(context, guess.band);
    final tokens = Theme.of(context).extension<WarmerTokens>() ?? WarmerTokens.light;
    final isWin = guess.band == TemperatureBand.win;
    final simPct = ((guess.similarity + 1) / 2 * 100).toStringAsFixed(1);

    return Container(
      margin: const EdgeInsets.symmetric(vertical: 3),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: heat.tintBg,
        borderRadius: BorderRadius.circular(12),
        border: isHighlighted
            ? Border.all(color: heat.base, width: 1.5)
            : Border.all(color: heat.base.withValues(alpha: 0.25), width: 0.5),
      ),
      child: Row(
        children: [
          Text(
            guess.word,
            style: TextStyle(
              fontWeight: isHighlighted ? FontWeight.w700 : FontWeight.w500,
              color: tokens.text1,
            ),
          ),
          const Spacer(),
          Text(
            '#${guess.rank}',
            style: TextStyle(
              fontWeight: FontWeight.w600,
              color: heat.text,
              fontFeatures: const [FontFeature.tabularFigures()],
            ),
          ),
          const SizedBox(width: 10),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
            decoration: BoxDecoration(
              color: isWin ? tokens.accent : heat.base.withValues(alpha: 0.16),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Text(
              guess.band.label,
              style: TextStyle(
                color: isWin ? tokens.accentInk : heat.text,
                fontSize: 11,
                fontWeight: FontWeight.w600,
                letterSpacing: 0.3,
              ),
            ),
          ),
          const SizedBox(width: 8),
          Text(
            '$simPct%',
            style: Theme.of(context)
                .textTheme
                .labelSmall
                ?.copyWith(color: tokens.text3),
          ),
        ],
      ),
    );
  }
}
