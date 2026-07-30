# Warmer — Hinglish Embedding Fine-Tune

## Goal
Raise the hi-en semantic engine above the off-the-shelf ceiling (Spearman 0.639, the current shipped `l3cube-pune/indic-sentence-bert-nli`) by fine-tuning it on Hinglish semantic-similarity data. Target: a real, held-out improvement toward ~0.72–0.78. English is untouched. Embeddings stay OFFLINE/precomputed — $0 runtime, no API key.

## The honest risk (this drives the whole design)
Fine-tuning on limited data trivially inflates eval numbers while making the actual game WORSE — the model memorizes the test pairs. Every design choice below exists to prevent that:
- **Strict train/dev/test split**, frozen before any training, with NO overlap of secrets OR vocab words across splits where avoidable.
- **The reported metric is TEST-set + a fresh live spot-check**, never the training data.
- **A regression floor**: the fine-tune must not degrade any currently-working pair (the pairs that already read correctly at 0.639 must still read correctly).
- If the fine-tune doesn't beat 0.639 on the HELD-OUT test set by a meaningful margin, we DON'T ship it — off-the-shelf stays. Over-tuned models that only win on seen data are a net negative.

## Training data (the real bottleneck)
Assemble Hinglish semantic-similarity pairs from multiple sources, deduped and quality-gated:
1. **Reuse the eval-harness dim-1 scenarios** — they're already (anchor, near, far) triplets = contrastive data in the exact shape SBERT training needs. But: whatever is used for TRAINING is REMOVED from the eval (no train/test leakage — this is the cardinal rule).
2. **LLM-augmented pairs** (local model, $0, no API key): generate Hinglish (word, related-word, unrelated-word) triplets across diverse domains; quality-filter with the LLM-as-judge already built (spoiler/quality patterns reused). Human spot-check a sample (GG) before training.
3. **Cross-lingual anchors**: romanized-Hindi ↔ English-translation pairs (jeet↔victory) as positive pairs — cheap, abundant, and directly targets the translation-tier weakness (currently 0.0%).
4. **Existing alias/normalization data** as trivial-positive pairs (spelling variants of the same word).
Aim for a training set large enough to matter (thousands of pairs) without overfitting; report final counts per source.

## Method
- **Base:** `l3cube-pune/indic-sentence-bert-nli` (the bake-off winner).
- **Training:** SBERT contrastive fine-tune — `MultipleNegativesRankingLoss` (in-batch negatives, works great with (anchor, positive) pairs) and/or `CosineSimilarityLoss` for graded pairs. Use LoRA/PEFT for parameter-efficiency (optional — full fine-tune is fine at this size; LoRA if it helps iteration speed).
- **Compute:** local/CPU or whatever's available; this is a small model — no cloud, no paid compute, no API key. Report training setup.
- **Hyperparams:** conservative (low LR, few epochs, early-stopping on the DEV set) — over-training is the enemy. Log the dev-set curve.

## Evaluation gates (the point)
Run the FULL eval harness (dims 1 & 2) on the fine-tuned model, reporting TEST-set (never train) numbers:
1. **Held-out Spearman** (test split) — must beat 0.639 by a meaningful margin to ship. Report translation-tier vs in-language split separately (the honest India-wedge number).
2. **Cross-language consistency** (dim 2) on the full paired schedule — must improve, not just dim 1.
3. **Regression floor**: run against the currently-correct pairs; the fine-tune must NOT break pairs that already work at 0.639. Report any regressions — a net-negative fine-tune (fixes some, breaks others) doesn't ship.
4. **Residual weak pairs**: re-check the known-fail set (titli, khamoshi, rasoi, samunder, bachpan) — report which the fine-tune fixed vs still-weak.
5. **English untouched**: EN metrics provably identical (fine-tune is hi-en only).

## Ship criteria (all must hold)
- Held-out test Spearman meaningfully > 0.639 (propose a threshold, e.g. ≥ 0.70).
- Cross-language consistency improved.
- Zero net regression on currently-working pairs.
- A LIVE spot-check on the deployed model: play 5-6 Hinglish puzzles on a real build, confirm known-close guesses read Hot/Scorching and far guesses Cold — including at least 2 puzzles NOT in any training data.
If any fails → DON'T ship the fine-tune; keep off-the-shelf and report why (likely: need more/better training data — a documented next step, not a failure to hide).

## Shipping (only if gates pass)
- Regenerate ALL hi-en payloads (daily + Bollywood + Cricket) with the fine-tuned model; byte-reproducible, size + spoiler gates pass.
- Commit the model artifact (or a reproducible training script + checkpoint reference) so builds are reproducible; document the training recipe.
- Update the eval baseline report (before/after hi-en, held-out) and known-limitations entry (Hinglish moves from 0.639 to the new held-out number).
- Note the on-device implication for the future any-word feature: model size after fine-tune (still ~470MB class; quantization needed for browser — same as before, note don't act).

## Acceptance criteria
1. Frozen train/dev/test split with documented no-leakage guarantee; whatever's used for training is removed from the eval.
2. Training data assembled from the sources above, counts reported per source, GG spot-check of a sample done.
3. Fine-tune run with logged dev-curve + conservative hyperparams; training recipe reproducible.
4. Full harness on TEST split: held-out Spearman, cross-lang, translation/in-language split, regression-floor check, residual-weak-pairs status, EN-unchanged proof — all reported.
5. Ship decision explicit against the ship criteria; if it doesn't clear, off-the-shelf stays and the reason is documented.
6. If shipped: payloads regenerated, gates pass, baseline report + ledger updated, live spot-check (incl. 2 unseen puzzles) passes.
7. All tests green.

## Risks
- **Overfitting / train-test leakage** — THE risk; the frozen split + held-out-only reporting + regression floor are the guards. Do not report training-set numbers as results.
- **Insufficient data** — the fine-tune may not clear the bar; that's an acceptable outcome (documented next step), not something to force by over-training.
- **Net-negative fine-tune** — fixing some pairs while breaking others; the regression floor catches it.
- **Reproducibility** — commit the recipe + checkpoint so the model isn't a one-off artifact no one can rebuild.
