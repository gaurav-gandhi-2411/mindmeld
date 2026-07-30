import 'dart:async';
import 'dart:ui';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_crashlytics/firebase_crashlytics.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:google_mobile_ads/google_mobile_ads.dart';
import 'package:intl/intl.dart';
import 'package:mindmeld/ads/consent_manager.dart';
import 'package:mindmeld/ads/rewarded_ad_service.dart';
import 'package:mindmeld/analytics/app_check_init.dart';
import 'package:mindmeld/analytics/firebase_exporter.dart';
import 'package:mindmeld/analytics/firebase_web_options.dart';
import 'package:mindmeld/core/config.dart';
import 'package:mindmeld/core/design_tokens.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/payload_client.dart';
import 'package:mindmeld/core/payload_codec.dart';
import 'package:mindmeld/core/persistence.dart';
import 'package:mindmeld/features/archive/archive_screen.dart';
import 'package:mindmeld/features/branding/heat_rings_mark.dart';
import 'package:mindmeld/features/onboarding/first_run.dart';
import 'package:mindmeld/features/onboarding/onboarding_flow.dart';
import 'package:mindmeld/features/onboarding/onboarding_screen.dart';
import 'package:mindmeld/features/puzzle/puzzle_screen.dart';
import 'package:mindmeld/features/settings/settings_screen.dart';
import 'package:mindmeld/features/social/join_flow_screen.dart';
import 'package:mindmeld/features/social/social_home_screen.dart';
import 'package:mindmeld/features/stats/stats_screen.dart';
import 'package:mindmeld/features/win/win_screen.dart';
import 'package:mindmeld/social/social_service.dart';
import 'package:mindmeld/stubs/analytics_stub.dart' show AnalyticsEvent;
// dart.library.js_interop (not dart.library.html): html is FALSE under
// --wasm, which silently selected these stubs in every wasm production
// build — ?reset=1 / ?notif=1 / join links dead on live, all DDC-run tests
// green. js_interop is true for BOTH web compile targets, false on native.
import 'package:mindmeld/core/reset_stub.dart'
    // ignore: uri_does_not_exist
    if (dart.library.js_interop) 'package:mindmeld/core/reset_web.dart';
import 'package:mindmeld/social/deep_link_stub.dart'
    // ignore: uri_does_not_exist
    if (dart.library.js_interop) 'package:mindmeld/social/deep_link_web.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Test-only overrides for the app shell.
///
/// Pass a non-null instance to [WarmerApp] to:
///   - Skip network fetches by injecting a pre-built [PayloadClient]
///     (e.g. one backed by a [FileSystemAssetBundle] or mock HTTP).
///   - Pin the puzzle date so integration tests don't depend on wall-clock time.
///   - Override the language so tests don't depend on SharedPreferences state.
///   - Point persistence at an isolated SQLite file so tests don't share DB state.
///
/// All fields are optional.  The real app always uses `null` overrides so
/// production behaviour is fully preserved by default.
class AppOverrides {
  const AppOverrides({
    this.payloadClient,
    this.fixedDate,
    this.skipOnboarding = false,
    this.lang,
    this.dbPath,
    this.hintGate,
  });

  /// If non-null, [PuzzleScreen] uses this client instead of creating its own.
  final PayloadClient? payloadClient;

  /// If non-null, the app treats this as "today" instead of [DateTime.now()].
  /// Format: "yyyy-MM-dd".
  final String? fixedDate;

  /// When true the onboarding gate is bypassed on first launch.
  final bool skipOnboarding;

  /// If non-null, overrides the language loaded from SharedPreferences.
  ///
  /// Use in integration tests to pin the language without touching prefs state.
  final String? lang;

  /// If non-null, [AppPersistence] is initialised at this path instead of the
  /// platform default documents directory.
  ///
  /// Use in integration tests to get a fresh, isolated SQLite database per test
  /// run so that won/gave-up state from one test cannot bleed into the next.
  final String? dbPath;

