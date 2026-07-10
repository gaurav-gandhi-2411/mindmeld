# Warmer — Applied-AI Eval Harness: Baseline Report

Generated in 2336.3s. See the sibling `.json` file for full per-record detail (every flagged scenario, every judged clue, every simulated puzzle).

## Legacy pairwise-ordering fixtures (subsumed, not replaced)

- 70/70 passed

## Dimension 1 — Semantic ranking quality

### en

- n_scenarios: 227
- band-accuracy: overall 74.9%, near 96.0%, mid 7.7%, far 94.4%
- Spearman correlation: 0.837
- monotonicity violations: 38/614 (6.2%)
- flagged weak pairs: 57

### hi-en

- n_scenarios: 227
- band-accuracy: overall 67.8%, near 68.0%, mid 1.9%, far 95.2%
- **hi-en near-tier split** (GG review — do not blend these): translation 85.0% (n=20), associate 56.7% (n=30)
- Spearman correlation: 0.639
- monotonicity violations: 94/614 (15.3%)
- flagged weak pairs: 73

## Dimension 2 — Cross-language consistency

- 59/60 pairs resolved (1 vocab-coverage errors)
- pass rate (translation lands Scorching/Hot): 54.2%
- median rank: 20.0 (0.2th percentile of vocab)
- worst-diverging pairs (translation ranks near the BOTTOM of the vocab):

  - `khamoshi` <- `silence`: rank 8244 (78.8%ile)
  - `rasoi` <- `kitchen`: rank 6393 (61.1%ile)
  - `samunder` <- `ocean`: rank 3809 (36.4%ile)
  - `bachpan` <- `childhood`: rank 3773 (36.1%ile)
  - `titli` <- `butterfly`: rank 3761 (36.0%ile)
  - `khidki` <- `window`: rank 3190 (30.5%ile)
  - `tyohar` <- `festival`: rank 3012 (28.8%ile)
  - `razaai` <- `blanket`: rank 2706 (25.9%ile)
  - `parchhain` <- `shadow`: rank 2610 (24.9%ile)
  - `pul` <- `bridge`: rank 2534 (24.2%ile)

## Dimension 3 — Clue quality (local LLM judge, qwen3:8b)

### Calibration (judge <-> known-ground-truth agreement)

- spoiler-safety agreement: 96.9% (32 golden cases)
- solvability agreement: 65.6% (32 golden cases)

### Full clue-set judging

- n_clues_judged: 220 (errors: 0)
- solvability: min 1, mean 2.15, % below gate (3): 71.8%
- spoiler-flagged clues: 0
- difficulty distribution: {'1': 0, '2': 25, '3': 184, '4': 11, '5': 0}
- mean cultural_fit (hi-en, uncalibrated): 4.80

## Dimension 4 — Rival calibration

- n_puzzles: 220
- median par: 8.0 (target 8-12: True), 100.0% within [4,16]
- median chill_spread: 5.0 (100.0% within [2,8])
- median sharp_spread: 3.0 (100.0% within [1,5])
- flagged puzzles: 0

## Dimension 5 — Difficulty / win-rate modeling

- n_puzzles: 220
- median win-rate: 93.0%
- in target band [75%,85%]: 10.5%
- outliers too easy (>97%): 18
- outliers too hard (<40%): 0
