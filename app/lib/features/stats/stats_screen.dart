import 'package:flutter/material.dart';
import 'package:mindmeld/core/design_tokens.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/persistence.dart';

/// Displays player statistics: streak, max streak, played, win %, guess
/// distribution, and streak-freeze holdings (earned — see
/// [AppPersistence.recordWin]'s milestone grant and
/// [AppPersistence.rescueStreakOrReset]'s consumption — never purchased).
class StatsScreen extends StatefulWidget {
  const StatsScreen({
    super.key,
    required this.lang,
    this.active = true,
  });

  final String lang;

  /// Whether this tab is the currently-selected destination in the app
  /// shell's [IndexedStack].
  ///
  /// [StatsScreen] is mounted eagerly at boot (all `IndexedStack` children
  /// build regardless of which index is selected) and only ever loads once
  /// in [initState] — so within a single session, switching to this tab
  /// after stats change elsewhere (e.g. winning the daily puzzle) rendered
  /// boot-time numbers forever. [_StatsScreenState.didUpdateWidget] reloads
  /// whenever [active] transitions false→true. Defaults to `true` so direct
  /// usages (tests, any future non-tabbed embedding) reload on every build
  /// as before.
  final bool active;

  @override
  State<StatsScreen> createState() => _StatsScreenState();
}

class _StatsScreenState extends State<StatsScreen> {
  PlayerStats? _stats;
  bool _loading = true;

  /// True for one load only, right after a streak freeze was just spent to
  /// cover a missed day — drives the one-time "Streak freeze used!" banner.
  bool _justRescued = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(StatsScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    // Reload on false→true activation (tab becomes visible again after
    // stats may have changed elsewhere in this session — e.g. a daily win)
    // and on a lang switch (stats are per-lang; the old lang's numbers are
    // stale for the new lang). Not reloading on every build here is
    // deliberate: this screen is always mounted (see [StatsScreen.active]
    // doc), so an unconditional reload on every rebuild would re-fire the
    // passive-streak-rescue write far more often than the data can actually
    // change.
    final becameActive = widget.active && !oldWidget.active;
    final langChanged = widget.lang != oldWidget.lang;
    if (becameActive || langChanged) {
      _load();
    }
  }