  /// If non-null, [PuzzleScreen] uses this hint gate instead of constructing
  /// one from [buildHintGate].
  ///
  /// Use in integration tests to bypass the ad flow entirely (e.g. inject an
  /// instant-grant gate so hints are revealed with zero delay).
  final HintGate? hintGate;
}

/// Pref keys wiped by the `?reset=1` developer hook (web-only, used to
/// simulate a genuinely first-time user for cold-profile verification) — kept
/// as a top-level constant (rather than an inline list literal in [_init])
/// so tests can assert on its membership without needing to exercise the
/// `kIsWeb`-gated call path itself. See reset_hook_test.dart.
const List<String> kResetWipedPrefKeys = [
  kLegacyOnboardingDonePref,
  kOnboardingStateKey,
  kOnboardingGraduatedDateKey,
  'selected_lang',
  'rival_enabled',
  'rival_tier',
];

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await AppPersistence.instance.init(); // production: uses platform default path

  // Build the exporter synchronously (FirebaseExporter or _NoOpExporter
  // depending on the flag) so it's available as a WarmerApp constructor arg —
  // its async .init() (ring-buffer flush) is deferred below, same as Firebase.
  final exporter = buildAnalyticsExporter();

  // Render the first frame BEFORE awaiting Firebase/AppCheck/Crashlytics/ads.
  // Launch-1 wave finding: awaiting Firebase.initializeApp() here (it loads
  // several gstatic.com JS SDK modules on web — firestore/auth/analytics/
  // messaging/app-check, ~211KB combined) previously blocked runApp() itself,
  // directly costing real LCP once ANALYTICS_ENABLED=true started actually
  // exercising this path in production (measured: LCP 2635ms with --wasm
  // alone -> 3240ms once analytics was also enabled and eagerly awaited here
  // — see reports/renderer-decision-2026-07-12.md and
  // docs/known-limitations.md). None of what follows is needed for the first
  // frame — analytics events already queue in the local SQLite ring buffer
  // regardless (see firebase_exporter.dart's own flush-semantics doc), so
  // deferring this costs nothing functionally, only delays when the FIRST
  // flush/AdMob-load/Crashlytics-wiring happens by a few hundred ms.
  runApp(WarmerApp(exporter: exporter));

  // On web, FirebaseOptions must be supplied explicitly (no google-services.json).
  // The placeholder values in firebase_web_options.dart must be replaced before
  // deploying a monetised web build. See docs/firebase-setup.md for instructions.
  // Skip Firebase init if the web config is still placeholder (pre-project-creation).
  final webConfigReady =
      !kIsWeb || firebaseWebOptions.apiKey != 'PLACEHOLDER';

  // Firebase init + Crashlytics error hooks — only when analyticsEnabled.
  // When analyticsEnabled=false (the default) zero Firebase calls are made,
  // keeping cold-start fast for non-monetised builds. Trade-off accepted:
  // a Flutter framework error thrown in the brief window between runApp()
  // and this block completing won't reach Crashlytics (it still surfaces in
  // the browser/device console) — an acceptable gap for a real LCP win on
  // every load, versus the previous zero-gap-but-blocking behaviour.
  if (AppConfig.analyticsEnabled && webConfigReady) {
    await Firebase.initializeApp(
      options: kIsWeb ? firebaseWebOptions : null,
    );
    await ensureAppCheckActivated();

    // Wire Flutter framework errors to Crashlytics.
    FlutterError.onError = FirebaseCrashlytics.instance.recordFlutterFatalError;

    // Wire platform/isolate errors (non-Flutter zone) to Crashlytics.
    PlatformDispatcher.instance.onError = (error, stack) {
      FirebaseCrashlytics.instance.recordError(error, stack, fatal: true);
      return true;
    };
  }

  await exporter.init(); // flush any queued events from previous sessions.

  // AdMob initialisation and UMP consent — only executed in monetised native builds.
  // adsEnabledEffective is false on web (google_mobile_ads is native-only),
  // so zero ad/UMP code paths execute on web regardless of dart-defines.
  if (AppConfig.adsEnabledEffective) {
    await MobileAds.instance.initialize();
    await ConsentManager.gatherConsent();
  }
}

