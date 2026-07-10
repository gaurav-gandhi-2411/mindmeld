# Warmer — Applied-AI Eval Harness (foundation)

## Why this first
Before adding on-device inference or LLM-generated content, we need the measurement that proves the AI is correct — otherwise "well tested" and "rock solid" are assertions, not facts. This harness formalizes what "good" means for the semantic engine, runs synthetic scenarios, reports metrics, and becomes the gate every later AI feature must pass. It is the substance behind the launch claim of a tested, evaluated product.

Reuses existing patterns: the current eval fixtures (77/77), and the LLM-as-judge approach used elsewhere (local model, e.g. qwen3:8b — zero cost, no API key, respects the Max-plan rule).

## What the semantic engine does (under eval)
- Precomputed embeddings (all-MiniLM-L6-v2 en; multilingual for hi-en) → per-secret rank table of every vocab word by cosine similarity → hot/cold temperature bands + rank feedback. Plus deterministic rival paths, par, clues.

## Eval dimensions (each with synthetic scenarios + metrics)

### 1. Semantic ranking quality
- **Synthetic scenarios:** for a sample of secrets, curated (guess → expected band) sets — obvious-near (synonyms/strong associates → Scorching/Hot), mid (related domain → Warm), far (unrelated → Cold/Freezing). Author a few hundred labeled pairs per language (or generate + human-spot-check).
- **Metrics:** band-accuracy (does the guess land in the expected band), rank correlation (Spearman between human-intuited closeness and model rank on labeled sets), monotonicity checks (a strictly-more-related word should not rank worse).
- **Gate:** band-accuracy and correlation thresholds per language; regressions fail CI.

### 2. Cross-language consistency
- **Synthetic scenarios:** translation-paired secrets (the daily EN↔hi-en pairs) with parallel guess sets.
- **Metric:** for paired concepts, do analogous guesses land in comparable bands across languages? Flag pairs where the hi-en model diverges badly (the known script-clustering issue) so they're documented, not silently shipped.

### 3. Clue quality (LLM-as-judge)
- **Judge:** local LLM (qwen3:8b-class), zero cost. For every clue (daily + all packs), score: (a) solvability (does the clue point at the secret for a knowledgeable player), (b) spoiler-safety (does it give the answer away — complements the exact-alias gate + the semantic-neighbor audit), (c) difficulty estimate, (d) cultural-fit for Hinglish clues.
- **Calibration:** validate the judge against a human-labeled subset (GG's prior reviews) — report judge↔human agreement so the scores are trustworthy, not blindly accepted.
- **Metric/gate:** min solvability, zero spoiler-flags, difficulty distribution within target; new clues (future packs) must pass before publish.

### 4. Rival calibration
- **Synthetic scenarios:** simulate many solver trajectories against each puzzle; compare the deterministic rival's solve-length distribution to par and to plausible human play.
- **Metric:** rival solve-length vs par per tier (chill/even/sharp) within the spec bands; flag puzzles where the rival is trivially easy or unwinnable.

### 5. Difficulty / win-rate modeling
- **Synthetic scenarios:** simulate players of varying skill (embedding-guided guessers with noise) to estimate per-puzzle win-rate under the current maxGuesses.
- **Metric:** predicted win-rate distribution (target ~75–85% for a competent player); flag puzzles that are outliers (too easy/impossible) for content review.

## Deliverables
1. `evals/` harness: scenario generators (synthetic data), the labeled fixture sets, runners per dimension, and a single `run_evals` entry that produces a **report** (JSON + human-readable markdown) with all metrics per language.
2. Synthetic scenario generators for each dimension (documented, reproducible, seeded).
3. LLM-as-judge integration (local model, zero cost) with the human-agreement calibration report.
4. CI gates: the harness runs in the existing eval-gate CI; thresholds fail the build on regression.
5. A committed **baseline eval report** — the current state of the product measured, so launch has real numbers ("band-accuracy X%, clue-solvability Y%, judge↔human agreement Z%, predicted win-rate median W%").

## Acceptance criteria
1. All five eval dimensions implemented with synthetic scenarios + metrics, both languages.
2. `run_evals` produces a reproducible report (JSON + markdown) with every metric.
3. LLM-as-judge runs on the local model at $0, with a judge↔human calibration number reported (not assumed).
4. Gates wired into CI; a deliberately-broken clue/rank regression fails the harness (proven with a test).
5. Baseline report committed, documenting current measured quality + any flagged weak puzzles/clues/pairs (feeds the known-limitations ledger in workstream C).
6. Existing 77 fixtures subsumed/retained; all tests green.
7. Harness is structured so the later AI features (on-device scoring, generated content, semantic map) plug into it as new gated dimensions.

## Risks / notes
- **Judge trust:** an uncalibrated LLM judge is worse than none — the human-agreement calibration is mandatory, not optional.
- **Label quality:** synthetic scenarios must be sanity-checked by GG on a sample; garbage labels → meaningless metrics.
- **Scope:** this is measurement infrastructure + a baseline report. It does NOT add player-facing features (those are the next two sub-phases) — but it is the gate they must pass.
