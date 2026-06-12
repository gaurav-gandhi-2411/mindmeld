import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

const String _kOnboardingDone = 'onboarding_done';

/// Returns whether the user has completed onboarding.
Future<bool> hasSeenOnboarding() async {
  final prefs = await SharedPreferences.getInstance();
  return prefs.getBool(_kOnboardingDone) ?? false;
}

/// Mark onboarding as complete.
Future<void> markOnboardingDone() async {
  final prefs = await SharedPreferences.getInstance();
  await prefs.setBool(_kOnboardingDone, true);
}

/// 4-page onboarding flow shown on first launch.
///
/// Pages:
///   1. What is Mindmeld?
///   2. How guessing works (semantic similarity)
///   3. Temperature bands explained
///   4. Hints and streaks
class OnboardingScreen extends StatefulWidget {
  const OnboardingScreen({super.key, required this.onDone});

  final VoidCallback onDone;

  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<OnboardingScreen> {
  final _controller = PageController();
  int _page = 0;

  static const _pages = [
    _OnboardingPage(
      icon: Icons.psychology,
      title: 'Welcome to Mindmeld',
      body: 'Every day there is a secret word. Your goal is to guess it using '
          'semantic similarity — the AI ranks how close each guess is.',
    ),
    _OnboardingPage(
      icon: Icons.bar_chart,
      title: 'Guessing works by meaning',
      body: 'Enter any word from the vocabulary. You\'ll see its rank '
          '(#1 = secret word) and a similarity score. '
          'Words that mean similar things rank closer!',
    ),
    _OnboardingPage(
      icon: Icons.thermostat,
      title: 'Temperature bands',
      body: '🟥 Scorching — very close\n'
          '🟧 Hot — nearby\n'
          '🟨 Warm — in the neighbourhood\n'
          '🟩 Cold — far away\n'
          '🟦 Freezing — very far\n\n'
          'Work your way up to Scorching!',
    ),
    _OnboardingPage(
      icon: Icons.lightbulb_outline,
      title: 'Hints & Streaks',
      body: 'Stuck? Use a hint — it reveals a word at a known rank. '
          'Watch a short ad to unlock each hint.\n\n'
          'Play every day to build your streak. '
          'Good luck! 🧠',
    ),
  ];

  void _next() {
    if (_page < _pages.length - 1) {
      _controller.nextPage(
        duration: const Duration(milliseconds: 300),
        curve: Curves.easeInOut,
      );
    } else {
      _finish();
    }
  }

  Future<void> _finish() async {
    await markOnboardingDone();
    widget.onDone();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: PageView.builder(
                controller: _controller,
                itemCount: _pages.length,
                onPageChanged: (i) => setState(() => _page = i),
                itemBuilder: (_, i) => _pages[i],
              ),
            ),
            // Page dots
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: List.generate(
                _pages.length,
                (i) => AnimatedContainer(
                  duration: const Duration(milliseconds: 200),
                  margin: const EdgeInsets.symmetric(horizontal: 4, vertical: 12),
                  width: i == _page ? 20 : 8,
                  height: 8,
                  decoration: BoxDecoration(
                    color: i == _page
                        ? Theme.of(context).colorScheme.primary
                        : Theme.of(context).colorScheme.outlineVariant,
                    borderRadius: BorderRadius.circular(4),
                  ),
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
              child: Row(
                children: [
                  if (_page > 0)
                    TextButton(
                      onPressed: () => _controller.previousPage(
                        duration: const Duration(milliseconds: 300),
                        curve: Curves.easeInOut,
                      ),
                      child: const Text('Back'),
                    ),
                  const Spacer(),
                  TextButton(
                    onPressed: _finish,
                    child: const Text('Skip'),
                  ),
                  const SizedBox(width: 8),
                  FilledButton(
                    onPressed: _next,
                    child: Text(
                      _page == _pages.length - 1 ? 'Start playing!' : 'Next',
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _OnboardingPage extends StatelessWidget {
  const _OnboardingPage({
    required this.icon,
    required this.title,
    required this.body,
  });

  final IconData icon;
  final String title;
  final String body;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(32),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(icon, size: 80, color: Theme.of(context).colorScheme.primary),
          const SizedBox(height: 32),
          Text(
            title,
            style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                  fontWeight: FontWeight.bold,
                ),
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 16),
          Text(
            body,
            style: Theme.of(context).textTheme.bodyLarge,
            textAlign: TextAlign.center,
          ),
        ],
      ),
    );
  }
}
