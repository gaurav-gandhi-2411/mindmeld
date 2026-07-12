import 'package:flutter/material.dart';
import 'package:mindmeld/core/design_tokens.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/persistence.dart';
import 'package:mindmeld/iap/entitlements.dart';
import 'package:mindmeld/iap/revenuecat_gateway.dart';

/// Displays player statistics: streak, max streak, played, win %, guess distribution,
/// and streak-freeze count (sourced from the IAP gateway entitlements).
class StatsScreen extends StatefulWidget {
  const StatsScreen({
    super.key,
    required this.lang,
    /// Optional gateway override for tests. When null [buildIapGateway] is used.
    this.iapGateway,
    this.active = true,
  });

  final String lang;

  /// Optional IAP gateway; package-accessible for test injection.
  final IapGateway? iapGateway;

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
  Entitlements _entitlements = Entitlements.empty;
  bool _loading = true;

  late final IapGateway _gateway;

  @override
  void initState() {
    super.initState();
    _gateway = widget.iapGateway ?? buildIapGateway();
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
    // passive-streak-reset write and the IAP gateway call far more often
    // than the data can actually change.
    final becameActive = widget.active && !oldWidget.active;
    final langChanged = widget.lang != oldWidget.lang;
    if (becameActive || langChanged) {
      _load();
    }
  }

  Future<void> _load() async {
    final today = DateTime.now();
    var e = await _gateway.current();
    var s = await AppPersistence.instance.loadStats(widget.lang);

    // Passive streak reset: fix stale streak display when the player missed day(s).
    if (s.currentStreak > 0) {
      final lastWin = await AppPersistence.instance.loadLastWinDate(widget.lang);
      if (_isStreakBroken(lastWin, today)) {
        if (e.streakFreezes > 0) {
          await _gateway.consumeStreakFreeze();
          e = Entitlements(
            removeAds: e.removeAds,
            archive: e.archive,
            streakFreezes: e.streakFreezes - 1,
          );
        } else {
          s = await AppPersistence.instance.applyPassiveStreakReset(
            lang: widget.lang,
            today: today,
          );
        }
      }
    }

    if (mounted) {
      setState(() {
        _stats = s;
        _entitlements = e;
        _loading = false;
      });
    }
  }

  static bool _isStreakBroken(DateTime? lastWin, DateTime today) {
    if (lastWin == null) return false;
    final todayNorm = DateTime(today.year, today.month, today.day);
    final lastNorm = DateTime(lastWin.year, lastWin.month, lastWin.day);
    return todayNorm.difference(lastNorm).inDays > 1;
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }

    final stats = _stats ?? PlayerStats.empty;
    final winPctStr = '${(stats.winPct * 100).toStringAsFixed(0)}%';

    return Scaffold(
      appBar: AppBar(title: const Text('Statistics')),
      body: Padding(
        padding: const EdgeInsets.all(WarmerSpacing.xl),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
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

            // Streak-freeze count — surfaces non-zero values from IAP entitlements.
            if (_entitlements.streakFreezes > 0) ...[
              const SizedBox(height: WarmerSpacing.xl),
              Text(
                'Streak freezes: ${_entitlements.streakFreezes}',
                style: Theme.of(context).textTheme.bodyMedium,
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
