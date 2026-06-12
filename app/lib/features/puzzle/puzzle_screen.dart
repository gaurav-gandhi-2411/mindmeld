import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:mindmeld/ads/rewarded_ad_service.dart';
import 'package:mindmeld/core/config.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/payload_client.dart';
import 'package:mindmeld/core/payload_codec.dart';
import 'package:mindmeld/core/persistence.dart';
import 'package:mindmeld/iap/entitlements.dart';
import 'package:mindmeld/iap/revenuecat_gateway.dart';
import 'package:mindmeld/stubs/analytics_stub.dart';
import 'package:mindmeld/stubs/rewarded_ad_stub.dart';

import 'guess_tile.dart';

/// Minimum guesses before the "give up" option is unlocked.
const int _giveUpMinGuesses = 30;

/// Main puzzle screen: guess input, history, hints, give-up.
class PuzzleScreen extends StatefulWidget {
  const PuzzleScreen({
    super.key,
    required this.lang,
    required this.date,
    required this.onWin,
    this.payloadClient,
    this.adStub,
    this.hintGate,
    this.iapGateway,
  });

  final String lang;
  final String date;
  final VoidCallback onWin;

  /// Optional override for the payload client (used in tests/integration tests).
  /// When null, a default [PayloadClient] is constructed (production behaviour).
  final PayloadClient? payloadClient;

  /// Optional override for the rewarded-ad stub (used in tests).
  ///
  /// When null, a default [RewardedAdStub] is used (3-second simulated delay).
  /// Pass a stub with [simulatedDelay] of [Duration.zero] in widget tests.
  ///
  /// When [hintGate] is also provided, [adStub] is ignored; [hintGate] takes
  /// precedence. Use [hintGate] for full gate injection in new tests.
  final RewardedAdStub? adStub;

  /// Optional override for the hint gate (used in tests).
  ///
  /// When non-null, this gate is used directly instead of calling
  /// [buildHintGate]. Allows tests to inject [AdMobRewardedGate] with a
  /// fake [AdLoader] without touching dart-defines.
  final HintGate? hintGate;

  /// Optional IAP gateway override (used in tests).
  ///
  /// When non-null, entitlements are fetched from this gateway instead of
  /// building one from [AppConfig]. Allows tests to grant removeAds without
  /// touching dart-defines.
  final IapGateway? iapGateway;

  @override
  State<PuzzleScreen> createState() => _PuzzleScreenState();
}

class _PuzzleScreenState extends State<PuzzleScreen> {
  final _controller = TextEditingController();
  final _focusNode = FocusNode();
  late final PayloadClient _client;
  late final HintGate _hintGate;
  late final IapGateway _iapGateway;
  Entitlements _entitlements = Entitlements.empty;

  @override
  void initState() {
    super.initState();
    _client = widget.payloadClient ?? PayloadClient();
    // Resolve the hint gate: explicit hintGate > buildHintGate(adStub).
    _hintGate = widget.hintGate ?? buildHintGate(adStub: widget.adStub);
    _iapGateway = widget.iapGateway ?? buildIapGateway();
    _load();
  }

  DailyPayload? _payload;
  DayState? _dayState;
  String? _inputError;
  bool _loading = true;
  String? _loadError;
  bool _showingAd = false;

  AnalyticsStub get _analytics =>
      AnalyticsStub(AppPersistence.instance);

