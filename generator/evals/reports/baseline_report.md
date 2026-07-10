# Warmer — Applied-AI Eval Harness: Baseline Report

Generated in 2326.9s. See the sibling `.json` file for full per-record detail (every flagged scenario, every judged clue, every simulated puzzle).

## Legacy pairwise-ordering fixtures (subsumed, not replaced)

- 77/77 passed

## Dimension 1 — Semantic ranking quality

### en

- n_scenarios: 227
- band-accuracy: overall 74.9%, near 96.0%, mid 7.7%, far 94.4%
- Spearman correlation: 0.837
- monotonicity violations: 38/614 (6.2%)
- flagged weak pairs: 57

### hi-en

- n_scenarios: 227
- band-accuracy: overall 54.6%, near 8.0%, mid 0.0%, far 96.0%
- **hi-en near-tier split** (GG review — do not blend these): translation 0.0% (n=20), associate 13.3% (n=30)
- Spearman correlation: -0.003
- monotonicity violations: 330/614 (53.7%)
- flagged weak pairs: 103

## Dimension 2 — Cross-language consistency

- 59/60 pairs resolved (1 vocab-coverage errors)
- pass rate (translation lands Scorching/Hot): 5.1%
- median rank: 4881.0 (46.6th percentile of vocab)
- worst-diverging pairs (translation ranks near the BOTTOM of the vocab):

  - `ghadi` <- `clock`: rank 10394 (99.3%ile)
  - `aaina` <- `mirror`: rank 10291 (98.4%ile)
  - `bijli` <- `lightning`: rank 10249 (98.0%ile)
  - `chaand` <- `moon`: rank 10211 (97.6%ile)
  - `sipahi` <- `soldier`: rank 9998 (95.6%ile)
  - `rasoi` <- `kitchen`: rank 9917 (94.8%ile)
  - `pul` <- `bridge`: rank 9743 (93.1%ile)
  - `titli` <- `butterfly`: rank 9579 (91.6%ile)
  - `nadi` <- `river`: rank 9430 (90.1%ile)
  - `khidki` <- `window`: rank 9172 (87.7%ile)

## Dimension 3 — Clue quality (local LLM judge, qwen3:8b)

### Calibration (judge <-> known-ground-truth agreement)

- spoiler-safety agreement: 96.9% (32 golden cases)
- solvability agreement: 65.6% (32 golden cases)

### Full clue-set judging

- n_clues_judged: 220 (errors: 0)
- solvability: min 1, mean 2.15, % below gate (3): 71.8%
- spoiler-flagged clues: 0
- difficulty distribution: {'1': 0, '2': 26, '3': 183, '4': 11, '5': 0}
- mean cultural_fit (hi-en, uncalibrated): 4.80

**Interpretation note (read before acting on the 71.8% figure):** manually
spot-checked the 8 lowest-scored (solvability=1) real clues against the raw
text — every one is a legitimate, evocative, human-approved clue, e.g.
`music`: "It reaches places in your mind that words alone cannot",
`village`: "Where everyone knows your grandmother's name",
`friend`: "The family you choose, one laugh at a time". None of these are
broken. This matches the calibration finding above exactly: solvability
agreement is only 65.6% (vs spoiler-safety's 96.9%), and the specific,
confirmed failure mode is the judge under-rating deliberately indirect/
evocative clues — which is this game's house style by design. **Read the
71.8% figure as "this judge's absolute solvability threshold doesn't fit
this game's clue-writing style", not as "most clues are unsolvable".**
The judge is far more trustworthy for spoiler-detection (0 flagged, matches
the deterministic exact-alias gate's own 0-leak result exactly) and for
difficulty-distribution sanity-checking (reasonable, non-degenerate spread)
than for absolute solvability scoring. Do not wire a hard solvability-score
gate against future clues using this judge without either recalibrating the
threshold or moving to a relative/comparative solvability check.

## Dimension 4 — Rival calibration

- n_puzzles: 220
- median par: 8.0 (target 8-12: True), 100.0% within [4,16]
- median chill_spread: 5.0 (100.0% within [2,8])
- median sharp_spread: 3.0 (100.0% within [1,5])
- flagged puzzles: 0

## Dimension 5 — Difficulty / win-rate modeling

- n_puzzles: 220
- median win-rate: 92.0%
- in target band [75%,85%]: 10.9%
- outliers too easy (>97%): 21
- outliers too hard (<40%): 0
