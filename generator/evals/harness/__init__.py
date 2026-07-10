"""Applied-AI eval harness for Warmer's semantic engine.

Five gated dimensions (see spec-eval-harness.md):
  1. Semantic ranking quality  (harness.dimension1_ranking)
  2. Cross-language consistency (harness.dimension2_crosslang)
  3. Clue quality — local LLM judge (harness.dimension3_judge)
  4. Rival calibration (harness.dimension4_rival)
  5. Difficulty / win-rate modeling (harness.dimension5_winrate)

harness.pairs is shared infrastructure (the EN<->hi-en secret pairing) used
by dimensions 1 and 2. harness.report aggregates all dimensions into the
single run_evals_harness.py report.
"""
