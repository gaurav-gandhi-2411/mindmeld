/// First-session onboarding puzzle wrapper (first-session-hook wave).
///
/// Hosts the onboarding [PuzzleScreen] (pack mode, see onboarding_config.dart)
/// plus a language toggle, and swaps to a warm "graduation" view on win/loss
/// before handing off to today's real daily. See spec-first-session-hook.md.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:mindmeld/analytics/firebase_exporter.dart';
import 'package:mindmeld/core/design_tokens.dart';
import 'package:mindmeld/core/payload_client.dart';
import 'package:mindmeld/core/payload_codec.dart';
import 'package:mindmeld/core/persistence.dart';
import 'package:mindmeld/features/branding/heat_rings_mark.dart';
import 'package:mindmeld/features/onboarding/first_run.dart';
import 'package:mindmeld/features/onboarding/onboarding_config.dart';
import 'package:mindmeld/features/puzzle/puzzle_screen.dart';
import 'package:mindmeld/features/settings/settings_screen.dart' show setSelectedLang;
import 'package:mindmeld/stubs/analytics_stub.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Outcome of the onboarding puzzle, driving which body [OnboardingFlow]
/// renders: the live puzzle (none), or the graduation view (won/lost).
enum _OnboardingOutcome { none, won, lost }

/// Wraps the onboarding puzzle: language toggle, coaching/example machinery
/// (inside [PuzzleScreen] itself via `isOnboarding: true`), and graduation
/// into today's real daily.
class OnboardingFlow extends StatefulWidget {
  const OnboardingFlow({
    super.key,
    required this.lang,
    required this.today,
    required this.onDone,
    this.onLangChanged,
    this.payloadClient,
    this.exporter,
  });

  /// Initial language — the app shell's currently-selected language. Can be
  /// changed locally via the in-flow toggle before/while playing.
  final String lang;

  /// Today's date (yyyy-MM-dd), honouring [AppOverrides.fixedDate] in tests —
  /// threaded through so the win-path `onboarding_graduated_date` pref is
  /// written against the SAME "today" the daily puzzle uses, not wall-clock
  /// time (which would silently desync in tests and around midnight).
  final String today;

  /// Called once onboarding is fully resolved (win/loss CTA tapped, or
  /// skipped) — the app shell returns to the normal tabbed app.
  final VoidCallback onDone;

  /// Called when the player changes language via the in-flow toggle, so the
  /// app shell's own `_lang` state (used once onboarding hands off to the
  /// daily) stays in sync.
  final ValueChanged<String>? onLangChanged;

  /// Optional payload client override (tests/integration tests).
  final PayloadClient? payloadClient;

  /// Optional analytics exporter override (tests).
  final AnalyticsExporter? exporter;

  @override
  State<OnboardingFlow> createState() => _OnboardingFlowState();
}

