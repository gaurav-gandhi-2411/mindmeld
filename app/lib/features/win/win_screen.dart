import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/persistence.dart';
import 'package:mindmeld/stubs/analytics_stub.dart';

import 'share_stub.dart'
    // ignore: uri_does_not_exist
    if (dart.library.html) 'share_web.dart';

/// Generate the spoiler-free heat-trail share card text.
///
/// Format (brand name first, URL last):
///   Mindmeld #N (English)  🟦🟦🟨🟧🟥⭐
///   Par −2 · Beat the bot 🤖✓
///   🔥 3 day streak
///   playmindmeld.vercel.app
///
/// - ⭐ replaces the last emoji when the player solved (rank 1).
/// - Par and rival lines are omitted when payload is v1 (parGuesses null).
/// - No secret word or guess words are ever included.
String buildShareCard({
  required List<Guess> guesses,
  required int puzzleNumber,
  required String lang,
  int? parGuesses,
  int hintsUsed = 0,
  int? rivalSolveAt,
  int currentStreak = 0,
}) {
  final langLabel = lang == 'hi-en' ? '(Hinglish)' : '(English)';

  // Emoji trail: chronological, last replaced by ⭐ if player won
  final won = guesses.isNotEmpty && guesses.last.band == TemperatureBand.win;
  final emojis = guesses.asMap().entries.map((e) {
    if (won && e.key == guesses.length - 1) return '⭐';
    return e.value.band.emoji;
  }).join('');

  final line1 = 'Mindmeld #$puzzleNumber $langLabel  $emojis';
  final lines = <String>[line1];

  // Par + rival outcome line
  if (parGuesses != null) {
    final effectiveGuesses = guesses.length + hintsUsed;
    final delta = effectiveGuesses - parGuesses;
    final parStr =
        delta == 0 ? 'Par' : (delta > 0 ? 'Par +$delta' : 'Par $delta');

    String rivalStr = '';
    if (rivalSolveAt != null) {
      if (guesses.length < rivalSolveAt) {
        rivalStr = ' · Beat the bot 🤖✓';
      } else if (guesses.length == rivalSolveAt) {
        rivalStr = ' · Tied the bot 🤖=';
      } else {
        rivalStr = ' · Bot won 🤖✗';
      }
    }
    lines.add('$parStr$rivalStr');
  }

  // Streak line (only when > 1 day to avoid noise for new players)
  if (currentStreak > 1) {
    lines.add('🔥 $currentStreak day streak');
  }

  lines.add('playmindmeld.vercel.app');
  return lines.join('\n');
}

/// Win screen — shown when the player guesses the secret word.
class WinScreen extends StatefulWidget {
  const WinScreen({
    super.key,
    required this.secret,
    required this.guesses,
    required this.lang,
    required this.date,
    required this.onPlayAgain,
    this.parGuesses,
    this.rivalSolveAt,
    this.hintsUsed = 0,
    this.currentStreak = 0,
  });

  final String secret;
  final List<Guess> guesses;
  final String lang;
  final String date;
  final VoidCallback onPlayAgain;

  /// Par guess count from payload; null for pre-v2 payloads.
  final int? parGuesses;

  /// Rival's solve step count for the selected tier; null when rival disabled/v1.
  final int? rivalSolveAt;

  /// Hints used in this session (each counts as +1 against par).
  final int hintsUsed;

  /// Player's current streak (shown on share card when > 1).
  final int currentStreak;

  @override
  State<WinScreen> createState() => _WinScreenState();
}

class _WinScreenState extends State<WinScreen> {
  final _shareCardKey = GlobalKey();

  int get _puzzleNumber {
    try {
      final start = DateTime(2026, 6, 12);
      final d = DateTime.parse(widget.date);
      return d.difference(start).inDays + 1;
    } catch (_) {
      return 1;
    }
  }

