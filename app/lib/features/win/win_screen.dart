import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:mindmeld/analytics/firebase_exporter.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/features/notifications/notification_opt_in_card.dart';
import 'package:mindmeld/notifications/notification_service.dart';
import 'package:mindmeld/stubs/analytics_stub.dart';

import 'share_stub.dart'
    // ignore: uri_does_not_exist
    if (dart.library.html) 'share_web.dart';

/// Generate the spoiler-free heat-trail share card text.
///
/// Format for wins (brand name first, URL last):
///   Mindmeld #N (English)  🟦🟦🟨🟧🟥⭐
///   6/15 · Par −2 · Beat the bot 🤖✓
///   🔥 3 day streak
///   playmindmeld.vercel.app
///
/// Format for losses:
///   Mindmeld #N (English)  🟦🟦🟨🟧🟥💀
///   Didn't get it — best: 🟥 · streak reset
///   playmindmeld.vercel.app
///
/// - [won] controls the terminal emoji (⭐ for win, 💀 for loss).
/// - Par and rival lines are omitted when payload is v1 (parGuesses null).
/// - [maxGuesses] shows the budget fraction on the par line (e.g. 6/15).
/// - No secret word or guess words are ever included.
///
/// When [packName] is non-null (themed-pack puzzle, phase 6c), line 1 becomes:
///   Mindmeld · $packName #N (English)  🟦🟦🟨🟧🟥⭐
/// Daily output ([packName] null) is byte-identical to the original format.
String buildShareCard({
  required List<Guess> guesses,
  required int puzzleNumber,
  required String lang,
  int? parGuesses,
  int? maxGuesses,
  int hintsUsed = 0,
  int? rivalSolveAt,
  int currentStreak = 0,
  /// Pass [true] for wins (⭐ terminal) or [false] for losses (💀 terminal).
  /// When null (the default), win is auto-detected from whether the last guess
  /// has [TemperatureBand.win] — preserving backward compatibility.
  bool? won,
  /// Themed-pack display name (phase 6c); null for daily puzzles.
  String? packName,
}) {
  final langLabel = lang == 'hi-en' ? '(Hinglish)' : '(English)';

  // Auto-detect win when the caller doesn't specify (backward compat).
  final effectiveWon =
      won ?? (guesses.isNotEmpty && guesses.last.band == TemperatureBand.win);

  // Emoji trail: chronological, last replaced by ⭐ (win) or 💀 (loss).
  final emojis = guesses.asMap().entries.map((e) {
    final isLast = e.key == guesses.length - 1;
    if (isLast && effectiveWon) return '⭐';
    if (isLast && !effectiveWon) return '💀';
    return e.value.band.emoji;
  }).join('');

  final line1 = packName != null
      ? 'Mindmeld · $packName #$puzzleNumber $langLabel  $emojis'
      : 'Mindmeld #$puzzleNumber $langLabel  $emojis';
  final lines = <String>[line1];

  if (effectiveWon) {
    // Par + rival outcome line (wins only).
    if (parGuesses != null) {
      final effectiveGuesses = guesses.length + hintsUsed;
      final delta = effectiveGuesses - parGuesses;
      final parStr =
          delta == 0 ? 'Par' : (delta > 0 ? 'Par +$delta' : 'Par $delta');

      final budgetStr =
          maxGuesses != null ? '${guesses.length}/$maxGuesses' : '${guesses.length}';

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
      lines.add('$budgetStr · $parStr$rivalStr');
    }

    // Streak line (only when > 1 day to avoid noise for new players).
    if (currentStreak > 1) {
      lines.add('🔥 $currentStreak day streak');
    }
  } else {
    // Loss outcome line: best band reached + streak reset notice.
    final bestGuess = guesses.isEmpty
        ? null
        : guesses.reduce((a, b) => a.rank < b.rank ? a : b);
    final bestEmoji = bestGuess?.band.emoji ?? '❓';
    lines.add("Didn't get it — best: $bestEmoji · streak reset");
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
    this.maxGuesses,
    this.rivalSolveAt,
    this.hintsUsed = 0,
    this.currentStreak = 0,
    this.exporter,
    this.onChallengeGroup,
    this.notificationService,
    this.packName,
    this.packPuzzleNumber,
  });

  final String secret;
  final List<Guess> guesses;
  final String lang;
  final String date;
  final VoidCallback onPlayAgain;

  /// Par guess count from payload; null for pre-v2 payloads.
  final int? parGuesses;

  /// Maximum guess budget from payload; null for pre-v3 payloads.
  final int? maxGuesses;

  /// Rival's solve step count for the selected tier; null when rival disabled/v1.
  final int? rivalSolveAt;

  /// Hints used in this session (each counts as +1 against par).
  final int hintsUsed;

  /// Player's current streak (shown on share card when > 1).
  final int currentStreak;

  /// Optional analytics exporter override.
  ///
  /// When null, [buildAnalyticsExporter] is called to construct the default
  /// exporter.
  final AnalyticsExporter? exporter;

  /// "Challenge your group" CTA — opens the social/groups screen. Null hides
  /// the button (e.g. in tests that don't wire social navigation).
  final VoidCallback? onChallengeGroup;

  /// Optional [NotificationService] override for tests. When null
  /// [buildNotificationService] is used by [NotificationOptInCard].
  final NotificationService? notificationService;

  /// Themed-pack display name (phase 6c); null for daily puzzles.
  final String? packName;

  /// 1-based puzzle number within [packName]'s pack (phase 6c); null for
  /// daily puzzles, which derive their number from [date] instead.
  final int? packPuzzleNumber;

  @override
  State<WinScreen> createState() => _WinScreenState();
}

