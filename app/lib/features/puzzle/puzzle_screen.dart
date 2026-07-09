import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:mindmeld/ads/rewarded_ad_service.dart';
import 'package:mindmeld/analytics/firebase_exporter.dart';
import 'package:mindmeld/core/config.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/payload_client.dart';
import 'package:mindmeld/core/payload_codec.dart';
import 'package:mindmeld/core/persistence.dart';
import 'package:mindmeld/core/rival_state.dart';
import 'package:mindmeld/iap/entitlements.dart';
import 'package:mindmeld/iap/revenuecat_gateway.dart';
import 'package:mindmeld/stubs/analytics_stub.dart';
import 'package:mindmeld/stubs/rewarded_ad_stub.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'guess_tile.dart';

/// Minimum guesses before the "give up" option is unlocked.
const int _giveUpMinGuesses = 1;

/// Main puzzle screen: guess input, history, hints, give-up.
class PuzzleScreen extends StatefulWidget {
  const PuzzleScreen({
    super.key,
    required this.lang,
    required this.date,
    required this.onWin,
    required this.onLoss,
    this.payloadClient,
    this.adStub,
    this.hintGate,
    this.iapGateway,
    this.isPractice = false,
    this.exporter,
    this.packId,
    this.packIdx,
    this.packTitle,
  }) : assert(packId == null || packIdx != null,
            'packIdx is required when packId is set');

  final String lang;
  final String date;
  final VoidCallback onWin;

  /// Called when the player exhausts the guess budget or gives up.
  final VoidCallback onLoss;

  /// When true, wins and losses are not recorded to persistent stats.
  final bool isPractice;

  /// Themed-pack id (phase 6c). Non-null puts the screen into "pack mode":
  /// the puzzle is fetched via [PayloadClient.fetchPack], progress is
  /// persisted to the pack_progress store (never day_state/stats — see
  /// [AppPersistence] class doc), and [packIdx]/[packTitle] must also be set.
  final String? packId;

  /// 1-based puzzle index within [packId]'s pack. Required when [packId] is set.
  final int? packIdx;

  /// Themed-pack display name shown in the app bar (phase 6c).
  final String? packTitle;

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

  /// Optional analytics exporter override (used in tests).
  ///
  /// When null, [buildAnalyticsExporter] is called to construct the default
  /// exporter based on the ANALYTICS_ENABLED dart-define flag.
  final AnalyticsExporter? exporter;

  @override
  State<PuzzleScreen> createState() => _PuzzleScreenState();
}

class _PuzzleScreenState extends State<PuzzleScreen> {
  final _controller = TextEditingController();
  final _focusNode = FocusNode();
  late final PayloadClient _client;
  late final HintGate _hintGate;
  late final IapGateway _iapGateway;
  late final AnalyticsExporter _analytics;
  Entitlements _entitlements = Entitlements.empty;

  @override
  void initState() {
    super.initState();
    _client = widget.payloadClient ?? PayloadClient();
    // Resolve the hint gate: explicit hintGate > buildHintGate(adStub).
    _hintGate = widget.hintGate ?? buildHintGate(adStub: widget.adStub);
    _iapGateway = widget.iapGateway ?? buildIapGateway();
    _analytics = widget.exporter ?? buildAnalyticsExporter();
    _load();
    _loadRivalSettings();
  }

  DailyPayload? _payload;
  DayState? _dayState;
  String? _inputError;
  bool _loading = true;
  String? _loadError;
  bool _showingAd = false;
  bool _submitting = false;
  bool _rivalEnabled = true;
  String _rivalTier = 'even';

  /// True when this screen is playing a themed-pack puzzle (phase 6c) rather
  /// than the daily puzzle.
  bool get _isPackMode => widget.packId != null;

  /// True when guess/hint/give-up outcomes must NOT be written to the daily
  /// stats/streak — practice mode and pack mode both qualify. Pack mode
  /// additionally routes state through pack_progress instead of day_state
  /// (see [_loadState]/[_saveState]).
  bool get _skipStatsWrites => widget.isPractice || _isPackMode;