class _OnboardingFlowState extends State<OnboardingFlow>
    with WidgetsBindingObserver {
  late String _lang;
  late final AnalyticsExporter _analytics;
  _OnboardingOutcome _outcome = _OnboardingOutcome.none;
  String? _secret;

  @override
  void initState() {
    super.initState();
    _lang = widget.lang;
    _analytics = widget.exporter ?? buildAnalyticsExporter();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  /// Abandon signal: fires while the onboarding puzzle is still unfinished
  /// (never once win/loss has transitioned to the graduation view, and never
  /// after skip/graduate has already handed off). Guess count is read from
  /// persisted pack state rather than tracked locally, since [PuzzleScreen]
  /// owns the live guess list.
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final backgrounded =
        state == AppLifecycleState.paused || state == AppLifecycleState.hidden;
    if (backgrounded && _outcome == _OnboardingOutcome.none) {
      unawaited(_fireAbandoned());
    }
  }

  Future<void> _fireAbandoned() async {
    final packState = await AppPersistence.instance
        .loadPackState(kOnboardingPackId, kOnboardingPackIdx, _lang);
    await _analytics.logEvent(AnalyticsEvent.onboardingAbandoned, {
      'lang': _lang,
      'guess_count': packState?.guesses.length ?? 0,
    });
  }

  Future<void> _setLang(String lang) async {
    if (lang == _lang) return;
    await setSelectedLang(lang);
    if (!mounted) return;
    setState(() => _lang = lang);
    widget.onLangChanged?.call(lang);
  }

  /// Decodes and shows the solved/revealed secret, then swaps to the
  /// graduation view. Shared by the win and loss paths — they differ only in
  /// [outcome] and the copy the graduation view renders for it.
  Future<void> _showGraduationView(_OnboardingOutcome outcome) async {
    final client = widget.payloadClient ?? PayloadClient();
    String secret;
    try {
      final result = await client.fetchOnboarding(_lang);
      secret = PayloadCodec.decodeSecret(result.payload);
    } catch (_) {
      secret = '(loading…)';
    }
    if (!mounted) return;
    setState(() {
      _outcome = outcome;
      _secret = secret;
    });
  }

  Future<void> _handleWin() => _showGraduationView(_OnboardingOutcome.won);

  Future<void> _handleLoss() => _showGraduationView(_OnboardingOutcome.lost);

  /// "Skip to today's puzzle" — graduation without ceremony: no graduation
  /// view, straight to [widget.onDone]. Does NOT set the
  /// `onboarding_graduated_date` pref (that's the win path only — see
  /// puzzle_screen.dart's `_logPuzzleCompleted`).
  Future<void> _handleSkip() async {
    final packState = await AppPersistence.instance
        .loadPackState(kOnboardingPackId, kOnboardingPackIdx, _lang);
    await _analytics.logEvent(AnalyticsEvent.onboardingSkipped, {
      'lang': _lang,
      'guess_count': packState?.guesses.length ?? 0,
    });
    final prefs = await SharedPreferences.getInstance();
    await markOnboardingPuzzleDone(prefs);
    if (!mounted) return;
    widget.onDone();
  }

  /// The graduation view's CTA — marks onboarding `done`, fires
  /// `graduated_to_daily`, and (win path only) stamps `onboarding_graduated_date`
  /// so puzzle_screen.dart's `_logPuzzleCompleted` can close the funnel with
  /// `daily_completed_after_onboarding` once today's real daily is finished.
  Future<void> _graduate() async {
    final from = _outcome == _OnboardingOutcome.won ? 'win' : 'loss';
    final prefs = await SharedPreferences.getInstance();
    await markOnboardingPuzzleDone(prefs);
    await _analytics.logEvent(AnalyticsEvent.graduatedToDaily, {
      'lang': _lang,
      'from': from,
    });
    if (from == 'win') {
      await prefs.setString(kOnboardingGraduatedDateKey, widget.today);
    }
    if (!mounted) return;
    widget.onDone();
  }

  @override
  Widget build(BuildContext context) {
    if (_outcome != _OnboardingOutcome.none) {
      return _GraduationView(
        won: _outcome == _OnboardingOutcome.won,
        secret: _secret ?? '',
        onContinue: _graduate,
      );
    }

    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(
                  horizontal: WarmerSpacing.lg, vertical: WarmerSpacing.sm),
              child: Center(
                child: SegmentedButton<String>(
                  segments: const [
                    ButtonSegment(value: 'en', label: Text('English')),
                    ButtonSegment(value: 'hi-en', label: Text('Hinglish')),
                  ],
                  selected: {_lang},
                  onSelectionChanged: (selection) => _setLang(selection.first),
                ),
              ),
            ),
            Expanded(
              child: PuzzleScreen(
                key: ValueKey('onboarding-$_lang'),
                lang: _lang,
                date: kOnboardingDate,
                packId: kOnboardingPackId,
                packIdx: kOnboardingPackIdx,
                packTitle: 'Learn to play',
                isOnboarding: true,
                payloadClient: widget.payloadClient,
                exporter: _analytics,
                onWin: _handleWin,
                onLoss: _handleLoss,
                onSkip: _handleSkip,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Warm "you've got it!" (or gentle loss) moment shown after the onboarding
/// puzzle resolves, ending in a single CTA into today's real daily.
class _GraduationView extends StatelessWidget {
  const _GraduationView({
    required this.won,
    required this.secret,
    required this.onContinue,
  });

  final bool won;
  final String secret;
  final VoidCallback onContinue;

  @override
  Widget build(BuildContext context) {
    final tokens = Theme.of(context).extension<WarmerTokens>() ?? WarmerTokens.light;
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(WarmerSpacing.xl),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const HeatRingsMark(size: 72),
                const SizedBox(height: WarmerSpacing.xl),
                if (won) ...[
                  Text(
                    "You've got it!",
                    style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                          fontWeight: FontWeight.bold,
                        ),
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: WarmerSpacing.md),
                  Text(
                    secret,
                    style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                          fontWeight: FontWeight.w700,
                          color: tokens.accentText,
                        ),
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: WarmerSpacing.lg),
                  Text(
                    "That's Warmer: closer in meaning = hotter.",
                    style: Theme.of(context)
                        .textTheme
                        .bodyMedium
                        ?.copyWith(color: tokens.text2),
                    textAlign: TextAlign.center,
                  ),
                ] else
                  Text(
                    'The word was "$secret" — no stress, now you know how it works.',
                    style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                          fontWeight: FontWeight.bold,
                        ),
                    textAlign: TextAlign.center,
                  ),
                const SizedBox(height: WarmerSpacing.xxl),
                FilledButton(
                  onPressed: onContinue,
                  child: const Text("Play today's puzzle"),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
