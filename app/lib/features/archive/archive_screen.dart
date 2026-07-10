import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:mindmeld/features/packs/pack_selector_screen.dart';
import 'package:mindmeld/features/packs/packs_entry_banner.dart';
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
          PacksEntryBanner(onTap: () => _openPacks(context)),
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
