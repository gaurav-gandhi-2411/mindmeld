/// Single source of truth for the onboarding puzzle's identity and coaching
/// copy. See spec-first-session-hook.md.
///
/// The onboarding puzzle rides the existing themed-pack machinery (see
/// puzzle_screen.dart's `_isPackMode`) so its persistence and stats-isolation
/// work unchanged — it is addressed as pack [kOnboardingPackId], puzzle
/// [kOnboardingPackIdx].
library;

import 'package:mindmeld/core/models.dart';

/// Pack id used for the onboarding puzzle.
const String kOnboardingPackId = 'onboarding';

/// 1-based puzzle index within [kOnboardingPackId]'s pack — there is only one.
const int kOnboardingPackIdx = 1;

/// Synthetic date/key for the onboarding puzzle's persisted state, matching
/// the pack-schema "{packId}-{NNN}" convention used elsewhere (e.g.
/// pack_isolation_test.dart's "bollywood-001").
const String kOnboardingDate = 'onboarding-001';

/// Generous guess budget — the onboarding puzzle is deliberately
/// near-impossible to lose (spec: "Guarantee the first win").
const int kOnboardingMaxGuesses = 20;

/// Pre-seeded example guess word shown before the player's first input,
/// keyed by language.
///
/// Provenance: hand-picked (GG review — the onboarding secret/clue/example
/// triple is authored content, see spec-first-session-hook.md) to sit at a
/// clearly Warm/Hot band against the onboarding secret under the production
/// embeddings model. Gated by the generator's onboarding-puzzle authoring
/// tests. 'nadi' (river) is chosen for Hinglish specifically to avoid the
/// known weak titli/khamoshi/rasoi/samunder/bachpan-class pairs called out
/// as a risk in the spec.
const Map<String, String> kOnboardingExampleWord = {
  'en': 'bone',
  'hi-en': 'nadi',
};

/// Returns the pre-seeded example guess word for [lang], defaulting to the
/// English example if [lang] is unrecognised.
String exampleWordFor(String lang) =>
    kOnboardingExampleWord[lang] ?? kOnboardingExampleWord['en']!;

/// Number of the player's own guesses (not counting the pre-seeded example)
/// that receive plain-language coaching copy before feedback reverts to the
/// normal terse band + rank.
const int kOnboardingCoachedGuesses = 3;

/// One-line dismissible nudge shown under the input before the player's
/// first guess.
const String kOnboardingNudge =
    'Type any word related to the clue — Warmer tells you how close you are.';

/// Plain-language coaching line for [band], shown under the latest guess for
/// the first [kOnboardingCoachedGuesses] player guesses only.
///
/// Freezing/cold intentionally share one encouraging line — an early
/// Freezing on the very first guess must not read as failure (spec risk:
/// "over-coaching annoys fast players" is the opposite failure mode, but an
/// early bounce from a discouraging first result is the one this line
/// guards against).
String coachingLineFor(TemperatureBand band) {
  switch (band) {
    case TemperatureBand.freezing:
    case TemperatureBand.cold:
      return "Far off — no problem, that's a clue too. Think about what the "
          'clue is about.';
    case TemperatureBand.warm:
      return 'Warm! Related — try something closer in meaning.';
    case TemperatureBand.hot:
      return 'Hot! Very close now.';
    case TemperatureBand.scorching:
      return "Scorching — you're almost there!";
    case TemperatureBand.win:
      return "You've got it!";
  }
}
