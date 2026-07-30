import 'package:flutter/material.dart';
import 'package:mindmeld/core/design_tokens.dart';

/// Entry banner into [PackSelectorScreen] — a themed card whose "identity
/// coin" carries the packs motif (gold/plum gradient, sparkle icon) so it
/// reads as a distinct destination (a themed content pack, e.g. Bollywood)
/// while the card itself stays on the app's calm-minimal surface treatment.
///
/// Two placements:
///   - [compact] = true: a slim strip pinned to the top of the primary daily
///     play surface ([PuzzleScreen]) so packs are impossible to miss on the
///     screen every player lands on first. This is the fix for the
///     "couldn't find Bollywood" bug — packs used to be reachable only from
///     a card buried under the Practice tab.
///   - [compact] = false: the larger card still shown atop the Practice tab
///     ([ArchiveScreen]) as a secondary, redundant entry point.
class PacksEntryBanner extends StatelessWidget {
  const PacksEntryBanner({super.key, required this.onTap, this.compact = false});

  final VoidCallback onTap;
  final bool compact;

  /// Bollywood-pack motif gradient for the banner's identity coin — kept
  /// distinct from any single pack's live accent so the banner reads as the
  /// "packs" destination itself, not one specific pack.
  static const _coinGradient = [Color(0xFFC0913F), Color(0xFF7E3B46)];

  @override
  Widget build(BuildContext context) {
    final tokens = Theme.of(context).extension<WarmerTokens>() ?? WarmerTokens.light;
    final coinSize = compact ? 32.0 : 40.0;
    final coinRadius = compact ? 10.0 : 12.0;

    return Padding(
      padding: compact
          ? const EdgeInsets.fromLTRB(
              WarmerSpacing.lg, WarmerSpacing.sm, WarmerSpacing.lg, 0)
          : const EdgeInsets.fromLTRB(
              WarmerSpacing.lg, WarmerSpacing.md, WarmerSpacing.lg, WarmerSpacing.xs),
      child: Card(
        clipBehavior: Clip.antiAlias,
        margin: EdgeInsets.zero,
        child: InkWell(
          onTap: onTap,
          child: Padding(
            padding: EdgeInsets.all(compact ? WarmerSpacing.md : WarmerSpacing.lg),
            child: Row(
              children: [
                Container(
                  width: coinSize,
                  height: coinSize,
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(coinRadius),
                    gradient: const LinearGradient(
                      begin: Alignment.topLeft,
                      end: Alignment.bottomRight,
                      colors: _coinGradient,
                    ),
                  ),
                  child: Icon(Icons.auto_awesome,
                      color: Colors.white, size: compact ? 16 : 20),
                ),
                const SizedBox(width: WarmerSpacing.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Themed Packs',
                        style: TextStyle(
                          color: tokens.text1,
                          fontWeight: FontWeight.w600,
                          fontSize: compact ? 14 : 16,
                        ),
                      ),
                      if (!compact) ...[
                        const SizedBox(height: 2),
                        Text(
                          'Bollywood, Cricket & Indian Kitchen',
                          style: TextStyle(color: tokens.text2, fontSize: 12),
                        ),
                      ] else
                        Text(
                          'Bollywood, Cricket & Indian Kitchen — all live',
                          style: TextStyle(color: tokens.text2, fontSize: 11),
                        ),
                    ],
                  ),
                ),
                Icon(Icons.chevron_right, color: tokens.text3),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
