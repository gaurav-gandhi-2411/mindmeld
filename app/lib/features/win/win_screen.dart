import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:mindmeld/analytics/firebase_exporter.dart';
import 'package:mindmeld/core/design_tokens.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/features/branding/heat_rings_mark.dart';
import 'package:mindmeld/features/notifications/notification_opt_in_card.dart';
import 'package:mindmeld/features/packs/pack_selector_screen.dart';
import 'package:mindmeld/features/packs/packs_entry_banner.dart';
import 'package:mindmeld/features/puzzle/guess_tile.dart' show heatForBand;
import 'package:mindmeld/notifications/notification_service.dart';
import 'package:mindmeld/stubs/analytics_stub.dart';

// dart.library.js_interop, not dart.library.html: html is FALSE under the
// --wasm production build target, which silently stubbed the share path on
// live (known-limitations entry 19). share_web.dart is already package:web.
import 'share_stub.dart'
    // ignore: uri_does_not_exist
    if (dart.library.js_interop) 'share_web.dart';

/// Generate the spoiler-free heat-trail share card text.
///
/// Format for wins (brand name first, URL last):
///   Warmer #N (English)  🟦🟦🟨🟧🟥⭐
///   6/15 · Par −2 · Beat the bot 🤖✓
///   🔥 3 day streak
///   playwarmer.vercel.app
///
/// Format for losses:
///   Warmer #N (English)  🟦🟦🟨🟧🟥💀
///   Didn't get it — best: 🟥 · streak reset
///   playwarmer.vercel.app
///
/// - [won] controls the terminal emoji (⭐ for win, 💀 for loss).
/// - Par and rival lines are omitted when payload is v1 (parGuesses null).
/// - [maxGuesses] shows the budget fraction on the par line (e.g. 6/15).
/// - No secret word or guess words are ever included.
///
/// When [packName] is non-null (themed-pack puzzle, phase 6c), line 1 becomes:
///   Warmer · $packName #N (English)  🟦🟦🟨🟧🟥⭐
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
      ? 'Warmer · $packName #$puzzleNumber $langLabel  $emojis'
      : 'Warmer #$puzzleNumber $langLabel  $emojis';
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

  lines.add('playwarmer.vercel.app');
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
        widget.packName != null ? 'Warmer · ${widget.packName}' : 'Warmer';
    if (webShareAvailable()) {
      final shared = await shareViaWebApi(
        title: shareTitle,
        text: _shareText,
        url: 'https://playwarmer.vercel.app/',
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
              padding: const EdgeInsets.all(WarmerSpacing.md),
              decoration: BoxDecoration(
                color: Theme.of(ctx).colorScheme.surfaceContainerHighest,
                borderRadius: BorderRadius.circular(WarmerRadius.sm),
              ),
              child: SelectableText(
                _shareText,
                style: const TextStyle(fontFamily: 'monospace'),
              ),
            ),
            const SizedBox(height: WarmerSpacing.md),
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
      padding: const EdgeInsets.symmetric(
          horizontal: WarmerSpacing.lg, vertical: WarmerSpacing.sm),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.primaryContainer,
        borderRadius: BorderRadius.circular(WarmerRadius.sm),
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
        padding: const EdgeInsets.all(WarmerSpacing.xl),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            // Packs entry — daily-mode only. Hidden for pack-mode wins
            // (widget.packName != null) to avoid recursion into the pack
            // system from within a pack puzzle's own result screen. This is
            // the fix for packs being unreachable from a result screen
            // reached directly (no puzzle-tab "Back" tap needed) — see
            // packs_entry_banner.dart for the shared widget.
            if (widget.packName == null)
              PacksEntryBanner(
                compact: true,
                onTap: () => Navigator.push(
                  context,
                  MaterialPageRoute<void>(
                    builder: (_) => PackSelectorScreen(lang: widget.lang),
                  ),
                ),
              ),
            const HeatRingsMark(size: 72),
            const SizedBox(height: WarmerSpacing.lg),
            Text(
              widget.secret.toUpperCase(),
              style: Theme.of(context).textTheme.displaySmall?.copyWith(
                    fontWeight: FontWeight.bold,
                    letterSpacing: 4,
                  ),
            ),
            const SizedBox(height: WarmerSpacing.sm),
            Text(
              '${widget.packName != null ? '${widget.packName} ' : ''}'
              'Puzzle #$_puzzleNumber · ${widget.guesses.length} guess${widget.guesses.length == 1 ? '' : 'es'}',
              style: Theme.of(context).textTheme.titleMedium,
            ),

            if (widget.parGuesses != null) ...[
              const SizedBox(height: WarmerSpacing.md),
              _buildParRivalBadge(context),
            ],

            const SizedBox(height: WarmerSpacing.xl),

            // Share card preview (wrapped in RepaintBoundary for PNG capture)
            RepaintBoundary(
              key: _shareCardKey,
              child: _SharePreviewCard(
                guesses: widget.guesses,
                won: true,
                puzzleNumber: _puzzleNumber,
                lang: widget.lang,
                packName: widget.packName,
                parGuesses: widget.parGuesses,
                maxGuesses: widget.maxGuesses,
                hintsUsed: widget.hintsUsed,
                rivalSolveAt: widget.rivalSolveAt,
                currentStreak: widget.currentStreak,
              ),
            ),

            const SizedBox(height: WarmerSpacing.lg),

            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                FilledButton.icon(
                  onPressed: () => _share(context),
                  icon: const Icon(Icons.share),
                  label: const Text('Copy & Share'),
                ),
                const SizedBox(width: WarmerSpacing.md),
                OutlinedButton.icon(
                  onPressed: () => _sharePng(context),
                  icon: const Icon(Icons.image_outlined),
                  label: const Text('Image'),
                ),
              ],
            ),

            if (widget.onChallengeGroup != null) ...[
              const SizedBox(height: WarmerSpacing.md),
              TextButton.icon(
                onPressed: widget.onChallengeGroup,
                icon: const Icon(Icons.groups),
                label: const Text('Challenge your group'),
              ),
            ],

            if (_showNotifCard) ...[
              const SizedBox(height: WarmerSpacing.lg),
              NotificationOptInCard(
                lang: widget.lang,
                notificationService: widget.notificationService,
                exporter: widget.exporter,
                onDismissed: () => setState(() => _showNotifCard = false),
              ),
            ],

            const SizedBox(height: WarmerSpacing.xxl),

            Builder(builder: (ctx) {
              final tokens =
                  Theme.of(ctx).extension<WarmerTokens>() ?? WarmerTokens.light;
              return Text(
                'Your closest guesses:',
                style: microLabel(tokens),
              );
            }),
            const SizedBox(height: WarmerSpacing.sm),
            ...sorted.take(5).map(
                  (g) => Builder(builder: (ctx) {
                    final heat = heatForBand(ctx, g.band);
                    final tokens =
                        Theme.of(ctx).extension<WarmerTokens>() ?? WarmerTokens.light;
                    return Padding(
                      padding: const EdgeInsets.symmetric(vertical: 2),
                      child: Row(
                        children: [
                          Container(
                            width: 12,
                            height: 12,
                            decoration: BoxDecoration(
                              color: heat.base,
                              borderRadius: BorderRadius.circular(3),
                            ),
                          ),
                          const SizedBox(width: 10),
                          Text(
                            '#${g.rank}',
                            style: TextStyle(
                              fontWeight: FontWeight.w600,
                              color: heat.text,
                            ),
                          ),
                          const SizedBox(width: WarmerSpacing.md),
                          Text(g.word, style: TextStyle(color: tokens.text1)),
                          const Spacer(),
                          Text(
                            g.band.label,
                            style: Theme.of(ctx)
                                .textTheme
                                .labelSmall
                                ?.copyWith(color: heat.text),
                          ),
                        ],
                      ),
                    );
                  }),
                ),

            const SizedBox(height: WarmerSpacing.xxl),
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
        widget.packName != null ? 'Warmer · ${widget.packName}' : 'Warmer';
    if (webShareAvailable()) {
      final shared = await shareViaWebApi(
        title: shareTitle,
        text: _shareText,
        url: 'https://playwarmer.vercel.app/',
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
              padding: const EdgeInsets.all(WarmerSpacing.md),
              decoration: BoxDecoration(
                color: Theme.of(ctx).colorScheme.surfaceContainerHighest,
                borderRadius: BorderRadius.circular(WarmerRadius.sm),
              ),
              child: SelectableText(
                _shareText,
                style: const TextStyle(fontFamily: 'monospace'),
              ),
            ),
            const SizedBox(height: WarmerSpacing.md),
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
        padding: const EdgeInsets.all(WarmerSpacing.xl),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            // Packs entry — daily-mode only. Hidden for pack-mode losses
            // (widget.packName != null) to avoid recursion into the pack
            // system from within a pack puzzle's own result screen. This is
            // the fix for packs being unreachable from a result screen
            // reached directly (no puzzle-tab "Back" tap needed) — see
            // packs_entry_banner.dart for the shared widget.
            if (widget.packName == null)
              PacksEntryBanner(
                compact: true,
                onTap: () => Navigator.push(
                  context,
                  MaterialPageRoute<void>(
                    builder: (_) => PackSelectorScreen(lang: widget.lang),
                  ),
                ),
              ),
            Builder(builder: (ctx) {
              final tokens =
                  Theme.of(ctx).extension<WarmerTokens>() ?? WarmerTokens.light;
              return Icon(Icons.sentiment_dissatisfied, size: 64, color: tokens.text3);
            }),
            const SizedBox(height: WarmerSpacing.lg),
            Text(
              widget.secret.toUpperCase(),
              style: Theme.of(context).textTheme.displaySmall?.copyWith(
                    fontWeight: FontWeight.bold,
                    letterSpacing: 4,
                  ),
            ),
            const SizedBox(height: WarmerSpacing.sm),
            Text(
              '${widget.packName != null ? '${widget.packName} ' : ''}'
              'Puzzle #$_puzzleNumber · $langLabel · $reasonText',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            if (bestGuess != null) ...[
              const SizedBox(height: WarmerSpacing.md),
              Container(
                padding: const EdgeInsets.symmetric(
                    horizontal: WarmerSpacing.lg, vertical: WarmerSpacing.sm),
                decoration: BoxDecoration(
                  color: Theme.of(context).colorScheme.errorContainer,
                  borderRadius: BorderRadius.circular(WarmerRadius.sm),
                ),
                child: Text(
                  'Your best: ${bestGuess.band.label} #${bestGuess.rank} — so close!',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        color: Theme.of(context).colorScheme.onErrorContainer,
                      ),
                  textAlign: TextAlign.center,
                ),
              ),
            ],
            const SizedBox(height: WarmerSpacing.xl),
            RepaintBoundary(
              key: _shareCardKey,
              child: _SharePreviewCard(
                guesses: widget.guesses,
                won: false,
                puzzleNumber: _puzzleNumber,
                lang: widget.lang,
                packName: widget.packName,
                parGuesses: widget.parGuesses,
                maxGuesses: widget.maxGuesses,
                hintsUsed: widget.hintsUsed,
                rivalSolveAt: widget.rivalSolveAt,
              ),
            ),
            const SizedBox(height: WarmerSpacing.lg),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                FilledButton.icon(
                  onPressed: () => _share(context),
                  icon: const Icon(Icons.share),
                  label: const Text('Copy & Share'),
                ),
                const SizedBox(width: WarmerSpacing.md),
                OutlinedButton.icon(
                  onPressed: () => _sharePng(context),
                  icon: const Icon(Icons.image_outlined),
                  label: const Text('Image'),
                ),
              ],
            ),
            if (widget.onChallengeGroup != null) ...[
              const SizedBox(height: WarmerSpacing.md),
              TextButton.icon(
                onPressed: widget.onChallengeGroup,
                icon: const Icon(Icons.groups),
                label: const Text('Challenge your group'),
              ),
            ],
            if (_showNotifCard) ...[
              const SizedBox(height: WarmerSpacing.lg),
              NotificationOptInCard(
                lang: widget.lang,
                notificationService: widget.notificationService,
                exporter: widget.exporter,
                onDismissed: () => setState(() => _showNotifCard = false),
              ),
            ],
            const SizedBox(height: WarmerSpacing.xxl),
            if (widget.guesses.isNotEmpty) ...[
              Builder(builder: (ctx) {
                final tokens =
                    Theme.of(ctx).extension<WarmerTokens>() ?? WarmerTokens.light;
                return Text(
                  'Your guesses this round:',
                  style: microLabel(tokens),
                );
              }),
              const SizedBox(height: WarmerSpacing.sm),
              ...sorted.take(5).map(
                    (g) => Builder(builder: (ctx) {
                      final heat = heatForBand(ctx, g.band);
                      final tokens = Theme.of(ctx).extension<WarmerTokens>() ??
                          WarmerTokens.light;
                      return Padding(
                        padding: const EdgeInsets.symmetric(vertical: 2),
                        child: Row(
                          children: [
                            Container(
                              width: 12,
                              height: 12,
                              decoration: BoxDecoration(
                                color: heat.base,
                                borderRadius: BorderRadius.circular(3),
                              ),
                            ),
                            const SizedBox(width: 10),
                            Text(
                              '#${g.rank}',
                              style: TextStyle(
                                fontWeight: FontWeight.w600,
                                color: heat.text,
                              ),
                            ),
                            const SizedBox(width: WarmerSpacing.md),
                            Text(g.word, style: TextStyle(color: tokens.text1)),
                            const Spacer(),
                            Text(
                              g.band.label,
                              style: Theme.of(ctx)
                                  .textTheme
                                  .labelSmall
                                  ?.copyWith(color: heat.text),
                            ),
                          ],
                        ),
                      );
                    }),
                  ),
            ],
            const SizedBox(height: WarmerSpacing.xxl),
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

