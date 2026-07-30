# Warmer — Hinglish Residual: Multi-Lever Research Assault

## Goal
Eliminate the two documented residual failure modes to push the field-leading model as close to "perfect" as the data/architecture allow — by attacking EVERY viable lever, measuring each on the trustworthy benchmark, and shipping whichever wins. Current model: `gauravgandhi2411/hinglish-relatedness-sbert`, dim1 Spearman 0.675 / dim2 0.740, 14/14 CI-significant vs alternatives, dev↔test 0.920. English untouched throughout.

## The residual, precisely (two DIFFERENT mechanisms → different fixes)
1. **Subword-collision** (junoon, registan …): romanized words fragment into subword pieces that collide with unrelated tokens, corrupting the embedding at the INPUT level. Proven dead: more same-recipe hard negatives at r=8 (can't teach past a corrupted representation).
2. **Associative-commonsense** (imli→sour …): world-knowledge relatedness, NOT distributional co-occurrence. Embedding models are structurally weak here (imli/sour rarely co-occur; you know it from tasting, not reading). A known frontier limit of pure embeddings — so the fix must change the APPROACH, not add more co-occurrence data.

## Method discipline (non-negotiable — this is what makes it research, not credit-burn)
- **Probe before scale:** each lever gets a SMALL, cheap experiment first, measured on the benchmark. Only levers that move the residual (CI-meaningfully, zero net regression) graduate to a full GCP run. The last probe proved a lever dead for the cost of a small run — apply that gate to every lever here.
- **One trustworthy ruler:** every candidate measured on the current benchmark (dim1 headline, dim2 secondary), bootstrap CIs, regression floor (must not break currently-working pairs). Report a comparison table across all levers.
- **GCP:** free credits for capacity sweeps + distillation (compute-heavy). Cap/monitor spend, spot GPUs, shut down instances, report credit burn. Model stays offline/build-time only.
- **Fix entry-21 bug FIRST** (LoRA best-checkpoint restore) if not already merged — every training run below depends on it selecting the right checkpoint.

## Lever set — attack ALL, probe each, scale the winners

### For subword-collision:
**L1 — Higher LoRA capacity.** Sweep rank (16/32/64), alpha, and MORE target modules (add value/output projections, not just query/key) — the collision may need representational room to route around bad tokenization. Probe on the collision words first.
**L2 — Devanagari-hybrid embedding.** Detect collision-prone / low-quality romanized tokens; embed their DEVANAGARI transliteration (the base tokenizes Devanagari far better) instead of the romanized form. Reuse the existing transliteration pipeline. Probe: does Devanagari-embedding the collision words fix their ranks without hurting clean words? (Decision needed: apply only to flagged words, or evaluate a full romanized→Devanagari front-end.)
**L3 — Alternative base with better romanized tokenization.** Test 2-3 bases (incl. newer Indic models) for how they tokenize junoon/registan-class words; if one fragments less, fine-tune it with the proven recipe and compare on the benchmark.

### For associative-commonsense:
**L4 — Knowledge distillation (strongest hypothesis).** A large instruction-tuned embedding/LLM KNOWS tamarind is sour. Distill that associative signal: use a big teacher model to score/generate commonsense-relatedness targets (imli↔sour-class) and train the student toward them. This injects world-knowledge the co-occurrence data lacks. Probe on the commonsense residual words first.
**L5 — Knowledge/retrieval augmentation at ranking time.** A non-fine-tuning mitigation: inject a world-knowledge edge (from a KG, or LLM-derived properties like "tamarind→sour/tangy") into the RANK computation, so the association exists even where embedding similarity doesn't. Probe: does adding this signal fix commonsense pairs without polluting normal ranking? (This changes the generator's ranking step, not the model — note the architecture implication.)
**L6 — Commonsense-shaped training data** (distinct from the failed co-occurrence hard-negatives): pairs explicitly built around properties/associations (taste, color, function), commercial-licensed or teacher-generated. Probe before scaling.

### Combination:
**L7 — Best-of-each stacked.** If a collision lever and a commonsense lever both win independently, combine and verify the combination doesn't regress (interactions can hurt). The shippable model is the best combination that clears the benchmark with zero net regression.

## Gates (every lever, every stage)
- Probe result reported per lever: does it move its target residual, CI-meaningfully, zero net regression? Graduate or kill — and if killed, mark PROVEN DEAD (like L1-old) so it's never re-tried blind.
- Full runs only for graduated levers. GCP credit burn reported.
- Final selection: the config maximizing benchmark dim1 (+dim2) with CIs, zero net regression on working pairs, and measurable residual reduction.
- EN untouched; frozen no-leakage; benchmark integrity preserved (don't tune the benchmark to the model).

## Ship (only if a lever/combo wins CI-significantly with zero net regression)
- Update the HF model (versioned) + card: new numbers, comparison, methodology, and the NOW-SMALLER residual reported honestly (whatever survives — report it, don't claim zero).
- Regenerate Warmer hi-en payloads with the winner; gates pass; byte-verified deploy; live spot-check unseen puzzles incl. former-residual words (junoon/registan/imli-class) — confirm they now read correctly.
- Update benchmark card / known-limitations to the new state.

## If some residual survives all levers
NOT "accept it." Report the CHARACTERIZED boundary with the evidence (which levers moved it how far, which didn't and why) and the remaining architectural attack (e.g. "commonsense relatedness needs a retrieval/KG signal we probed at small scale; here's the full-scale design") + player-data as the standing lever. A residual that's been assaulted by 7 levers and documented with the exact next attack is a fundamentally different artifact than one merely "noted."

## Acceptance criteria
1. Entry-21 LoRA-checkpoint bug fixed/confirmed before training.
2. All 7 levers probed; per-lever result (moved/killed, CIs, regression) in one comparison table; killed levers marked PROVEN DEAD.
3. Graduated levers scaled on GCP (credit burn reported); best config selected on the benchmark with zero net regression.
4. Former-residual words (junoon/registan/imli-class) measurably improved — report before/after ranks.
5. If shipped: model + card versioned & updated, payloads regenerated + byte-verified deployed, live spot-check incl. former-residual words, benchmark/ledger updated.
6. Any surviving residual documented as a characterized boundary + exact next attack (not "accepted"); EN untouched; frozen no-leakage; all tests green; every experiment logged + rerunnable.

## Risks
- **Benchmark overfitting** — attacking specific residual words risks tuning to the benchmark; the regression floor + held-out discipline + not-editing-the-benchmark-to-fit guard it.
- **Combination interactions** (L7) — stacked levers can regress; verify combined, not just individually.
- **Credit burn** — probe-gate everything; only graduated levers get full runs; report spend.
- **Commonsense may need architecture, not weights** — L4/L5 might show the real fix is a ranking-time knowledge signal, not a better embedding; that's a legitimate finding to design for, not force into the embedding.
```