class _WinScreenState extends State<WinScreen> {
  final _shareCardKey = GlobalKey();
  bool _showNotifCard = false;

  @override
  void initState() {
    super.initState();
    _checkNotifCard();
  }

  Future<void> _checkNotifCard() async {
    final show = await shouldShowNotificationOptInCard(service: widget.notificationService);
    if (mounted) setState(() => _showNotifCard = show);
  }

  int get _puzzleNumber {
    if (widget.packPuzzleNumber != null) return widget.packPuzzleNumber!;
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
        maxGuesses: widget.maxGuesses,
        hintsUsed: widget.hintsUsed,
        rivalSolveAt: widget.rivalSolveAt,
        currentStreak: widget.currentStreak,
        won: true,
        packName: widget.packName,
      );

  Future<void> _share(BuildContext context) async {
    final analytics = widget.exporter ?? buildAnalyticsExporter();
    await analytics.logEvent(AnalyticsEvent.shareTapped, {
      'lang': widget.lang,
      'day': widget.date,
      'guesses_used': widget.guesses.length + widget.hintsUsed,
      'max_guesses': widget.maxGuesses ?? 0,
      'par': widget.parGuesses ?? 0,
      'outcome': 'win',
    });

    final shareTitle =
        widget.packName != null ? 'Mindmeld · ${widget.packName}' : 'Mindmeld';
    if (webShareAvailable()) {
      final shared = await shareViaWebApi(
        title: shareTitle,
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
              '${widget.packName != null ? '${widget.packName} ' : ''}'
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

            if (widget.onChallengeGroup != null) ...[
              const SizedBox(height: 12),
              TextButton.icon(
                onPressed: widget.onChallengeGroup,
                icon: const Icon(Icons.groups),
                label: const Text('Challenge your group'),
              ),
            ],

            if (_showNotifCard) ...[
              const SizedBox(height: 16),
              NotificationOptInCard(
                lang: widget.lang,
                notificationService: widget.notificationService,
                exporter: widget.exporter,
                onDismissed: () => setState(() => _showNotifCard = false),
              ),
            ],

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

/// Loss screen — shown when the player runs out of guesses or gives up.
class LossScreen extends StatefulWidget {
  const LossScreen({
    super.key,
    required this.secret,
    required this.guesses,
    required this.lang,
    required this.date,
    required this.onClose,
    this.parGuesses,
    this.maxGuesses,
    this.rivalSolveAt,
    this.hintsUsed = 0,
    this.gaveUp = false,
    this.exporter,
    this.onChallengeGroup,
    this.notificationService,
    this.packName,
    this.packPuzzleNumber,
  });

  final String secret;
  final List<Guess> guesses;
  final String lang;
  final String date;
  final VoidCallback onClose;

  /// Par guess count from payload; null for pre-v2 payloads.
  final int? parGuesses;

  /// Maximum guess budget from payload; null for pre-v3 payloads.
  final int? maxGuesses;

  /// Rival's solve step count for the selected tier; null when rival disabled/v1.
  final int? rivalSolveAt;

  /// Hints used in this session.
  final int hintsUsed;

  /// True when the player explicitly chose to give up (vs budget exhaustion).
  final bool gaveUp;

  /// Optional analytics exporter override.
  ///
  /// When null, [buildAnalyticsExporter] is called to construct the default
  /// exporter.
  final AnalyticsExporter? exporter;

  /// "Challenge your group" CTA — opens the social/groups screen. Null hides
  /// the button (e.g. in tests that don't wire social navigation).
  final VoidCallback? onChallengeGroup;

  /// Optional [NotificationService] override for tests. When null
  /// [buildNotificationService] is used by [NotificationOptInCard].
  final NotificationService? notificationService;

  /// Themed-pack display name (phase 6c); null for daily puzzles.
  final String? packName;

  /// 1-based puzzle number within [packName]'s pack (phase 6c); null for
  /// daily puzzles, which derive their number from [date] instead.
  final int? packPuzzleNumber;

  @override
  State<LossScreen> createState() => _LossScreenState();
}

class _LossScreenState extends State<LossScreen> {
  final _shareCardKey = GlobalKey();
  bool _showNotifCard = false;

  @override
  void initState() {
    super.initState();
    _checkNotifCard();
  }

  Future<void> _checkNotifCard() async {
    final show = await shouldShowNotificationOptInCard(service: widget.notificationService);
    if (mounted) setState(() => _showNotifCard = show);
  }

  int get _puzzleNumber {
    if (widget.packPuzzleNumber != null) return widget.packPuzzleNumber!;
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
        maxGuesses: widget.maxGuesses,
        hintsUsed: widget.hintsUsed,
        rivalSolveAt: widget.rivalSolveAt,
        won: false,
        packName: widget.packName,
      );

  Future<void> _share(BuildContext context) async {
    final analytics = widget.exporter ?? buildAnalyticsExporter();
    await analytics.logEvent(AnalyticsEvent.shareTapped, {
      'lang': widget.lang,
      'day': widget.date,
      'guesses_used': widget.guesses.length + widget.hintsUsed,
      'max_guesses': widget.maxGuesses ?? 0,
      'par': widget.parGuesses ?? 0,
      'outcome': 'loss',
    });

    final shareTitle =
        widget.packName != null ? 'Mindmeld · ${widget.packName}' : 'Mindmeld';
    if (webShareAvailable()) {
      final shared = await shareViaWebApi(
        title: shareTitle,
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

  @override
  Widget build(BuildContext context) {
    final sorted = List<Guess>.from(widget.guesses)
      ..sort((a, b) => a.rank.compareTo(b.rank));
    final bestGuess = sorted.isEmpty ? null : sorted.first;

    final langLabel = widget.lang == 'hi-en' ? 'Hinglish' : 'English';
    final reasonText = widget.gaveUp ? 'You gave up' : 'Budget exhausted';

    return Scaffold(
      appBar: AppBar(title: const Text('Better luck next time 🌙')),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            const Icon(Icons.sentiment_dissatisfied, size: 80, color: Color(0xFF9E9E9E)),
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
              '${widget.packName != null ? '${widget.packName} ' : ''}'
              'Puzzle #$_puzzleNumber · $langLabel · $reasonText',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            if (bestGuess != null) ...[
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                decoration: BoxDecoration(
                  color: Theme.of(context).colorScheme.errorContainer,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  'Your best: ${bestGuess.band.emoji} #${bestGuess.rank} — so close!',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        color: Theme.of(context).colorScheme.onErrorContainer,
                      ),
                  textAlign: TextAlign.center,
                ),
              ),
            ],
            const SizedBox(height: 24),
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
            if (widget.onChallengeGroup != null) ...[
              const SizedBox(height: 12),
              TextButton.icon(
                onPressed: widget.onChallengeGroup,
                icon: const Icon(Icons.groups),
                label: const Text('Challenge your group'),
              ),
            ],
            if (_showNotifCard) ...[
              const SizedBox(height: 16),
              NotificationOptInCard(
                lang: widget.lang,
                notificationService: widget.notificationService,
                exporter: widget.exporter,
                onDismissed: () => setState(() => _showNotifCard = false),
              ),
            ],
            const SizedBox(height: 32),
            if (widget.guesses.isNotEmpty) ...[
              Text(
                'Your guesses this round:',
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
            const SizedBox(height: 32),
            TextButton(
              onPressed: widget.onClose,
              child: const Text('Back'),
            ),
          ],
        ),
      ),
    );
  }
}