/// The visual share-card preview shown inside the `RepaintBoundary` on both
/// [WinScreen] and [LossScreen] — this becomes the shared PNG, the
/// most-seen brand surface.
///
/// IMPORTANT: this widget is display-only. It computes its own headline/
/// result strings from the same fields [buildShareCard] uses, but is
/// entirely independent of [buildShareCard] and the clipboard/Web-Share
/// text — changing this widget must never change [buildShareCard]'s output.
class _SharePreviewCard extends StatelessWidget {
  const _SharePreviewCard({
    required this.guesses,
    required this.won,
    required this.puzzleNumber,
    required this.lang,
    this.packName,
    this.parGuesses,
    this.maxGuesses,
    this.hintsUsed = 0,
    this.rivalSolveAt,
    this.currentStreak = 0,
  });

  /// Guesses in chronological order (the order they were made).
  final List<Guess> guesses;
  final bool won;
  final int puzzleNumber;
  final String lang;
  final String? packName;
  final int? parGuesses;
  final int? maxGuesses;
  final int hintsUsed;
  final int? rivalSolveAt;
  final int currentStreak;

  String get _headline {
    final langLabel = lang == 'hi-en' ? 'Hinglish' : 'English';
    return packName != null
        ? 'Warmer · $packName #$puzzleNumber ($langLabel)'
        : 'Warmer #$puzzleNumber ($langLabel)';
  }

