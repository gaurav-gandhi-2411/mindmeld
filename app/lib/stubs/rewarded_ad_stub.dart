import 'package:flutter/material.dart';
import 'package:mindmeld/core/config.dart';

/// Stub for the rewarded-ad flow.
///
/// Phase 2: Replace the simulated delay + modal with a real AdMob rewarded-ad
/// load/show cycle. The [show] contract (returns true on successful reward)
/// stays the same — callers need not change.
///
/// When [AppConfig.adsEnabled] is false (Phase 1), this stub:
///   - Shows a modal dialog informing the user that an ad is being simulated.
///   - Waits [simulatedDelay] (default 3 s; [Duration.zero] in tests keeps
///     the timer drained by a single [WidgetTester.pump]).
///   - Returns true (reward granted).
///
/// ## Widget-test usage
///
/// Pass `simulatedDelay: const Duration(seconds: 4)` (or any non-zero value)
/// and advance the fake clock with `tester.pump(const Duration(seconds: 5))`
/// after tapping the hint button.  The fake-async clock advances instantly, so
/// no real wall-clock time is consumed.
///
/// If you need the dialog to appear *before* the delay fires, pump once
/// (shows the dialog), inspect, then pump with the target duration to fire the
/// timer and dismiss the dialog.
class RewardedAdStub {
  const RewardedAdStub({this.simulatedDelay = const Duration(seconds: 3)});

  /// How long the simulated ad modal is displayed before auto-dismissing.
  ///
  /// In widget tests inject a short [Duration] (e.g. `Duration(seconds: 1)`)
  /// and pump past it with `tester.pump(Duration(seconds: 4))`.
  /// The fake-async clock advances instantly — no real time is consumed.
  final Duration simulatedDelay;

  /// Show the rewarded ad (or stub) and return true if the reward was granted.
  ///
  /// [context] must be a valid [BuildContext] with a mounted scaffold.
  /// Never call this after the widget tree is disposed.
  Future<bool> show(BuildContext context) async {
    if (!AppConfig.adsEnabled) {
      return _showSimulated(context);
    }
    // Phase 2: load and show real AdMob rewarded ad here.
    // Example:
    //   final ad = await RewardedAd.load(...);
    //   final rewarded = await ad.show();
    //   return rewarded;
    throw UnimplementedError('Real ad SDK not wired in Phase 1.');
  }

  Future<bool> _showSimulated(BuildContext context) async {
    // Show "simulated ad" modal so the flow is visible during testing.
    if (!context.mounted) return false;

    showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (_) => const _SimulatedAdDialog(),
    );

    // Simulate the ad watch period.
    // In widget tests the fake-async clock is advanced by pump(duration), so
    // this Future resolves instantly from the test's perspective.
    await Future<void>.delayed(simulatedDelay);

    // Dismiss the dialog if still mounted.
    if (context.mounted) {
      Navigator.of(context, rootNavigator: true).pop();
    }

    return true;
  }
}

class _SimulatedAdDialog extends StatelessWidget {
  const _SimulatedAdDialog();

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Watching ad…'),
      content: const Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          CircularProgressIndicator(),
          SizedBox(height: 16),
          Text(
            'Simulated ad (Phase 1 stub). Ads will be real in Phase 2.',
            textAlign: TextAlign.center,
          ),
        ],
      ),
    );
  }
}