class WarmerApp extends StatelessWidget {
  const WarmerApp({super.key, this.overrides, this.exporter});

  /// Test-only overrides; null in production.
  final AppOverrides? overrides;

  /// Analytics exporter — passed down so [_AppShell] can call [onResume].
  ///
  /// When null a default [_NoOpExporter] is constructed (used in widget tests
  /// that call [WarmerApp] directly without going through [main]).
  final AnalyticsExporter? exporter;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Warmer',
      debugShowCheckedModeBanner: false,
      theme: buildWarmerTheme(Brightness.light),
      darkTheme: buildWarmerTheme(Brightness.dark),
      home: _AppShell(overrides: overrides, exporter: exporter),
    );
  }
}

/// Root shell: handles onboarding gate, language, win routing, and bottom nav.
class _AppShell extends StatefulWidget {
  const _AppShell({this.overrides, this.exporter});

  final AppOverrides? overrides;
  final AnalyticsExporter? exporter;

  @override
  State<_AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<_AppShell> with WidgetsBindingObserver {
  bool _initialised = false;

  /// Legacy static 4-page pager gate (see onboarding_screen.dart) — only ever
  /// set true via Settings > "Replay onboarding" now; never set by [_init].
  bool _showOnboarding = false;

  /// First-session-hook onboarding puzzle gate — resolved by [_init] via
  /// [resolveOnboardingGate].
  bool _showOnboardingPuzzle = false;
  String _lang = 'en';
  int _navIndex = 0;
  bool _won = false;
  String? _wonSecret;
  DailyPayload? _wonPayload;
  bool _lost = false;
  String? _lostSecret;
  DailyPayload? _lostPayload;

  /// Join code extracted from a `/join/{code}` deep link on cold boot, or
  /// null. Consumed (cleared) once [JoinFlowScreen] is dismissed. Shown
  /// AFTER onboarding so a first-time user gets onboard -> name -> join,
  /// while a returning user goes straight to the join confirm screen.
  String? _pendingJoinCode;

  AnalyticsExporter get _exporter =>
      widget.exporter ?? buildAnalyticsExporter();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _init();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      // Flush queued events whenever the app returns to foreground.
      _exporter.onResume();
    }
  }

  Future<void> _init() async {
    // Initialise persistence before reading any state so the DB is open when
    // PuzzleScreen._load() runs.  In tests, dbPath is a per-test temp file so
    // no won/gave-up state bleeds between test runs.
    await AppPersistence.instance.init(
      dbPath: widget.overrides?.dbPath,
    );

    // ?reset=1: wipe all local state to simulate a first-time user (web-only dev hook).
    if (kIsWeb && hasResetParam()) {
      await AppPersistence.instance.clearAll();
      final prefs = await SharedPreferences.getInstance();
      for (final key in kResetWipedPrefKeys) {
        await prefs.remove(key);
      }
      stripResetParam();
    }

    // First-run gate (first-session-hook wave): resolves whether a brand-new
    // player is routed to the onboarding puzzle before today's real daily.
    // See features/onboarding/first_run.dart for the full grandfather-check
    // resolution order (robust against the app's rename/migration history).
    final prefs = await SharedPreferences.getInstance();
    var showOnboardingPuzzle = false;
    var fireOnboardingStarted = false;
    if (widget.overrides?.skipOnboarding ?? false) {
      // Bypass entirely, but still write `done` so downstream logic (the
      // reset hook, a later boot without the override) is consistent with
      // having actually gone through onboarding.
      await markOnboardingPuzzleDone(prefs);
    } else {
      final gate = await resolveOnboardingGate(
        prefs: prefs,
        persistence: AppPersistence.instance,
      );
      showOnboardingPuzzle = gate.showOnboarding;
      fireOnboardingStarted = gate.fireStartedEvent;
    }

    // Honour the lang override so integration tests don't depend on whatever
    // lang was last written to SharedPreferences by a previous test.
    final lang =
        widget.overrides?.lang ?? await loadSelectedLang();

    // Web-only /join/{code} deep link — a no-op stub on native.
    final joinCode = kIsWeb ? extractJoinCode() : null;
    if (joinCode != null) clearJoinPath();

    // ?notif=1: a real click-through from a delivered daily notification
    // (phase 6b). Fire-and-forget so a slow/offline analytics write never
    // delays boot; the app already lands on today's puzzle with no special
    // routing needed.
    if (kIsWeb && hasNotifOpenParam()) {
      unawaited(_exporter.logEvent(AnalyticsEvent.notificationOpened));
      stripNotifOpenParam();
    }

    if (fireOnboardingStarted) {
      unawaited(
        _exporter.logEvent(AnalyticsEvent.onboardingStarted, {'lang': lang}),
      );
    }

    if (mounted) {
      setState(() {
        _showOnboardingPuzzle = showOnboardingPuzzle;
        _lang = lang;
        _pendingJoinCode = joinCode;
        _initialised = true;
      });
    }

    // Restart routing: if today's puzzle was already finished in a previous
    // session, land on the appropriate result shell (win/loss) instead of the
    // live puzzle board. The tabbed nav stays mounted underneath (see build())
    // so this never removes the bottom NavigationBar the way a full-surface
    // swap used to.
    await _deriveResultRouting(lang);
  }

  /// Loads today's persisted day state for [lang] and, if the puzzle is
  /// already finished, transitions `_won`/`_lost` via [_handleWin]/
  /// [_handleLoss]. No-op if the puzzle is still in progress or unstarted.
  ///
  /// Shared by [_init] (cold-start/restart routing) and [_onLangChanged]
  /// (re-deriving routing for the newly selected language).
  Future<void> _deriveResultRouting(String lang) async {
    final state = await AppPersistence.instance.loadDayState(_today, lang);
    if (!mounted || state == null) return;
    if (state.won) {
      await _handleWin();
    } else if (state.isFinished) {
      await _handleLoss();
    }
  }

  /// Returns today's date as "yyyy-MM-dd", honouring [AppOverrides.fixedDate].
  String get _today =>
      widget.overrides?.fixedDate ??
      DateFormat('yyyy-MM-dd').format(DateTime.now());

  Future<void> _handleWin() async {
    try {
      final client = widget.overrides?.payloadClient ?? PayloadClient();
      final result = await client.fetch(_lang, _today);
      final secret = PayloadCodec.decodeSecret(result.payload);
      if (mounted) {
        setState(() {
          _won = true;
          _wonSecret = secret;
          _wonPayload = result.payload;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _won = true;
          _wonSecret = '(loading…)';
          _wonPayload = null;
        });
      }
    }
  }

  Future<void> _handleLoss() async {
    try {
      final client = widget.overrides?.payloadClient ?? PayloadClient();
      final result = await client.fetch(_lang, _today);
      final secret = PayloadCodec.decodeSecret(result.payload);
      if (mounted) {
        setState(() {
          _lost = true;
          _lostSecret = secret;
          _lostPayload = result.payload;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _lost = true;
          _lostSecret = '(loading…)';
          _lostPayload = null;
        });
      }
    }
  }

  Future<void> _onLangChanged(String lang) async {
    setState(() {
      _lang = lang;
      _won = false;
      _wonSecret = null;
      _wonPayload = null;
      _lost = false;
      _lostSecret = null;
      _lostPayload = null;
    });
    // Re-derive routing for the new lang: if its daily is already finished,
    // land on that lang's result screen; otherwise the live puzzle board
    // (already selected by the setState above) is correct as-is.
    await _deriveResultRouting(lang);
  }

  @override
  Widget build(BuildContext context) {
    if (!_initialised) {
      return const Scaffold(
        body: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              HeatRingsMark(size: 72),
              SizedBox(height: WarmerSpacing.xl),
              CircularProgressIndicator(),
            ],
          ),
        ),
      );
    }

    if (_showOnboardingPuzzle) {
      return OnboardingFlow(
        lang: _lang,
        today: _today,
        payloadClient: widget.overrides?.payloadClient,
        exporter: _exporter,
        onLangChanged: (lang) => setState(() => _lang = lang),
        onDone: () {
          setState(() => _showOnboardingPuzzle = false);
          // Fire-and-forget: today's daily may already be finished (unlikely
          // for a brand-new player, but harmless/idempotent if so).
          _deriveResultRouting(_lang);
        },
      );
    }

    if (_showOnboarding) {
      return OnboardingScreen(
        onDone: () => setState(() => _showOnboarding = false),
      );
    }

    if (_pendingJoinCode != null) {
      return JoinFlowScreen(
        code: _pendingJoinCode!,
        date: _today,
        lang: _lang,
        onDone: () => setState(() => _pendingJoinCode = null),
      );
    }

    // The tabbed Scaffold is always the home surface — win/loss never replace
    // it wholesale (that used to strip the NavigationBar, making it
    // unreachable until the flag was cleared). Instead only the index-0
    // IndexedStack child swaps between the result shells and the live puzzle
    // board; NavigationBar stays mounted and reachable in every state.
    final Widget puzzleTab;
    if (_won) {
      puzzleTab = _WinShell(
        lang: _lang,
        date: _today,
        secret: _wonSecret ?? '',
        payload: _wonPayload,
        exporter: _exporter,
        onClose: () => setState(() {
          _won = false;
          _wonSecret = null;
          _wonPayload = null;
        }),
      );
    } else if (_lost) {
      puzzleTab = _LossShell(
        lang: _lang,
        date: _today,
        secret: _lostSecret ?? '',
        payload: _lostPayload,
        exporter: _exporter,
        onClose: () => setState(() {
          _lost = false;
          _lostSecret = null;
          _lostPayload = null;
        }),
      );
    } else {
      puzzleTab = PuzzleScreen(
        key: ValueKey('puzzle-$_lang'),
        lang: _lang,
        date: _today,
        onWin: _handleWin,
        onLoss: _handleLoss,
        payloadClient: widget.overrides?.payloadClient,
        hintGate: widget.overrides?.hintGate,
        exporter: _exporter,
      );
    }

    return Scaffold(
      body: IndexedStack(
        index: _navIndex,
        children: [
          puzzleTab,
          ArchiveScreen(lang: _lang, active: _navIndex == 1),
          StatsScreen(lang: _lang, active: _navIndex == 2),
          SettingsScreen(
            currentLang: _lang,
            onLangChanged: _onLangChanged,
            onReplayOnboarding: () => setState(() => _showOnboarding = true),
          ),
          SocialHomeScreen(date: _today, lang: _lang, active: _navIndex == 4),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _navIndex,
        onDestinationSelected: (i) => setState(() => _navIndex = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.grid_view), label: 'Puzzle'),
          NavigationDestination(
              icon: Icon(Icons.history_edu_outlined), label: 'Practice'),
          NavigationDestination(icon: Icon(Icons.bar_chart), label: 'Stats'),
          NavigationDestination(icon: Icon(Icons.settings), label: 'Settings'),
          NavigationDestination(icon: Icon(Icons.groups), label: 'Friends'),
        ],
      ),
    );
  }
}

