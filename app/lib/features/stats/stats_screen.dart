import 'package:flutter/material.dart';
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
  });

  final String lang;

  /// Optional IAP gateway; package-accessible for test injection.
  final IapGateway? iapGateway;

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

  Future<void> _load() async {
    final s = await AppPersistence.instance.loadStats(widget.lang);
    final e = await _gateway.current();
    if (mounted) {
      setState(() {
        _stats = s;
        _entitlements = e;
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

    return Scaffold(
      appBar: AppBar(title: const Text('Statistics')),
      body: Padding(
        padding: const EdgeInsets.all(24),
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

            const SizedBox(height: 32),

            Text(
              'Guess Distribution',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 12),

            if (stats.guessDistribution.isEmpty)
              const Text('No wins yet — play a puzzle!')
            else
              ..._buildDistribution(context, stats),

            // Streak-freeze count — surfaces non-zero values from IAP entitlements.
            if (_entitlements.streakFreezes > 0) ...[
              const SizedBox(height: 24),
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
              child: Text(key, textAlign: TextAlign.right),
            ),
            const SizedBox(width: 8),
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
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(
                    '$count',
                    style: const TextStyle(
                      color: Colors.white,
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
    return Column(
      children: [
        Text(
          value,
          style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                fontWeight: FontWeight.bold,
              ),
        ),
        Text(label, style: Theme.of(context).textTheme.labelSmall),
      ],
    );
  }
}
