# Warmer — Hinglish Data Expansion + Retrain

## Why
The first fine-tune overfit (543 pairs too few; held-out Spearman regressed 0.435→0.376). Root cause = data volume + quality, not method. This expands the training data from REAL, human-annotated and corpus-mined sources (not more LLM guessing), then retrains against the same frozen held-out gates. Ship only if it beats 0.639 held-out with zero net regression.

## Critical insight from research (shapes the data strategy)
Word-similarity datasets split into two kinds:
- **Relatedness** (WordSim-353 style): weather↔forecast, stock↔market score HIGH. Association/domain-relatedness.
- **True similarity** (SimLex-999 style): only synonymy scores high; associates and antonyms score LOW.
**Warmer's game is RELATEDNESS** (a guess in the right domain should read Warm, not just exact synonyms). So prioritize WordSim/relatedness-style data; use SimLex-style only carefully (as strong-positive synonym anchors), NOT as the primary signal — training on pure-similarity data would teach a "close" that mismatches how the game scores.

## LICENSING GATE (do this FIRST — commercial product)
Before using ANY dataset for training a model that ships in production, verify its license permits commercial use. Report each source's license explicitly. CC-BY (with attribution) is fine; non-commercial / research-only licenses are NOT usable for the shipped model (could still be used for EVAL-only, kept separate). Do not train on anything whose license you can't confirm commercial-OK.

## Data sources (verify availability + license for each)
1. **Hindi WordSim-353** — WordSim-353 translated to Hindi with native-speaker similarity annotations (relatedness — the right kind). Reportedly CC-BY-4.0. Human-scored graded pairs → the gold training signal.
2. **Multilingual SimLex-999 (Hindi)** — human similarity scores; use as strong-synonym positives only (it's similarity not relatedness — don't let it dominate).
3. **Hindi WordNet** — synonym sets (strong positives), hypernym/hyponym pairs (graded positives). Structured, human-curated relatedness.
4. **Corpus co-occurrence** (IndicCorp / HingCorpus if accessible) — mine empirical relatedness from real Hinglish/Hindi text (PMI/co-occurrence gives relatedness grounded in actual usage, not LLM guessing). Heavier; do if feasible.
5. **Transliteration** — use Aksharantar/IndicXlit to reliably render Devanagari sources → romanized Hinglish (your engine's input form). This is the bridge that makes Devanagari benchmarks usable.
6. Keep the existing LLM-augmented pairs ONLY as a minority supplement, not the backbone (they were 89/543 and are the weakest signal).

## Method (unchanged from last attempt — it was sound)
- Base: `l3cube-pune/indic-sentence-bert-nli`. SBERT contrastive (MNRL for pairs, CosineSimilarity for graded). Conservative epochs, early-stop on DEV. LoRA optional (reduces effective params → less overfit risk with the new larger set).
- Transliterate all Devanagari sources to romanized form to match engine input; verify transliteration quality on a sample.

## The frozen split is SACRED (carry over from last attempt)
- Reuse the EXACT same train/dev/test split of the 60 schedule secrets (33/11/16, 5 residual-weak forced into test). New external data is TRAINING-side only and must NOT contain any test secret or its translation — assert + test, same no-leakage guarantee.
- The eval is unchanged, so the new held-out number is directly comparable to the 0.639 baseline and the failed fine-tune's 0.376.

## Gates + ship criteria (unchanged — this is the point)
1. Held-out TEST Spearman meaningfully > 0.639 (target ≥ 0.70), translation vs in-language split reported.
2. Cross-language consistency (dim 2) improved.
3. Regression floor: zero NET regression on currently-working pairs (report fixed vs broken).
4. Residual-weak pairs (titli/khamoshi/rasoi/samunder/bachpan) status.
5. EN untouched (provably identical).
6. Live spot-check incl. ≥2 unseen puzzles.
Ship ONLY if 1-3 hold. If not → off-the-shelf stays, documented (now with "even real-corpus data at scale didn't clear it" — a much stronger documented ceiling than before).

## Deliverables
1. Licensing report per source (commercial-OK or not).
2. Assembled dataset with per-source counts + provenance; GG spot-check of a sample.
3. Retrain + held-out eval report (test-set only), same gates.
4. Explicit ship decision.
5. If shipped: regenerate hi-en payloads, gates pass, baseline report + ledger updated to the new number, live spot-check.
6. Reproducible recipe + data-prep pipeline committed (data sources referenced, not necessarily vendored if large; checkpoints gitignored).

## Acceptance criteria
1. Every data source's license verified + reported; only commercial-OK data used for the shipped model.
2. Data assembled from real human-annotated + corpus sources (LLM only a minority supplement); relatedness prioritized over pure-similarity; counts + provenance reported; GG sample spot-check.
3. Same frozen split + no-leakage guarantee (asserted + tested); new data is train-side only, no test-secret/translation leakage.
4. Retrained; held-out TEST metrics reported with translation/in-language split, regression floor, residual-pairs, EN-unchanged.
5. Explicit ship decision vs criteria; if no-ship, documented with the stronger ceiling evidence.
6. If shipped: payloads regenerated + gated, ledger updated, live spot-check incl. unseen puzzles passes.
7. All tests green.

## Risks
- **Licensing** — some academic datasets are research-only; using one in a shipped model is a legal problem. The licensing gate is mandatory, not optional.
- **Relatedness vs similarity mismatch** — training on SimLex-style pure-similarity data would teach the wrong notion of "close"; prioritize WordSim/relatedness.
- **Transliteration noise** — Devanagari→romanized adds error; verify on a sample, and the alias layer helps.
- **Still might not clear the bar** — even real data may not be enough for 10k-vocab; if so, that's a strong, well-evidenced documented ceiling (and the real unlock becomes player guess-data post-launch). An honest no-ship remains a valid outcome.