/// Intermediate widget that loads day state from persistence for the win screen.
class _WinShell extends StatefulWidget {
  const _WinShell({
    required this.lang,
    required this.date,
    required this.secret,
    required this.onClose,
    this.payload,
    this.exporter,
  });

  final String lang;
  final String date;
  final String secret;
  final VoidCallback onClose;
  final DailyPayload? payload;
  final AnalyticsExporter? exporter;

  @override
  State<_WinShell> createState() => _WinShellState();
}

class _WinShellState extends State<_WinShell> {
  DayState? _dayState;
  PlayerStats? _stats;
  String _rivalTier = 'even';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final state = await AppPersistence.instance
        .loadDayState(widget.date, widget.lang);
    final stats = await AppPersistence.instance.loadStats(widget.lang);
    final prefs = await SharedPreferences.getInstance();
    final rivalTier = prefs.getString('rival_tier') ?? 'even';
    if (mounted) {
      setState(() {
        _dayState = state;
        _stats = stats;
        _rivalTier = rivalTier;
      });
    }

    // Fire-and-forget: writes to every group the player belongs to (no-op
    // for solo/offline/signed-out players — see SocialService.hasLocalIdentity).
    // Never awaited so the win screen never blocks on a network round-trip.
    final par = widget.payload?.parGuesses;
    if (state != null && par != null) {
      final guessesUsed = state.guesses.length + state.hintsUsed;
      buildSocialService().writeResultToAllGroups(
        date: widget.date,
        outcome: 'win',
        guessesUsed: guessesUsed,
        par: par,
        scoreVsPar: guessesUsed - par,
        lang: widget.lang,
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_dayState == null) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    final payload = widget.payload;
    final rivalData = payload?.rival?.forTier(_rivalTier);
    return WinScreen(
      secret: widget.secret,
      guesses: _dayState!.guesses,
      lang: widget.lang,
      date: widget.date,
      onPlayAgain: widget.onClose,
      parGuesses: payload?.parGuesses,
      maxGuesses: payload?.maxGuesses,
      rivalSolveAt: rivalData?.solveAt,
      hintsUsed: _dayState!.hintsUsed,
      currentStreak: _stats?.currentStreak ?? 0,
      exporter: widget.exporter,
      onChallengeGroup: () => Navigator.of(context).push(MaterialPageRoute<void>(
        builder: (_) => SocialHomeScreen(date: widget.date, lang: widget.lang),
      )),
    );
  }
}