  /// Converts a persisted [PackPuzzleState] into the local [DayState] shape
  /// used by the rest of this widget, keyed by [widget.date] (the caller
  /// passes the pack's synthetic "{packId}-{NNN}" date string).
  DayState _fromPackState(PackPuzzleState p) => DayState(
        date: widget.date,
        lang: p.lang,
        guesses: p.guesses,
        hintsUsed: p.hintsUsed,
        won: p.won,
        gaveUp: p.gaveUp,
        revealedHints: p.revealedHints,
      );

  PackPuzzleState _toPackState(DayState d) => PackPuzzleState(
        packId: widget.packId!,
        idx: widget.packIdx!,
        lang: d.lang,
        guesses: d.guesses,
        hintsUsed: d.hintsUsed,
        won: d.won,
        gaveUp: d.gaveUp,
        revealedHints: d.revealedHints,
      );

  /// Loads persisted state via the pack_progress path in pack mode, or
  /// day_state otherwise.
  Future<DayState?> _loadState() async {
    if (_isPackMode) {
      final packState = await AppPersistence.instance
          .loadPackState(widget.packId!, widget.packIdx!, widget.lang);
      return packState == null ? null : _fromPackState(packState);
    }
    return AppPersistence.instance.loadDayState(widget.date, widget.lang);
  }

  /// Persists [state] via the pack_progress path in pack mode, or day_state
  /// otherwise. CRITICAL INVARIANT: pack mode never calls saveDayState.
  Future<void> _saveState(DayState state) async {
    if (_isPackMode) {
      await AppPersistence.instance.savePackState(_toPackState(state));
    } else {
      await AppPersistence.instance.saveDayState(state);
    }
  }