  Future<void> _load() async {
    final today = DateTime.now();
    var s = await AppPersistence.instance.loadStats(widget.lang);
    var justRescued = false;

    // Passive streak check: fix a stale streak display when the player
    // missed day(s), spending an earned streak freeze first if one covers
    // exactly the gap (see AppPersistence.rescueStreakOrReset).
    if (s.currentStreak > 0) {
      final result = await AppPersistence.instance.rescueStreakOrReset(
        lang: widget.lang,
        today: today,
      );
      s = result.stats;
      justRescued = result.rescued;
    }

    if (mounted) {
      setState(() {
        _stats = s;
        _justRescued = justRescued;
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }

    final stats = _stats ?? PlayerStats.empty;
    final winPctStr = '${(stats.winPct * 100).toStringAsFixed(0)}%';
    final tokens = Theme.of(context).extension<WarmerTokens>() ?? WarmerTokens.light;

    return Scaffold(
      appBar: AppBar(title: const Text('Statistics')),
      body: Padding(
        padding: const EdgeInsets.all(WarmerSpacing.xl),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (_justRescued) ...[
              Container(
                padding: const EdgeInsets.all(WarmerSpacing.md),
                decoration: BoxDecoration(
                  color: tokens.win.tintBg,
                  // WarmerRadius.sm, not .xs: matches every other message-
                  // banner in the app (win_screen.dart's win/par-rival/
                  // best-guess banners) — .xs is reserved for small chips.
                  borderRadius: BorderRadius.circular(WarmerRadius.sm),
                ),
                child: Row(
                  children: [
                    Icon(Icons.ac_unit, color: tokens.win.text, size: 20),
                    const SizedBox(width: WarmerSpacing.sm),
                    Expanded(
                      child: Text(
                        'Streak freeze used — a missed day was covered, your '
                        'streak is safe!',
                        style: TextStyle(color: tokens.win.text),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: WarmerSpacing.xl),
            ],

            // Top numbers row
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceEvenly,
              children: [
                _StatBox(label: 'Played', value: '${stats.played}'),
                _StatBox(label: 'Win %', value: winPctStr),
                _StatBox(label: 'Streak', value: '${stats.currentStreak}'),
                _StatBox(label: 'Best', value: '${stats.maxStreak}'),
              ],
            ),

            const SizedBox(height: WarmerSpacing.xxl),

            Text(
              'Guess Distribution',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: WarmerSpacing.md),

            if (stats.guessDistribution.isEmpty)
              Text(
                'No wins yet — play a puzzle!',
                style: TextStyle(
                  color: (Theme.of(context).extension<WarmerTokens>() ?? WarmerTokens.light).text2,
                ),
              )
            else
              ..._buildDistribution(context, stats),

            // Streak-freeze holdings — earned every streakFreezeMilestoneDays-day
            // streak, capped at maxStreakFreezes; see AppPersistence.recordWin.
            if (stats.streakFreezes > 0) ...[
              const SizedBox(height: WarmerSpacing.xl),
              Row(
                children: [
                  Icon(Icons.ac_unit, color: tokens.text2, size: 18),
                  const SizedBox(width: WarmerSpacing.sm),
                  Text(
                    'Streak freezes: ${stats.streakFreezes}',
                    style: Theme.of(context).textTheme.bodyMedium,
                  ),
                ],
              ),
              Padding(
                // Left-indent aligns the caption under the label text above,
                // past the 18px icon + WarmerSpacing.sm gap it sits beside —
                // computed from those same values, not a bare magic number.
                padding: const EdgeInsets.only(
                  top: WarmerSpacing.xs,
                  left: 18 + WarmerSpacing.sm,
                ),
                child: Text(
                  'Earned every $streakFreezeMilestoneDays-day streak — covers one '
                  'missed day automatically.',
                  style: Theme.of(context)
                      .textTheme
                      .bodySmall
                      ?.copyWith(color: tokens.text2),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  List<Widget> _buildDistribution(BuildContext context, PlayerStats stats) {
    final tokens = Theme.of(context).extension<WarmerTokens>() ?? WarmerTokens.light;
    final maxCount = stats.guessDistribution.values.fold(0, (a, b) => a > b ? a : b);
    final sortedKeys = stats.guessDistribution.keys.toList()
      ..sort((a, b) => int.parse(a).compareTo(int.parse(b)));

    return sortedKeys.map((key) {
      final count = stats.guessDistribution[key]!;
      final fraction = maxCount == 0 ? 0.0 : count / maxCount;

      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(
          children: [
            SizedBox(
              width: 36,
              child: Text(key, textAlign: TextAlign.right, style: TextStyle(color: tokens.text2)),
            ),
            const SizedBox(width: WarmerSpacing.sm),
            Expanded(
              child: FractionallySizedBox(
                alignment: Alignment.centerLeft,
                widthFactor: fraction.clamp(0.05, 1.0),
                child: Container(
                  height: 24,
                  alignment: Alignment.centerRight,
                  padding: const EdgeInsets.symmetric(horizontal: 6),
                  decoration: BoxDecoration(
                    color: Theme.of(context).colorScheme.primary,
                    borderRadius: BorderRadius.circular(WarmerRadius.xs),
                  ),
                  child: Text(
                    '$count',
                    style: TextStyle(
                      color: tokens.accentInk,
                      fontSize: 12,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              ),
            ),
          ],
        ),
      );
    }).toList();
  }
}

class _StatBox extends StatelessWidget {
  const _StatBox({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final tokens = Theme.of(context).extension<WarmerTokens>() ?? WarmerTokens.light;
    return Container(
      padding:
          const EdgeInsets.symmetric(vertical: WarmerSpacing.md, horizontal: WarmerSpacing.sm),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: tokens.hairline),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            value,
            style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                  fontWeight: FontWeight.w700,
                  color: tokens.text1,
                ),
          ),
          Text(label, style: microLabel(tokens)),
        ],
      ),
    );
  }
}