/// Intermediate widget that loads day state from persistence for the loss screen.
class _LossShell extends StatefulWidget {
  const _LossShell({
    required this.lang,
    required this.date,
    required this.secret,
    required this.onClose,
    this.payload,
    this.exporter,
  });

  final String lang;
  final String date;
  final String secret;
  final VoidCallback onClose;
  final DailyPayload? payload;
  final AnalyticsExporter? exporter;

  @override
  State<_LossShell> createState() => _LossShellState();
}

class _LossShellState extends State<_LossShell> {
  DayState? _dayState;
  String _rivalTier = 'even';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final state = await AppPersistence.instance
        .loadDayState(widget.date, widget.lang);
    final prefs = await SharedPreferences.getInstance();
    final rivalTier = prefs.getString('rival_tier') ?? 'even';
    if (mounted) {
      setState(() {
        _dayState = state;
        _rivalTier = rivalTier;
      });
    }

    // Fire-and-forget (see _WinShellState._load for the matching win path).
    final par = widget.payload?.parGuesses;
    if (state != null && par != null) {
      final guessesUsed = state.guesses.length + state.hintsUsed;
      buildSocialService().writeResultToAllGroups(
        date: widget.date,
        outcome: 'loss',
        guessesUsed: guessesUsed,
        par: par,
        scoreVsPar: guessesUsed - par,
        lang: widget.lang,
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_dayState == null) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    final payload = widget.payload;
    final rivalData = payload?.rival?.forTier(_rivalTier);
    // Determine display reason: gaveUp=true from explicit give-up; budget
    // exhaustion also sets gaveUp=true in the DB so we use it for both.
    final gaveUp = _dayState!.gaveUp;
    return LossScreen(
      secret: widget.secret,
      guesses: _dayState!.guesses,
      lang: widget.lang,
      date: widget.date,
      onClose: widget.onClose,
      parGuesses: payload?.parGuesses,
      maxGuesses: payload?.maxGuesses,
      rivalSolveAt: rivalData?.solveAt,
      hintsUsed: _dayState!.hintsUsed,
      gaveUp: gaveUp,
      exporter: widget.exporter,
      onChallengeGroup: () => Navigator.of(context).push(MaterialPageRoute<void>(
        builder: (_) => SocialHomeScreen(date: widget.date, lang: widget.lang),
      )),
    );
  }
}
