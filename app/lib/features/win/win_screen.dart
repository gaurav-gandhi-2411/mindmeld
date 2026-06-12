import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:mindmeld/core/config.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/persistence.dart';
import 'package:mindmeld/stubs/analytics_stub.dart';

// Conditional import: web platforms get the real Web Share API impl;
// native platforms get a stub that always returns false.
import 'share_stub.dart'
    // ignore: uri_does_not_exist
    if (dart.library.html) 'share_web.dart';

/// Generate the spoiler-free share card text.
///
/// Format:
///   Mindmeld #N 🧠 X guesses
///   [emoji grid]
///   [play URL]
///
/// The secret word is NEVER included in the share text.
/// The play URL is appended on all platforms to create a viral loop.
String buildShareCard({
  required List<Guess> guesses,
  required int puzzleNumber,
}) {
  final emojis = guesses.map((g) => g.band.emoji).join('');
  final count = guesses.length;
  final line1 = 'Mindmeld #$puzzleNumber 🧠 $count guess${count == 1 ? '' : 'es'}';
  return '$line1\n$emojis\n${AppConfig.playUrl}';
}

/// Win screen — shown when the player guesses the secret word.
///
/// Displays: secret word, guess count, best-rank progression, share card.
class WinScreen extends StatelessWidget {
  const WinScreen({
    super.key,
    required this.secret,
    required this.guesses,
    required this.lang,
    required this.date,
    required this.onPlayAgain,
  });

  final String secret;
  final List<Guess> guesses;
  final String lang;
  final String date;
  final VoidCallback onPlayAgain;

  // Puzzle number is derived from the date offset from the start date.
  int get _puzzleNumber {
    try {
      final start = DateTime(2026, 6, 12);
      final d = DateTime.parse(date);
      return d.difference(start).inDays + 1;
    } catch (_) {
      return 1;
    }
  }

  String get _shareText =>
      buildShareCard(guesses: guesses, puzzleNumber: _puzzleNumber);

  /// Share handler — uses Web Share API on web when available, falls back to
  /// clipboard+dialog on native and on desktop browsers without navigator.share.
  Future<void> _share(BuildContext context) async {
    await AnalyticsStub(AppPersistence.instance)
        .logEvent(AnalyticsEvent.shareTapped, {'lang': lang});

    // Try the Web Share API first (mobile browsers, supported desktop browsers).
    if (webShareAvailable()) {
      final shared = await shareViaWebApi(
        title: 'Mindmeld',
        text: _shareText,
        url: AppConfig.playUrl,
      );
      if (shared) return; // Share sheet shown — done.
      // Fall through to clipboard if share was cancelled or failed.
    }

    // Fallback: clipboard + dialog (native, desktop browsers, cancelled shares).
    await Clipboard.setData(ClipboardData(text: _shareText));

    if (!context.mounted) return;

    showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Share your result'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Theme.of(ctx).colorScheme.surfaceContainerHighest,
                borderRadius: BorderRadius.circular(8),
              ),
              child: SelectableText(
                _shareText,
                style: const TextStyle(fontFamily: 'monospace'),
              ),
            ),
            const SizedBox(height: 12),
            const Text('Copied to clipboard!'),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Close'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final sorted = List<Guess>.from(guesses)
      ..sort((a, b) => a.rank.compareTo(b.rank));

    return Scaffold(
      appBar: AppBar(title: const Text('You got it!')),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            // Trophy
            const Icon(Icons.emoji_events, size: 80, color: Color(0xFFFBC02D)),
            const SizedBox(height: 16),

            // Secret word reveal
            Text(
              secret.toUpperCase(),
              style: Theme.of(context).textTheme.displaySmall?.copyWith(
                    fontWeight: FontWeight.bold,
                    letterSpacing: 4,
                  ),
            ),
            const SizedBox(height: 8),
            Text(
              'Puzzle #$_puzzleNumber · ${guesses.length} guess${guesses.length == 1 ? '' : 'es'}',
              style: Theme.of(context).textTheme.titleMedium,
            ),

            const SizedBox(height: 24),

            // Share card preview
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: Theme.of(context).colorScheme.surfaceContainerHighest,
                borderRadius: BorderRadius.circular(12),
              ),
              child: Text(
                _shareText,
                style: const TextStyle(fontSize: 16),
              ),
            ),

            const SizedBox(height: 16),

            // Share button
            FilledButton.icon(
              onPressed: () => _share(context),
              icon: const Icon(Icons.share),
              label: const Text('Copy & Share'),
            ),

            const SizedBox(height: 32),

            // Best rank progression (top 5 closest guesses)
            Text(
              'Your closest guesses:',
              style: Theme.of(context).textTheme.titleSmall,
            ),
            const SizedBox(height: 8),
            ...sorted.take(5).map(
                  (g) => Padding(
                    padding: const EdgeInsets.symmetric(vertical: 2),
                    child: Row(
                      children: [
                        Text(
                          '#${g.rank}',
                          style: const TextStyle(fontWeight: FontWeight.bold),
                        ),
                        const SizedBox(width: 12),
                        Text(g.word),
                        const Spacer(),
                        Text(g.band.label),
                      ],
                    ),
                  ),
                ),
          ],
        ),
      ),
    );
  }
}
