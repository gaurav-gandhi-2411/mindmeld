# Warmer — Applied-AI Eval Harness: Baseline Report

Generated in 64.5s. See the sibling `.json` file for full per-record detail (every flagged scenario, every judged clue, every simulated puzzle).

## Legacy pairwise-ordering fixtures (subsumed, not replaced)

- 70/70 passed

## Dimension 1 — Semantic ranking quality

### en

- n_scenarios: 227
- band-accuracy: overall 78.0%, near 96.0%, mid 7.7%, far 100.0%
- Spearman correlation: 0.842
- monotonicity violations: 36/614 (5.9%)
- flagged weak pairs: 50

### hi-en

- n_scenarios: 227
- band-accuracy: overall 75.3%, near 92.0%, mid 1.9%, far 99.2%
- **hi-en near-tier split** (GG review — do not blend these): translation 100.0% (n=20), associate 86.7% (n=30)
- Spearman correlation: 0.813
- monotonicity violations: 41/614 (6.7%)
- flagged weak pairs: 56

## Dimension 2 — Cross-language consistency

- 59/60 pairs resolved (1 vocab-coverage errors)
- pass rate (translation lands Scorching/Hot): 78.0%
- median rank: 3.0 (0.0th percentile of vocab)
- worst-diverging pairs (translation ranks near the BOTTOM of the vocab):

  - `razaai` <- `blanket`: rank 1821 (17.4%ile)
  - `khamoshi` <- `silence`: rank 882 (8.4%ile)
  - `pul` <- `bridge`: rank 766 (7.3%ile)
  - `parchhain` <- `shadow`: rank 561 (5.4%ile)
  - `bagicha` <- `garden`: rank 465 (4.4%ile)
  - `samunder` <- `ocean`: rank 445 (4.2%ile)
  - `khidki` <- `window`: rank 430 (4.1%ile)
  - `mombatti` <- `candle`: rank 350 (3.4%ile)
  - `bhook` <- `hunger`: rank 216 (2.1%ile)
  - `rasoi` <- `kitchen`: rank 174 (1.7%ile)

## Dimension 3 — Clue quality (local LLM judge, qwen3:8b)

### Calibration (judge <-> known-ground-truth agreement)

- spoiler-safety agreement: 96.9% (32 golden cases)
- solvability agreement: 62.5% (32 golden cases)

### Full clue-set judging

- n_clues_judged: 220 (errors: 0)
- solvability: min 1, mean 2.14, % below gate (3): 72.3%
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
- median win-rate: 82.0%
- in target band [75%,85%]: 63.6%
- outliers too easy (>97%): 0
- outliers too hard (<40%): 1
