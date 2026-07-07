import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:mindmeld/features/packs/pack_selector_screen.dart';
import 'package:mindmeld/features/puzzle/puzzle_screen.dart';

/// Practice screen — lists past puzzles for replay.
///
/// Uses the same [PuzzleScreen] with [isPractice] = true so that practice
/// plays do not affect the player's daily stats or streak.
class ArchiveScreen extends StatelessWidget {
  const ArchiveScreen({super.key, required this.lang});

  final String lang;

  static const _startDate = '2026-06-12';

  List<String> _availableDates() {
    final start = DateTime.parse(_startDate);
    final now = DateTime.now();
    final yesterday = DateTime(now.year, now.month, now.day)
        .subtract(const Duration(days: 1));

    if (yesterday.isBefore(start)) return [];

    final dates = <String>[];
    var current = yesterday;
    while (!current.isBefore(start)) {
      dates.add(DateFormat('yyyy-MM-dd').format(current));
      current = current.subtract(const Duration(days: 1));
    }
    return dates;
  }

  void _playDate(BuildContext context, String date) {
    Navigator.push(
      context,
      MaterialPageRoute<void>(
        builder: (_) => PuzzleScreen(
          lang: lang,
          date: date,
          isPractice: true,
          onWin: () => Navigator.pop(context),
          onLoss: () => Navigator.pop(context),
        ),
      ),
    );
  }

  void _openPacks(BuildContext context) {
    Navigator.push(
      context,
      MaterialPageRoute<void>(builder: (_) => PackSelectorScreen(lang: lang)),
    );
  }

  @override
  Widget build(BuildContext context) {
    final dates = _availableDates();
    return Scaffold(
      appBar: AppBar(title: const Text('Practice')),
      body: Column(
        children: [
          _ThemedPacksEntryCard(onTap: () => _openPacks(context)),
          Expanded(
            child: dates.isEmpty
                ? const Center(
                    child: Text(
                        'No past puzzles available yet.\nCheck back tomorrow!',
                        textAlign: TextAlign.center),
                  )
                : ListView.builder(
                    itemCount: dates.length,
                    itemBuilder: (ctx, i) {
                      final date = dates[i];
                      final dt = DateTime.parse(date);
                      final formatted = DateFormat('EEEE, MMM d').format(dt);
                      final puzzleNum =
                          dt.difference(DateTime.parse(_startDate)).inDays + 1;
                      return ListTile(
                        leading: CircleAvatar(
                          child: Text('#$puzzleNum',
                              style: const TextStyle(fontSize: 12)),
                        ),
                        title: Text('Puzzle #$puzzleNum'),
                        subtitle: Text(formatted),
                        trailing: const Icon(Icons.chevron_right),
                        onTap: () => _playDate(ctx, date),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }
}

/// Entry card at the top of [ArchiveScreen] leading into [PackSelectorScreen].
///
/// Deliberately styled with the packs motif (gold/crimson gradient, film-strip
/// icon) rather than the app's core purple, so it reads as a distinct
/// destination rather than another practice-puzzle row.
class _ThemedPacksEntryCard extends StatelessWidget {
  const _ThemedPacksEntryCard({required this.onTap});

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
      child: Card(
        clipBehavior: Clip.antiAlias,
        margin: EdgeInsets.zero,
        child: InkWell(
          onTap: onTap,
          child: Ink(
            padding: const EdgeInsets.all(16),
            decoration: const BoxDecoration(
              gradient: LinearGradient(
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
                colors: [Color(0xFFE8B23A), Color(0xFF8E1A2B)],
              ),
            ),
            child: Row(
              children: [
                const Icon(Icons.auto_awesome, color: Colors.white, size: 32),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: const [
                      Text(
                        'Themed Packs',
                        style: TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.bold,
                          fontSize: 16,
                        ),
                      ),
                      SizedBox(height: 2),
                      Text(
                        'Bollywood, Cricket, Food & more',
                        style: TextStyle(color: Colors.white70, fontSize: 12),
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
