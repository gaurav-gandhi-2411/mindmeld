import 'dart:ui';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_crashlytics/firebase_crashlytics.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:google_mobile_ads/google_mobile_ads.dart';
import 'package:intl/intl.dart';
import 'package:mindmeld/ads/consent_manager.dart';
import 'package:mindmeld/analytics/firebase_exporter.dart';
import 'package:mindmeld/core/config.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/payload_client.dart';
import 'package:mindmeld/core/payload_codec.dart';
import 'package:mindmeld/core/persistence.dart';
import 'package:mindmeld/features/onboarding/onboarding_screen.dart';
import 'package:mindmeld/features/puzzle/puzzle_screen.dart';
import 'package:mindmeld/features/settings/settings_screen.dart';
import 'package:mindmeld/features/stats/stats_screen.dart';
import 'package:mindmeld/features/win/win_screen.dart';

/// Test-only overrides for the app shell.
///
/// Pass a non-null instance to [MindmeldApp] to:
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
}

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await AppPersistence.instance.init(); // production: uses platform default path

  // Firebase init + Crashlytics error hooks — only when analyticsEnabled.
  // When analyticsEnabled=false (the default) zero Firebase calls are made,
  // keeping cold-start fast for non-monetised builds.
  if (AppConfig.analyticsEnabled) {
    await Firebase.initializeApp();

    // Wire Flutter framework errors to Crashlytics.
    FlutterError.onError = FirebaseCrashlytics.instance.recordFlutterFatalError;

    // Wire platform/isolate errors (non-Flutter zone) to Crashlytics.
    PlatformDispatcher.instance.onError = (error, stack) {
      FirebaseCrashlytics.instance.recordError(error, stack, fatal: true);
      return true;
    };
  }

  // Build the exporter (FirebaseExporter or _NoOpExporter depending on flag).
  final exporter = buildAnalyticsExporter();
  await exporter.init(); // flush any queued events from previous sessions.

  // AdMob initialisation and UMP consent — only executed in monetised builds.
  // When adsEnabled=false (the default), zero ad/UMP code paths execute.
  if (AppConfig.adsEnabled) {
    await MobileAds.instance.initialize();
    await ConsentManager.gatherConsent();
  }

  runApp(MindmeldApp(exporter: exporter));
}

class MindmeldApp extends StatelessWidget {
  const MindmeldApp({super.key, this.overrides, this.exporter});

  /// Test-only overrides; null in production.
  final AppOverrides? overrides;

  /// Analytics exporter — passed down so [_AppShell] can call [onResume].
  ///
  /// When null a default [_NoOpExporter] is constructed (used in widget tests
  /// that call [MindmeldApp] directly without going through [main]).
  final AnalyticsExporter? exporter;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Mindmeld',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorSchemeSeed: const Color(0xFF6200EE),
        useMaterial3: true,
        brightness: Brightness.light,
      ),
      darkTheme: ThemeData(
        colorSchemeSeed: const Color(0xFF6200EE),
        useMaterial3: true,
        brightness: Brightness.dark,
      ),
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
  bool _showOnboarding = false;
  String _lang = 'en';
  int _navIndex = 0;
  bool _won = false;
  String? _wonSecret;

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

    final seen = await hasSeenOnboarding();
    // Honour the lang override so integration tests don't depend on whatever
    // lang was last written to SharedPreferences by a previous test.
    final lang =
        widget.overrides?.lang ?? await loadSelectedLang();
    if (mounted) {
      setState(() {
        // If skipOnboarding override is set, always bypass the gate.
        _showOnboarding = !seen && !(widget.overrides?.skipOnboarding ?? false);
        _lang = lang;
        _initialised = true;
      });
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
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _won = true;
          _wonSecret = '(loading…)';
        });
      }
    }
  }

  void _onLangChanged(String lang) {
    setState(() {
      _lang = lang;
      _won = false;
      _wonSecret = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    if (!_initialised) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }

    if (_showOnboarding) {
      return OnboardingScreen(
        onDone: () => setState(() => _showOnboarding = false),
      );
    }

    if (_won) {
      return _WinShell(
        lang: _lang,
        date: _today,
        secret: _wonSecret ?? '',
        onClose: () => setState(() {
          _won = false;
          _wonSecret = null;
        }),
      );
    }

    return Scaffold(
      body: IndexedStack(
        index: _navIndex,
        children: [
          PuzzleScreen(
            lang: _lang,
            date: _today,
            onWin: _handleWin,
            payloadClient: widget.overrides?.payloadClient,
          ),
          StatsScreen(lang: _lang),
          SettingsScreen(
            currentLang: _lang,
            onLangChanged: _onLangChanged,
            onReplayOnboarding: () => setState(() => _showOnboarding = true),
          ),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _navIndex,
        onDestinationSelected: (i) => setState(() => _navIndex = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.grid_view), label: 'Puzzle'),
          NavigationDestination(icon: Icon(Icons.bar_chart), label: 'Stats'),
          NavigationDestination(icon: Icon(Icons.settings), label: 'Settings'),
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
  });

  final String lang;
  final String date;
  final String secret;
  final VoidCallback onClose;

  @override
  State<_WinShell> createState() => _WinShellState();
}

class _WinShellState extends State<_WinShell> {
  List<Guess>? _guesses;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final state = await AppPersistence.instance
        .loadDayState(widget.date, widget.lang);
    if (mounted) {
      setState(() => _guesses = state?.guesses ?? []);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_guesses == null) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    return WinScreen(
      secret: widget.secret,
      guesses: _guesses!,
      lang: widget.lang,
      date: widget.date,
      onPlayAgain: widget.onClose,
    );
  }
}
