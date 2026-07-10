import 'package:flutter/material.dart';

/// Entry banner into [PackSelectorScreen] — deliberately styled with the
/// packs motif (gold/crimson gradient, film-strip icon) rather than the
/// app's own heat-rings identity, so it reads as a distinct destination
/// (a themed content pack, e.g. Bollywood) rather than another app-chrome
/// element.
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

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: compact
          ? const EdgeInsets.fromLTRB(16, 8, 16, 0)
          : const EdgeInsets.fromLTRB(16, 12, 16, 4),
      child: Card(
        clipBehavior: Clip.antiAlias,
        margin: EdgeInsets.zero,
        child: InkWell(
          onTap: onTap,
          child: Ink(
            padding: EdgeInsets.all(compact ? 12 : 16),
            decoration: const BoxDecoration(
              gradient: LinearGradient(
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
                colors: [Color(0xFFE8B23A), Color(0xFF8E1A2B)],
              ),
            ),
            child: Row(
              children: [
                Icon(Icons.auto_awesome, color: Colors.white, size: compact ? 24 : 32),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Themed Packs',
                        style: TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.bold,
                          fontSize: compact ? 14 : 16,
                        ),
                      ),
                      if (!compact) ...const [
                        SizedBox(height: 2),
                        Text(
                          'Bollywood, Cricket, Food & more',
                          style: TextStyle(color: Colors.white70, fontSize: 12),
                        ),
                      ] else
                        const Text(
                          'Bollywood & Cricket live — more packs coming soon',
                          style: TextStyle(color: Colors.white70, fontSize: 11),
                        ),
                    ],
                  ),
                ),
                const Icon(Icons.chevron_right, color: Colors.white),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