  String get _shareText => buildShareCard(
        guesses: widget.guesses,
        puzzleNumber: _puzzleNumber,
        lang: widget.lang,
        parGuesses: widget.parGuesses,
        hintsUsed: widget.hintsUsed,
        rivalSolveAt: widget.rivalSolveAt,
        currentStreak: widget.currentStreak,
      );

  Future<void> _share(BuildContext context) async {
    await AnalyticsStub(AppPersistence.instance)
        .logEvent(AnalyticsEvent.shareTapped, {'lang': widget.lang});

    if (webShareAvailable()) {
      final shared = await shareViaWebApi(
        title: 'Mindmeld',
        text: _shareText,
        url: 'https://playmindmeld.vercel.app/',
      );
      if (shared) return;
    }

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

  Future<void> _sharePng(BuildContext context) async {
    try {
      final boundary = _shareCardKey.currentContext?.findRenderObject();
      if (boundary is! RenderRepaintBoundary) return;
      final image = await boundary.toImage(pixelRatio: 3.0);
      final byteData = await image.toByteData(format: ui.ImageByteFormat.png);
      if (byteData == null) return;
      await shareOrDownloadPng(byteData.buffer.asUint8List());
    } catch (e) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Could not render image on this device.')),
      );
    }
  }

  Widget _buildParRivalBadge(BuildContext context) {
    final par = widget.parGuesses;
    if (par == null) return const SizedBox.shrink();

    final effectiveGuesses = widget.guesses.length + widget.hintsUsed;
    final delta = effectiveGuesses - par;
    final parStr =
        delta == 0 ? 'Par' : (delta > 0 ? '+$delta vs par' : '$delta vs par');

    String rivalStr = '';
    final rivalSolveAt = widget.rivalSolveAt;
    if (rivalSolveAt != null) {
      if (widget.guesses.length < rivalSolveAt) {
        rivalStr = '  Beat the bot 🤖✓';
      } else if (widget.guesses.length == rivalSolveAt) {
        rivalStr = '  Tied the bot 🤖=';
      } else {
        rivalStr = '  Bot won 🤖✗';
      }
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.primaryContainer,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        '$parStr$rivalStr',
        style: Theme.of(context).textTheme.titleMedium?.copyWith(
              color: Theme.of(context).colorScheme.onPrimaryContainer,
            ),
        textAlign: TextAlign.center,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final sorted = List<Guess>.from(widget.guesses)
      ..sort((a, b) => a.rank.compareTo(b.rank));

    return Scaffold(
      appBar: AppBar(title: const Text('You got it!')),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            const Icon(Icons.emoji_events, size: 80, color: Color(0xFFFBC02D)),
            const SizedBox(height: 16),
            Text(
              widget.secret.toUpperCase(),
              style: Theme.of(context).textTheme.displaySmall?.copyWith(
                    fontWeight: FontWeight.bold,
                    letterSpacing: 4,
                  ),
            ),
            const SizedBox(height: 8),
            Text(
              'Puzzle #$_puzzleNumber · ${widget.guesses.length} guess${widget.guesses.length == 1 ? '' : 'es'}',
              style: Theme.of(context).textTheme.titleMedium,
            ),

            if (widget.parGuesses != null) ...[
              const SizedBox(height: 12),
              _buildParRivalBadge(context),
            ],

            const SizedBox(height: 24),

            // Share card preview (wrapped in RepaintBoundary for PNG capture)
            RepaintBoundary(
              key: _shareCardKey,
              child: Container(
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
            ),

            const SizedBox(height: 16),

            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                FilledButton.icon(
                  onPressed: () => _share(context),
                  icon: const Icon(Icons.share),
                  label: const Text('Copy & Share'),
                ),
                const SizedBox(width: 12),
                OutlinedButton.icon(
                  onPressed: () => _sharePng(context),
                  icon: const Icon(Icons.image_outlined),
                  label: const Text('Image'),
                ),
              ],
            ),

            const SizedBox(height: 32),

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

            const SizedBox(height: 32),
            TextButton(
              onPressed: widget.onPlayAgain,
              child: const Text('Back'),
            ),
          ],
        ),
      ),
    );
  }
}
