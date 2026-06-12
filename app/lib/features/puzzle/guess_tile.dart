import 'package:flutter/material.dart';
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
    final color = bandColor(band);

    return Container(
      key: HintTileKey(hint.word),
      margin: const EdgeInsets.symmetric(vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        border: Border.all(color: color, width: 1.5),
        borderRadius: BorderRadius.circular(8),
      ),
      child: ListTile(
        dense: true,
        leading: CircleAvatar(
          backgroundColor: color.withValues(alpha: 0.20),
          radius: 16,
          child: Icon(Icons.lightbulb, color: color, size: 18),
        ),
        title: Text(
          hint.word,
          style: const TextStyle(fontWeight: FontWeight.w600),
        ),
        subtitle: Text(
          'rank #${hint.rank}',
          style: Theme.of(context)
              .textTheme
              .labelSmall
              ?.copyWith(color: color),
        ),
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            // "Hint" chip badge distinguishes pinned hints from guesses.
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              decoration: BoxDecoration(
                color: color,
                borderRadius: BorderRadius.circular(12),
              ),
              child: const Text(
                'Hint',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 0.5,
                ),
              ),
            ),
            const SizedBox(width: 8),
            Text(
              band.label,
              style: Theme.of(context).textTheme.labelSmall,
            ),
          ],
        ),
      ),
    );
  }
}

/// Color mapping for temperature bands.
Color bandColor(TemperatureBand band) {
  switch (band) {
    case TemperatureBand.win:
      return const Color(0xFF6200EE); // Purple
    case TemperatureBand.scorching:
      return const Color(0xFFD32F2F); // Deep red
    case TemperatureBand.hot:
      return const Color(0xFFF57C00); // Orange
    case TemperatureBand.warm:
      return const Color(0xFFFBC02D); // Yellow
    case TemperatureBand.cold:
      return const Color(0xFF388E3C); // Green
    case TemperatureBand.freezing:
      return const Color(0xFF1976D2); // Blue
  }
}

/// A single row in the guess history list.
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
    final color = bandColor(guess.band);
    final simPct = ((guess.similarity + 1) / 2 * 100).toStringAsFixed(1);

    return Container(
      margin: const EdgeInsets.symmetric(vertical: 3),
      decoration: BoxDecoration(
        color: isHighlighted
            ? color.withValues(alpha: 0.18)
            : Theme.of(context).colorScheme.surfaceContainerHighest,
        border: Border.all(
          color: isHighlighted ? color : Colors.transparent,
          width: isHighlighted ? 2 : 0,
        ),
        borderRadius: BorderRadius.circular(8),
      ),
      child: ListTile(
        dense: true,
        leading: CircleAvatar(
          backgroundColor: color,
          radius: 16,
          child: Text(
            '#${guess.rank}',
            style: const TextStyle(
              color: Colors.white,
              fontSize: 10,
              fontWeight: FontWeight.bold,
            ),
          ),
        ),
        title: Text(
          guess.word,
          style: TextStyle(
            fontWeight:
                isHighlighted ? FontWeight.bold : FontWeight.normal,
          ),
        ),
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              decoration: BoxDecoration(
                color: color,
                borderRadius: BorderRadius.circular(12),
              ),
              child: Text(
                guess.band.label,
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
            const SizedBox(width: 8),
            Text(
              '$simPct%',
              style: Theme.of(context).textTheme.labelSmall,
            ),
          ],
        ),
      ),
    );
  }
}
