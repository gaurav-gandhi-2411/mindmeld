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
///   - Waits 3 seconds (making the hint-gating flow fully testable without a
///     real ad SDK).
///   - Returns true (reward granted).
class RewardedAdStub {
  const RewardedAdStub();

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

    // Simulate the 3-second ad watch period.
    await Future<void>.delayed(const Duration(seconds: 3));

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