  String get _resultLine {
    final n = guesses.length;
    if (!won) {
      final bestGuess = guesses.isEmpty
          ? null
          : guesses.reduce((a, b) => a.rank < b.rank ? a : b);
      final bestLabel = bestGuess?.band.label ?? 'No guesses';
      return "Didn't get it — best: $bestLabel";
    }

    String base;
    if (parGuesses != null) {
      final budgetStr = maxGuesses != null ? '$n/$maxGuesses guesses' : '$n guesses';
      final delta = (n + hintsUsed) - parGuesses!;
      final parStr = delta == 0 ? 'Par' : (delta > 0 ? 'Par +$delta' : 'Par $delta');
      base = '$budgetStr · $parStr';
    } else {
      base = '$n guess${n == 1 ? '' : 'es'}';
    }

    final rivalAt = rivalSolveAt;
    if (rivalAt != null) {
      if (n < rivalAt) {
        base += ' · Beat the bot';
      } else if (n == rivalAt) {
        base += ' · Tied the bot';
      } else {
        base += ' · Bot won';
      }
    }
    return base;
  }

  @override
  Widget build(BuildContext context) {
    final tokens = Theme.of(context).extension<WarmerTokens>() ?? WarmerTokens.light;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(WarmerSpacing.lg),
      decoration: BoxDecoration(
        color: tokens.canvas,
        borderRadius: BorderRadius.circular(WarmerRadius.lg),
        border: Border.all(color: tokens.hairline, width: 1),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const WarmerWordmark(markSize: 18, fontSize: 15),
          const SizedBox(height: WarmerSpacing.md),
          Text(
            _headline,
            style: Theme.of(context).textTheme.titleSmall?.copyWith(
                  fontWeight: FontWeight.w600,
                  color: tokens.text1,
                ),
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              for (var i = 0; i < guesses.length; i++)
                Container(
                  width: 16,
                  height: 16,
                  margin: const EdgeInsets.only(right: WarmerSpacing.xs),
                  decoration: BoxDecoration(
                    color: i == guesses.length - 1
                        ? (won ? tokens.accent : tokens.text3)
                        : heatForBand(context, guesses[i].band).base,
                    borderRadius: BorderRadius.circular(5),
                  ),
                  child: i == guesses.length - 1 && won
                      ? Center(
                          child: Container(
                            width: 4,
                            height: 4,
                            decoration: BoxDecoration(
                              color: tokens.accentInk,
                              shape: BoxShape.circle,
                            ),
                          ),
                        )
                      : null,
                ),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            _resultLine,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(color: tokens.text2),
          ),
          if (won && currentStreak > 1) ...[
            const SizedBox(height: 2),
            Text(
              '🔥 $currentStreak day streak',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(color: tokens.text2),
            ),
          ],
          const SizedBox(height: WarmerSpacing.md),
          Text(
            'playwarmer.vercel.app',
            style: Theme.of(context)
                .textTheme
                .labelSmall
                ?.copyWith(color: tokens.accentText),
          ),
        ],
      ),
    );
  }
}