  Future<void> _load() async {
    try {
      // Fetch payload and entitlements concurrently.
      final payloadFuture = _client.fetch(widget.lang, widget.date);
      final entitlementsFuture = _iapGateway.current();
      final payloadResult = await payloadFuture;
      final entitlements = await entitlementsFuture;
      final existing = await AppPersistence.instance
          .loadDayState(widget.date, widget.lang);
      if (mounted) {
        setState(() {
          _payload = payloadResult.payload;
          _entitlements = entitlements;
          _dayState = existing ??
              DayState(
                date: widget.date,
                lang: widget.lang,
                guesses: [],
                hintsUsed: 0,
                won: false,
                gaveUp: false,
              );
          _loading = false;
        });

        // If the puzzle was already won in a previous session (e.g. the app was
        // restarted after winning), route the shell back to the win screen so the
        // player sees their result instead of a locked-input puzzle screen.
        if (existing != null && existing.won) {
          // Schedule for next frame so the parent shell's setState is not called
          // synchronously inside a build/setState cycle.
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (mounted) widget.onWin();
          });
        }
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _loadError = e.toString();
          _loading = false;
        });
      }
    }
  }

  Future<void> _submitGuess() async {
    final raw = _controller.text.trim().toLowerCase();
    if (raw.isEmpty) return;

    final payload = _payload!;
    final state = _dayState!;

    if (state.isFinished) return;

    // Duplicate check
    if (state.guesses.any((g) => g.word == raw)) {
      setState(() => _inputError = 'Already guessed "$raw"');
      return;
    }

    // Vocab lookup
    final entry = PayloadCodec.lookupWord(raw, payload);
    if (entry == null) {
      setState(() => _inputError = 'Not in word list');
      return;
    }

    final band = bandForRank(entry.rank, payload.n);
    final guess = Guess(
      word: raw,
      rank: entry.rank,
      similarity: entry.similarity,
      band: band,
    );

    final newGuesses = [...state.guesses, guess];
    final won = entry.rank == 1;

    final newState = state.copyWith(
      guesses: newGuesses,
      won: won,
    );

    await AppPersistence.instance.saveDayState(newState);
    await _analytics.logEvent(AnalyticsEvent.guessMade, {
      'lang': widget.lang,
      'rank': entry.rank,
      'guess_number': newGuesses.length,
    });

    if (won) {
      await AppPersistence.instance.recordWin(
        lang: widget.lang,
        guessCount: newGuesses.length,
        today: DateTime.parse(widget.date),
      );
      await _analytics.logEvent(AnalyticsEvent.win, {
        'lang': widget.lang,
        'guess_count': newGuesses.length,
      });
    }

    setState(() {
      _dayState = newState;
      _inputError = null;
      _controller.clear();
    });

    if (won) {
      // Brief delay so the user sees the win flash before navigating.
      await Future<void>.delayed(const Duration(milliseconds: 600));
      widget.onWin();
    }
  }

  Future<void> _useHint() async {
    final payload = _payload!;
    final state = _dayState!;
    final hintsAvailable = payload.hints;

    // Guard: no more payload hints left.
    if (state.hintsUsed >= hintsAvailable.length) return;

    // Guard: daily frequency cap — product rule, applies in all modes.
    if (state.revealedHints.length >= AppConfig.maxHintsPerDay) return;

    if (_showingAd) return;
    setState(() => _showingAd = true);

    // removeAds entitlement: skip the ad modal entirely — grant hint instantly
    // (still subject to the daily cap above).
    final HintGateResult result;
    if (_entitlements.removeAds) {
      result = const HintGateResult(granted: true, fallback: true);
    } else {
      result = await _hintGate.requestHint(context);
    }

    setState(() => _showingAd = false);

    if (!result.granted) return;

    final hint = hintsAvailable[state.hintsUsed];
    final newRevealedHints = [
      ...state.revealedHints,
      RevealedHint(rank: hint.rank, word: hint.word),
    ];
    final newState = state.copyWith(
      hintsUsed: state.hintsUsed + 1,
      revealedHints: newRevealedHints,
    );

    await AppPersistence.instance.saveDayState(newState);
    await _analytics.logEvent(AnalyticsEvent.hintUsed, {
      'lang': widget.lang,
      'hint_index': state.hintsUsed,
      'hint_rank': hint.rank,
    });
    await _analytics.logEvent(AnalyticsEvent.adWatched, {
      'fallback': result.fallback,
      'lang': widget.lang,
      'day': widget.date,
    });

    if (mounted) {
      setState(() => _dayState = newState);
    }
  }

  Future<void> _giveUp() async {
    final state = _dayState!;
    final payload = _payload!;
    final secret = PayloadCodec.decodeSecret(payload);

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Give up?'),
        content: Text(
          'You need at least $_giveUpMinGuesses guesses before giving up. '
          'You have ${state.guesses.length}.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Keep trying'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Give up'),
          ),
        ],
      ),
    );

    if (confirmed != true) return;

    final newState = state.copyWith(gaveUp: true);
    await AppPersistence.instance.saveDayState(newState);
    await AppPersistence.instance.recordLoss(lang: widget.lang);

    if (mounted) {
      setState(() => _dayState = newState);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('The word was: $secret'),
          duration: const Duration(seconds: 10),
        ),
      );
    }
  }

  List<Guess> get _sortedGuesses {
    final guesses = List<Guess>.from(_dayState?.guesses ?? []);
    guesses.sort((a, b) => a.rank.compareTo(b.rank));
    return guesses;
  }

  String _formatDate() {
    try {
      final dt = DateTime.parse(widget.date);
      return DateFormat('MMM d, yyyy').format(dt);
    } catch (_) {
      return widget.date;
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }

    if (_loadError != null) {
      return Scaffold(
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Text('Failed to load puzzle: $_loadError'),
          ),
        ),
      );
    }

    final state = _dayState!;
    final payload = _payload!;
    final sorted = _sortedGuesses;
    final latestGuess = state.guesses.isEmpty ? null : state.guesses.last;
    final canGiveUp = state.guesses.length >= _giveUpMinGuesses;
    // Frequency cap: max [AppConfig.maxHintsPerDay] revealed hints per day.
    // This is a product rule — applies in stub and real-AdMob modes alike.
    final dailyCapReached =
        state.revealedHints.length >= AppConfig.maxHintsPerDay;

    // The displayed count is the effective remaining: bounded by both the
    // payload's hint supply and the daily cap, so the label never promises
    // more hints than the cap will allow.
    final hintsLeft = math.min(
      payload.hints.length - state.hintsUsed,
      AppConfig.maxHintsPerDay - state.revealedHints.length,
    );

    // Pinned hints sorted by rank ascending (rank 1 = secret = closest,
    // so lowest rank first gives the most-useful hint at the top).
    final pinnedHints = List<RevealedHint>.from(state.revealedHints)
      ..sort((a, b) => a.rank.compareTo(b.rank));

    return Scaffold(
      appBar: AppBar(
        title: Column(
          children: [
            const Text('Mindmeld'),
            Text(
              '${_formatDate()}  ·  ${widget.lang == 'hi-en' ? 'Hinglish' : 'English'}',
              style: Theme.of(context).textTheme.labelSmall,
            ),
          ],
        ),
        centerTitle: true,
      ),
      body: Column(
        children: [
          // Guess input
          if (!state.isFinished)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _controller,
                      focusNode: _focusNode,
                      decoration: InputDecoration(
                        hintText: 'Enter a word…',
                        errorText: _inputError,
                        border: const OutlineInputBorder(),
                        isDense: true,
                      ),
                      textInputAction: TextInputAction.done,
                      onSubmitted: (_) => _submitGuess(),
                    ),
                  ),
                  const SizedBox(width: 8),
                  FilledButton(
                    onPressed: _submitGuess,
                    child: const Text('Guess'),
                  ),
                ],
              ),
            ),

          // Hint + give-up row
          if (!state.isFinished)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: Row(
                children: [
                  OutlinedButton.icon(
                    onPressed: hintsLeft > 0 && !_showingAd && !dailyCapReached
                        ? _useHint
                        : null,
                    icon: const Icon(Icons.lightbulb_outline, size: 18),
                    label: Text(
                      dailyCapReached
                          ? 'No more hints today'
                          : hintsLeft > 0
                              ? 'Hint ($hintsLeft left)'
                              : 'No hints left',
                    ),
                  ),
                  const SizedBox(width: 8),
                  if (canGiveUp)
                    TextButton(
                      onPressed: _giveUp,
                      style: TextButton.styleFrom(
                        foregroundColor:
                            Theme.of(context).colorScheme.error,
                      ),
                      child: const Text('Give up'),
                    ),
                ],
              ),
            ),

          // Guess count
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Row(
              children: [
                Text(
                  '${state.guesses.length} guess${state.guesses.length == 1 ? '' : 'es'}',
                  style: Theme.of(context).textTheme.labelMedium,
                ),
                const Spacer(),
                if (latestGuess != null)
                  Text(
                    'Latest: ${latestGuess.word} (#${latestGuess.rank})',
                    style: Theme.of(context).textTheme.labelMedium,
                  ),
              ],
            ),
          ),

          const Divider(),

          // Combined scrollable: pinned hint tiles first, then guess history.
          Expanded(
            child: ListView.builder(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              // Header items: hint section label + one HintTile per revealed hint
              // + separator divider; guess tiles follow immediately after.
              itemCount: (pinnedHints.isEmpty ? 0 : pinnedHints.length + 2) +
                  sorted.length,
              itemBuilder: (ctx, i) {
                // ── Pinned-hints header ─────────────────────────────────────
                if (pinnedHints.isNotEmpty) {
                  // Index 0: section label
                  if (i == 0) {
                    return Padding(
                      padding: const EdgeInsets.only(top: 4, bottom: 2),
                      child: Text(
                        'Hints revealed',
                        style: Theme.of(ctx).textTheme.labelSmall?.copyWith(
                              fontWeight: FontWeight.bold,
                            ),
                      ),
                    );
                  }
                  // Indices 1 … pinnedHints.length: one HintTile each.
                  if (i <= pinnedHints.length) {
                    return HintTile(
                      hint: pinnedHints[i - 1],
                      vocabSize: payload.n,
                    );
                  }
                  // Index pinnedHints.length + 1: separator divider.
                  if (i == pinnedHints.length + 1) {
                    return const Divider(height: 12);
                  }
                }
                // ── Guess tiles ──────────────────────────────────────────────
                final guessOffset = pinnedHints.isEmpty ? 0 : pinnedHints.length + 2;
                final g = sorted[i - guessOffset];
                final isLatest = latestGuess != null && g.word == latestGuess.word;
                return GuessTile(
                  guess: g,
                  vocabSize: payload.n,
                  isHighlighted: isLatest,
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}