  Future<void> _load() async {
    try {
      // Fetch payload and entitlements concurrently.
      final payloadFuture = _isPackMode
          ? _client.fetchPack(widget.packId!, widget.packIdx!, widget.lang)
          : _client.fetch(widget.lang, widget.date);
      final entitlementsFuture = _iapGateway.current();
      final payloadResult = await payloadFuture;
      final entitlements = await entitlementsFuture;
      final existing = await _loadState();
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

        // Already-finished-state redirect — pack mode only. Pack mode is a
        // pushed route (Navigator.push per puzzle) with no remount loop, and
        // its puzzle-list flow relies on this redirect to skip straight past
        // an already-solved pack puzzle. Daily mode must NOT redirect here:
        // the app shell (_AppShellState._deriveResultRouting) is the single
        // owner of daily win/loss routing, derived from this same recorded
        // day_state. If this fired in daily mode too, every remount of this
        // widget (e.g. tapping Back on the win screen swaps this widget back
        // into the index-0 IndexedStack slot) would re-fire onWin/onLoss and
        // immediately bounce the player back to the result screen, making
        // the bottom nav unreachable for the rest of the day. Gating this to
        // pack mode keeps onWin/onLoss idempotent per completion in daily
        // mode — they only fire from the active-transition paths below
        // (_submitGuess / _useHint / _giveUp).
        if (_isPackMode && existing != null && existing.won) {
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (mounted) widget.onWin();
          });
        } else if (_isPackMode &&
            existing != null &&
            existing.isFinished &&
            !existing.won) {
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (mounted) widget.onLoss();
          });
        } else if (existing == null && !_skipStatsWrites) {
          // Fresh start — fire puzzle_started and check day-2 return.
          final p = payloadResult.payload;
          await _analytics.logEvent(AnalyticsEvent.puzzleStarted, {
            'lang': widget.lang,
            'day': widget.date,
            'max_guesses': p.maxGuesses ?? 0,
            'par': p.parGuesses ?? 0,
          });
          final yesterdayState = await AppPersistence.instance
              .loadDayState(_yesterday(widget.date), widget.lang);
          if (yesterdayState != null) {
            await _analytics.logEvent(AnalyticsEvent.returningPlayer, {
              'lang': widget.lang,
              'day': widget.date,
              'days_since_last_play': 1,
            });
          }
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

  Future<void> _loadRivalSettings() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      if (mounted) {
        setState(() {
          _rivalEnabled = prefs.getBool('rival_enabled') ?? true;
          _rivalTier = prefs.getString('rival_tier') ?? 'even';
        });
      }
    } catch (_) {
      // SharedPreferences not available in test environments without mock setup;
      // silently retain default values (_rivalEnabled=true, _rivalTier='even').
    }
  }

  String _yesterday(String date) {
    final dt = DateTime.parse(date);
    return DateFormat('yyyy-MM-dd').format(dt.subtract(const Duration(days: 1)));
  }

  Future<void> _logRivalOutcome(
    DailyPayload payload,
    List<Guess> guesses,
    int hintsUsed, {
    required bool won,
  }) async {
    final rivalD = payload.rival?.forTier(_rivalTier);
    if (rivalD == null || !_rivalEnabled) return;
    final rivalS = RivalState.fromGuesses(
      guesses: guesses,
      tierData: rivalD,
      playerWon: won,
    );
    final outcomeStr = switch (rivalS.outcome) {
      RivalOutcome.playerWon => 'player_won',
      RivalOutcome.rivalWon => 'rival_won',
      RivalOutcome.tie => 'tie',
      _ => 'unknown',
    };
    await _analytics.logEvent(AnalyticsEvent.rivalOutcome, {
      'lang': widget.lang,
      'day': widget.date,
      'guesses_used': guesses.length + hintsUsed,
      'max_guesses': payload.maxGuesses ?? 0,
      'par': payload.parGuesses ?? 0,
      'outcome': outcomeStr,
      'rival_solve_at': rivalD.solveAt,
    });
  }

  Future<void> _submitGuess() async {
    if (_submitting) return;
    final raw = _controller.text.trim().toLowerCase();
    if (raw.isEmpty) return;
    setState(() => _submitting = true);
    try {
      final payload = _payload!;
      final state = _dayState!;

      if (state.isFinished) return;

      // Vocab lookup first (needed for rank-based duplicate detection).
      final entry = PayloadCodec.lookupWord(raw, payload);
      if (entry == null) {
        setState(() => _inputError = 'Not in word list');
        return;
      }

      // Duplicate check: compare by resolved rank, not raw string.
      // A variant spelling that resolves to the same canonical word (same rank)
      // counts as a duplicate — ranks belong to the canonical word, not the typed
      // variant. This prevents e.g. 'gana' being accepted after 'gaana' was guessed.
      if (state.guesses.any((g) => g.rank == entry.rank)) {
        setState(() => _inputError = 'Already guessed that word');
        return;
      }

      final band = bandForRank(entry.rank, payload.n);
      // word records what the player typed (display fidelity); rank/similarity
      // belong to the canonical word resolved by the lookup.
      final guess = Guess(
        word: raw,
        rank: entry.rank,
        similarity: entry.similarity,
        band: band,
      );

      final newGuesses = [...state.guesses, guess];
      final won = entry.rank == 1;

      // Budget check: effective usage = guesses + hints already used (newState
      // has same hintsUsed as state since this is a guess, not a hint).
      final maxG = _payload!.maxGuesses;
      final budgetExhausted =
          !won && maxG != null && (newGuesses.length + state.hintsUsed) >= maxG;

      final newState = state.copyWith(
        guesses: newGuesses,
        won: won,
        gaveUp: budgetExhausted, // budget exhaustion treated as a loss
      );

      await _saveState(newState);
      await _analytics.logEvent(AnalyticsEvent.guessMade, {
        'lang': widget.lang,
        'rank': entry.rank,
        'guess_number': newGuesses.length,
      });

      if (won && !_skipStatsWrites) {
        await AppPersistence.instance.recordWin(
          lang: widget.lang,
          guessCount: newGuesses.length,
          today: DateTime.parse(widget.date),
        );
        await _analytics.logEvent(AnalyticsEvent.win, {
          'lang': widget.lang,
          'day': widget.date,
          'guesses_used': newGuesses.length + state.hintsUsed,
          'max_guesses': payload.maxGuesses ?? 0,
          'par': payload.parGuesses ?? 0,
        });
        await _logRivalOutcome(payload, newGuesses, state.hintsUsed, won: true);
      }

      if (budgetExhausted && !_skipStatsWrites) {
        await AppPersistence.instance.recordLoss(lang: widget.lang);
        await _analytics.logEvent(AnalyticsEvent.loss, {
          'lang': widget.lang,
          'day': widget.date,
          'guesses_used': newGuesses.length + state.hintsUsed,
          'max_guesses': payload.maxGuesses ?? 0,
          'par': payload.parGuesses ?? 0,
        });
        await _logRivalOutcome(payload, newGuesses, state.hintsUsed, won: false);
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
      } else if (budgetExhausted) {
        await Future<void>.delayed(const Duration(milliseconds: 400));
        widget.onLoss();
      }
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  Future<void> _useHint() async {
    final payload = _payload!;
    final state = _dayState!;

    // Guard: puzzle already over (race condition with UI hide).
    if (state.isFinished) return;

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

    await _saveState(newState);
    await _analytics.logEvent(AnalyticsEvent.hintUsed, {
      'lang': widget.lang,
      'day': widget.date,
      'hint_index': state.hintsUsed,
      'hint_rank': hint.rank,
      'guesses_used': newState.guesses.length + newState.hintsUsed,
      'max_guesses': payload.maxGuesses ?? 0,
      'par': payload.parGuesses ?? 0,
    });
    await _analytics.logEvent(AnalyticsEvent.adWatched, {
      'fallback': result.fallback,
      'lang': widget.lang,
      'day': widget.date,
    });

    if (mounted) {
      setState(() => _dayState = newState);
    }

    // Check if this hint consumed the last budget slot.
    final maxG = payload.maxGuesses;
    if (maxG != null) {
      final effective = newState.guesses.length + newState.hintsUsed;
      if (effective >= maxG) {
        if (!_skipStatsWrites) {
          await AppPersistence.instance.recordLoss(lang: widget.lang);
        }
        final lostState = newState.copyWith(gaveUp: true);
        await _saveState(lostState);
        if (mounted) setState(() => _dayState = lostState);
        await Future<void>.delayed(const Duration(milliseconds: 400));
        if (mounted) widget.onLoss();
      }
    }
  }

  Future<void> _giveUp() async {
    final state = _dayState!;

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Give up?'),
        content: const Text('The word will be revealed. This counts as a loss.'),
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

    final payload = _payload!;
    final newState = state.copyWith(gaveUp: true);
    await _saveState(newState);
    if (!_skipStatsWrites) {
      await AppPersistence.instance.recordLoss(lang: widget.lang);
      await _analytics.logEvent(AnalyticsEvent.loss, {
        'lang': widget.lang,
        'day': widget.date,
        'guesses_used': state.guesses.length + state.hintsUsed,
        'max_guesses': payload.maxGuesses ?? 0,
        'par': payload.parGuesses ?? 0,
        'gave_up': 1,
      });
      await _logRivalOutcome(payload, state.guesses, state.hintsUsed, won: false);
    }
    if (mounted) {
      setState(() => _dayState = newState);
    }
    widget.onLoss();
  }

  RivalState? get _rivalState {
    final payload = _payload;
    final state = _dayState;
    if (payload == null || state == null || !_rivalEnabled) return null;
    final rivalData = payload.rival;
    if (rivalData == null) return null;
    return RivalState.fromGuesses(
      guesses: state.guesses,
      tierData: rivalData.forTier(_rivalTier),
      playerWon: state.won,
    );
  }

  List<Guess> get _sortedGuesses {
    final guesses = List<Guess>.from(_dayState?.guesses ?? []);
    guesses.sort((a, b) => a.rank.compareTo(b.rank));
    return guesses;
  }

  Widget _buildRivalStrip(RivalState rivalState, BuildContext context) {
    final guessCount = rivalState.guessCount;
    final solveAt = rivalState.solveAt;

    String rivalLabel;
    if (rivalState.rivalSolved) {
      rivalLabel = 'Rival finished in $solveAt ${solveAt == 1 ? 'guess' : 'guesses'}';
    } else if (guessCount == 0) {
      rivalLabel = 'Rival ready…';
    } else {
      final step = rivalState.rivalCurrentStep;
      final label = step?.temperatureBand.label ?? '';
      final emoji = step?.temperatureBand.emoji ?? '';
      rivalLabel = 'Rival: $emoji $label (best #${rivalState.rivalBestRank})';
    }

    final outcomeEmoji = switch (rivalState.outcome) {
      RivalOutcome.playerWon => ' 🏆',
      RivalOutcome.rivalWon => ' 🤖',
      RivalOutcome.tie => ' 🤝',
      RivalOutcome.racing => '',
    };

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      color: Theme.of(context).colorScheme.surfaceContainerHighest,
      child: Row(
        children: [
          const Text('🤖', style: TextStyle(fontSize: 14)),
          const SizedBox(width: 6),
          Expanded(
            child: Text(rivalLabel,
                style: Theme.of(context).textTheme.bodySmall),
          ),
          Text(
            'You $guessCount · Bot ${rivalState.rivalSolved ? solveAt : '?'}$outcomeEmoji',
            style: Theme.of(context).textTheme.labelSmall,
          ),
        ],
      ),
    );
  }

  Widget _buildProgressRow(DailyPayload payload, DayState state, BuildContext context) {
    if (state.guesses.isEmpty) return const SizedBox.shrink();

    final bestGuess =
        state.guesses.reduce((a, b) => a.rank < b.rank ? a : b);
    final percentile = ((1.0 - bestGuess.rank / payload.n) * 100);
    final pctStr = percentile >= 99.0
        ? percentile.toStringAsFixed(1)
        : percentile.toStringAsFixed(0);

    // Par scoring
    String parStr = '';
    final par = payload.parGuesses;
    if (par != null) {
      final effective = state.guesses.length + state.hintsUsed;
      final delta = effective - par;
      if (delta < 0) {
        parStr = ' · Par $delta 🎯';
      } else if (delta == 0) {
        parStr = ' · Par 🎯';
      } else {
        parStr = ' · Par +$delta';
      }
    }

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 2),
      child: Text(
        'Best: ${bestGuess.band.emoji} #${bestGuess.rank} · Top $pctStr%$parStr',
        style: Theme.of(context).textTheme.labelSmall,
      ),
    );
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
            Text(_isPackMode ? (widget.packTitle ?? 'Mindmeld') : 'Mindmeld'),
            Text(
              _isPackMode
                  ? 'Puzzle #${widget.packIdx}  ·  ${widget.lang == 'hi-en' ? 'Hinglish' : 'English'}'
                  : '${_formatDate()}  ·  ${widget.lang == 'hi-en' ? 'Hinglish' : 'English'}',
              style: Theme.of(context).textTheme.labelSmall,
            ),
          ],
        ),
        centerTitle: true,
      ),
      body: Column(
        children: [
          // Rival strip (shown during active play only, hidden after game over)
          if (_rivalState != null && !state.isFinished)
            _buildRivalStrip(_rivalState!, context),

          // Clue display (Phase 5 — shown from puzzle start until game over)
          if (payload.clue != null && payload.clue!.isNotEmpty && !state.isFinished)
            Container(
              width: double.infinity,
              margin: const EdgeInsets.fromLTRB(16, 8, 16, 0),
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              decoration: BoxDecoration(
                color: Theme.of(context).colorScheme.secondaryContainer,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                '💡 ${payload.clue}',
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: Theme.of(context).colorScheme.onSecondaryContainer,
                      fontStyle: FontStyle.italic,
                    ),
              ),
            ),

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

          // Guess count + progress row
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Row(
              children: [
                Builder(builder: (ctx) {
                  final maxG = payload.maxGuesses;
                  if (maxG != null) {
                    final remaining = maxG - state.guesses.length - state.hintsUsed;
                    return Text(
                      '${state.guesses.length}/$maxG · $remaining left',
                      style: Theme.of(ctx).textTheme.labelMedium?.copyWith(
                            color: remaining <= 3
                                ? Theme.of(ctx).colorScheme.error
                                : null,
                          ),
                    );
                  }
                  return Text(
                    '${state.guesses.length} guess${state.guesses.length == 1 ? '' : 'es'}',
                    style: Theme.of(ctx).textTheme.labelMedium,
                  );
                }),
                const Spacer(),
                if (latestGuess != null)
                  Text(
                    'Latest: ${latestGuess.word} (#${latestGuess.rank})',
                    style: Theme.of(context).textTheme.labelMedium,
                  ),
              ],
            ),
          ),
          _buildProgressRow(payload, state, context),

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
