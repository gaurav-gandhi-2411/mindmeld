import 'dart:async';

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:mindmeld/core/design_tokens.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/persistence.dart';
import 'package:mindmeld/features/packs/pack_selector_screen.dart';
import 'package:mindmeld/features/packs/packs_entry_banner.dart';
import 'package:mindmeld/features/puzzle/puzzle_screen.dart';

/// Archive screen — lists past daily puzzles for replay ("Practice" tab).
///
/// Uses the same [PuzzleScreen] with [isPractice] = true so that archive
/// plays do not affect the player's daily stats or streak — see
/// `AppPersistence`'s day-state/stats separation and
/// `flow_hardening_test.dart`'s "S24: practice mode does not affect daily
/// stats" for the proof this isolation holds.
class ArchiveScreen extends StatefulWidget {
  const ArchiveScreen({super.key, required this.lang});

  final String lang;

  static const startDate = '2026-06-12';

  @override
  State<ArchiveScreen> createState() => _ArchiveScreenState();
}

class _ArchiveScreenState extends State<ArchiveScreen> {
  Map<String, DayState?>? _solvedStates;

  @override
  void initState() {
    super.initState();
    unawaited(_loadSolvedStates());
  }

  @override
  void didUpdateWidget(ArchiveScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.lang != widget.lang) {
      _solvedStates = null;
      unawaited(_loadSolvedStates());
    }
  }

  List<String> _availableDates() {
    final start = DateTime.parse(ArchiveScreen.startDate);
    final now = DateTime.now();
    final yesterday = DateTime(
      now.year,
      now.month,
      now.day,
    ).subtract(const Duration(days: 1));

    if (yesterday.isBefore(start)) return [];

    final dates = <String>[];
    var current = yesterday;
    while (!current.isBefore(start)) {
      dates.add(DateFormat('yyyy-MM-dd').format(current));
      current = current.subtract(const Duration(days: 1));
    }
    return dates;
  }

  /// Loads each date's saved [DayState] (if any) so the list can show a
  /// solved/gave-up/unplayed indicator per puzzle. Archive plays are saved
  /// via the same `saveDayState` day-state store as the daily puzzle
  /// (keyed by date), just never routed through `recordWin`/`recordLoss` —
  /// see [PuzzleScreen.isPractice].
  Future<void> _loadSolvedStates() async {
    final dates = _availableDates();
    // Parallel, not sequential — the date range only grows over the game's
    // lifetime, and awaiting one query at a time would make this screen's
    // load time scale linearly with how long the game has been live.
    final loaded = await Future.wait(
      dates.map(
        (date) => AppPersistence.instance.loadDayState(date, widget.lang),
      ),
    );
    if (!mounted) return;
    setState(() => _solvedStates = Map.fromIterables(dates, loaded));
  }

  Future<void> _playDate(BuildContext context, String date) async {
    await Navigator.push(
      context,
      MaterialPageRoute<void>(
        builder: (_) => PuzzleScreen(
          lang: widget.lang,
          date: date,
          isPractice: true,
          onWin: () => Navigator.pop(context),
          onLoss: () => Navigator.pop(context),
        ),
      ),
    );
    // Refresh solved-state after returning, in case this date was just played.
    unawaited(_loadSolvedStates());
  }

  void _openPacks(BuildContext context) {
    Navigator.push(
      context,
      MaterialPageRoute<void>(
        builder: (_) => PackSelectorScreen(lang: widget.lang),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final dates = _availableDates();
    final colorScheme = Theme.of(context).colorScheme;
    final tokens =
        Theme.of(context).extension<WarmerTokens>() ?? WarmerTokens.light;
    return Scaffold(
      appBar: AppBar(title: const Text('Practice')),
      body: Column(
        children: [
          PacksEntryBanner(onTap: () => _openPacks(context)),
          Expanded(
            child: dates.isEmpty
                ? Center(
                    child: Padding(
                      padding: const EdgeInsets.all(WarmerSpacing.xl),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(
                            Icons.history_outlined,
                            size: 48,
                            color: tokens.text3,
                          ),
                          const SizedBox(height: WarmerSpacing.md),
                          Text(
                            'No past puzzles available yet.\nCheck back tomorrow!',
                            textAlign: TextAlign.center,
                            style: TextStyle(color: tokens.text2),
                          ),
                        ],
                      ),
                    ),
                  )
                : _solvedStates == null
                ? const Center(child: CircularProgressIndicator())
                : ListView.builder(
                    itemCount: dates.length,
                    itemBuilder: (ctx, i) {
                      final date = dates[i];
                      final dt = DateTime.parse(date);
                      final formatted = DateFormat('EEEE, MMM d').format(dt);
                      final puzzleNum =
                          dt
                              .difference(
                                DateTime.parse(ArchiveScreen.startDate),
                              )
                              .inDays +
                          1;
                      final state = _solvedStates?[date];
                      return ListTile(
                        leading: CircleAvatar(
                          backgroundColor: colorScheme.surfaceContainerHighest,
                          child: Text(
                            '#$puzzleNum',
                            style: TextStyle(fontSize: 12, color: tokens.text2),
                          ),
                        ),
                        title: Text('Puzzle #$puzzleNum'),
                        subtitle: Text(
                          state == null
                              ? formatted
                              : state.won
                              ? '$formatted · Solved in ${state.guesses.length}'
                              : state.gaveUp
                              ? '$formatted · Not solved'
                              : '$formatted · In progress',
                        ),
                        trailing: state != null && state.won
                            ? Icon(Icons.check_circle, color: tokens.win.text)
                            : state != null && state.gaveUp
                            ? Icon(
                                Icons.remove_circle_outline,
                                color: tokens.text3,
                              )
                            : const Icon(Icons.chevron_right),
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
