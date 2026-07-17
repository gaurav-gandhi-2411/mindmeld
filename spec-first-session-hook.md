# Warmer — First-Session Hook (onboarding puzzle + light coaching)

## Why this
First impressions decide daily-game retention. A new player currently lands on a cold board + clue + text box and must *infer* the mechanic is semantic closeness (not spelling, not trivia). If their first guess returns "Cold, rank 8607" with no interpretation, they bounce — and that confusion is invisible to them as "this game is frustrating." A first-session WIN is the single strongest predictor of return. This pass makes the first puzzle teach-by-playing, guarantee a win, and graduate cleanly to the real daily — without annoying players who get it instantly.

## Design principles
- **Teach by showing, not telling.** No wall-of-text tutorial. The mechanic is demonstrated through play.
- **Guarantee the first win.** The onboarding puzzle is deliberately easy and near-impossible to lose.
- **Get out of the way fast.** Players who get it in one guess should breeze through; coaching is light, dismissible, and never blocks.
- **Then hand off to the real thing.** After the onboarding win, the player lands on today's actual daily — the habit loop starts immediately.

## The onboarding puzzle
- A **dedicated first puzzle**, separate from the calendar daily — shown once, only to brand-new players (gated on first-run state; never appears again).
- **Deliberately easy:** a very common, concrete secret with a strong, generous clue and a rich semantic neighborhood (so near-guesses read Hot clearly). Curated by hand (GG review — it's the single most important puzzle in the game).
- **Pre-seeded example guess on the board:** one example guess already placed showing a mid/warm result, so the player sees the hot/cold mechanic *before* typing anything. E.g., secret `ocean`, clue "The biggest blue thing on any map," pre-seeded guess `river` → Warm. The player immediately sees "river is warm — so I should think bigger/closer."
- **Generous budget** so a win is essentially guaranteed even with a couple of off guesses.
- **EN + Hinglish** versions (the onboarding puzzle respects the chosen language; Hinglish gets a Hinglish-appropriate easy secret — pick one that plays WELL under the current 0.639 model, avoid the known weak pairs).

## Light coaching (layered on, dismissible)
- **Interpret the rank in plain language on early guesses** (first ~3 guesses of the onboarding puzzle only): translate rank→meaning — "Freezing · unrelated, think about the clue's theme" / "Warm · related, you're on the right track — go closer" / "Scorching · almost there!". After the onboarding puzzle, feedback reverts to the normal terse band + rank.
- **One-line contextual nudges**, not modals: a subtle coach line under the input that updates with progress ("Guess a word related to the clue" → after a warm guess: "Warmer! Try something closer in meaning"). Dismissible; never a blocking overlay.
- **No multi-screen tutorial.** The onboarding puzzle IS the tutorial.

## Graduation
- On winning the onboarding puzzle: a brief, warm "you've got it!" moment, then a clear CTA into **today's real daily**. The habit loop starts on day one.
- First-run state marks onboarding complete; it never shows again. A returning player who never finished onboarding resumes it (don't strand them mid-teach).

## Instrumentation (this is the point — measure the hook)
Fire analytics events so the first-session funnel is measurable:
- `onboarding_started`, `onboarding_first_guess`, `onboarding_won`, `onboarding_abandoned` (with guess count), `graduated_to_daily`, and whether they then completed the real daily.
- This funnel is how we'll KNOW if the hook works once real players arrive — it directly measures the drop-off point this pass targets.

## Scope / constraints
- No gameplay-rule changes to the real daily; this is additive first-run flow.
- Reuse the existing puzzle engine, clue system, coaching as a thin presentation layer.
- The onboarding puzzle's secret/clue/example-guess are authored content (GG review — stop point).
- Respect the existing skip/no-strand behavior; onboarding must be skippable for the impatient (a "skip to today's puzzle" escape), but skipping is itself an analytics event.
- Works cold-profile (brand-new user) and doesn't affect existing users (who never see it, or see it once if first-run state says they haven't).

## Acceptance criteria
1. Brand-new player gets the onboarding puzzle first (not the calendar daily); existing/returning-completed players never see it.
2. Onboarding puzzle is near-impossible to lose (generous budget, easy secret, strong clue), with a pre-seeded example guess visible before first input.
3. Light coaching: plain-language rank interpretation on the first ~3 guesses + dismissible one-line nudges; reverts to normal feedback after onboarding.
4. EN + Hinglish onboarding puzzles, both authored to play well (Hinglish avoids known weak pairs).
5. On win → warm moment → clear CTA into today's real daily; first-run marked complete; never repeats.
6. Skippable ("skip to today's puzzle"); skip is instrumented.
7. Full first-session funnel analytics fire with correct params.
8. Interrupted onboarding resumes (no strand); cold-profile + existing-user harness both pass.
9. All tests green; live-verify the full first-run flow on a cold profile (onboarding → coaching → win → graduate → daily) in EN and Hinglish; confirm existing users are unaffected.

## Risks
- **Over-coaching annoys fast players** — keep it light, dismissible, and gone after onboarding; the escape hatch matters.
- **Onboarding puzzle quality is the make-or-break** — it's the first thing every player experiences; GG review mandatory.
- **Hinglish onboarding** — must pick a secret that plays well under the current model, or the first Hinglish impression reinforces the weakness; avoid titli/khamoshi/rasoi/samunder/bachpan-class pairs.
- **First-run state edge cases** — the rename/migration history means first-run flags must be robust (don't re-show onboarding to existing players, don't skip it for genuinely new ones).
