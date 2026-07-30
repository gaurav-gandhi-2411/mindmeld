# Warmer — Hinglish Research Release (GCP-scaled)

## Goal
Turn the field-leading fine-tune into a category-defining PUBLIC release: the reference romanized-Hinglish semantic-relatedness model AND benchmark — the only rigorously-benchmarked one that exists. Use free GCP credits to (a) build a benchmark large enough that "best" is statistically defensible, (b) scale training data (the learning curve is still rising), (c) scale training (LoRA/base-model sweeps too slow locally). Sequenced so compute isn't wasted.

## Honest framing (guards the credibility that IS the USP)
"No limitations" is not achievable — every model has an error bar and a residual set. The real target: FIX the fixable limitations, SHRINK the rest until negligible, and MEASURE on a benchmark big enough that the numbers are defensible. The USP is not "a higher number" — it's "the authoritative, rigorously-benchmarked reference model + benchmark for romanized Hinglish, with an honest card." Overclaiming ("zero limitations") destroys the credibility that makes it valuable. Report residuals honestly; that's the strength.

## The USP (what no one else has)
There is no strong public romanized-Hinglish (Latin-script Hindi-English) relatedness model OR benchmark. Own the category:
1. A large, clean, public **benchmark** for romanized-Hinglish semantic relatedness (fills a real field gap — citable).
2. A model that **tops it** against all comparable alternatives, CI-significant.
3. The **methodology + honest card** (bake-off → diagnostic → LoRA → scaled release).

## Environment (GCP, free credits)
- Use GCP for: large-scale data mining/transliteration, and GPU training sweeps. Report the setup (instance type, GPU, cost against credits) so it's reproducible.
- Keep the model itself offline-usable (the game precomputes embeddings; GCP is build-time only). No new runtime dependency, no per-query cost.
- Guard the credits: cap/monitor spend; prefer spot/preemptible GPUs for sweeps; shut down instances after runs. Report credit burn.

## PHASE 1 — Trustworthy benchmark FIRST (fixes limitations 1 & 2)
A bigger model is unmeasurable on 8 clusters — the ruler comes first.
1. **Scale the held-out benchmark** to a defensible size (target: several hundred labeled pairs across diverse domains — nature, emotion, abstract, kinship, object, place, food, action). Sources: human-annotated where commercial-licensed data exists (re-verify), transliterated Hindi similarity data (relatedness-style, not pure-synonymy — the WordSim vs SimLex distinction matters), and carefully-judged synthetic pairs as a minority. Keep the frozen no-leakage guarantee.
2. **Fix the dev↔test 0.12 problem:** with a larger eval, hold out a proper dev set that actually predicts test, so checkpoint selection is trustworthy (not the current "select by sweeping test," which risks test-set overfitting at scale).
3. Report all metrics with bootstrap CIs; state min-significant-delta. This benchmark is the ruler for everything downstream AND the public artifact.
4. Scrub ALL game content (daily + pack secrets, variants, strong associates) from anything published — automated collision + associate check (the earlier scrub caught 6 leaks in 12; be at least that strict).

## PHASE 2 — Scale training data (fixes limitation 4)
The learning curve rose monotonically to 100% — more good data helps. With GCP:
1. **Large-scale relatedness mining** from commercial-clean corpora (IndicCorp v2 CC0, others with verified commercial licenses) — PMI/co-occurrence at much larger scale, quality-filtered (the judge rejected 88% before — expect similar; volume compensates).
2. **Reliable transliteration at scale** (Aksharantar/IndicXlit on GPU) — fix the 34.6%-agreement transliteration-noise problem with better models/beam search, since bad surface forms cap quality.
3. **Hard-negative mining at scale** (the v3 win included mined hard negatives — do more, better).
4. Licensing gate on EVERY source (commercial-OK for a public model); report each.
5. Target a training set several-fold larger than the current 1741 pairs, quality-gated.

## PHASE 3 — Scale training (squeeze the method)
1. **Exhaustive LoRA sweep** (rank, alpha, target modules, LR, epochs) — GPU makes the search that was too slow locally feasible.
2. **Base-model bake-off v2 at scale:** fine-tune the top 2-3 bases (l3cube + any newer strong Indic/multilingual base) with the full recipe; the best foundation may beat improving l3cube.
3. Every candidate measured on the Phase-1 benchmark with CIs + regression floor; select by held-out (now trustworthy) + zero-net-regression.

## PHASE 4 — Release
1. Publish the winning model to the existing HF repo (or a versioned new one), card updated with: the large-benchmark numbers + CIs, the full comparison table, methodology, and HONEST residuals (whatever weak set remains — report it, don't hide it).
2. Publish the large benchmark as a public dataset (scrubbed, CC-BY, attributed).
3. Regenerate Warmer's hi-en payloads with the new model; gates pass; byte-verified deploy; live spot-check unseen puzzles.
4. Update Warmer's eval baseline + docs.

## Ship/quality gates (every phase)
- Benchmark large enough for tight CIs; report n and CIs on everything.
- New model beats all comparators CI-significantly on the large benchmark.
- Zero net regression on currently-working pairs.
- Residual weak set reported honestly (shrunk, not claimed-solved).
- EN untouched; frozen no-leakage preserved; game content scrubbed from public artifacts.
- Reproducible: data pipeline, training recipe, GCP setup, seeds all logged.

## Acceptance criteria
1. Large benchmark built (report n, CIs, domains), dev set that predicts test (dev↔test corr materially > 0.12), all game content scrubbed + verified.
2. Training data scaled several-fold, every source licensed commercial-OK + reported, transliteration-noise reduced.
3. LoRA + base-model sweep at scale; best config selected on the large held-out benchmark with CIs + regression floor.
4. Winning model beats all comparators CI-significantly; residual weak set reported honestly.
5. Public release: model + card (large-benchmark numbers, comparison, honest limits) + public benchmark dataset (scrubbed, licensed, attributed).
6. Warmer payloads regenerated + gated + byte-verified deployed; live spot-check passes.
7. GCP setup reproducible; credit burn reported; EN untouched; all tests green.

## Stops for GG
- After Phase 1: review the benchmark (size, sample of pairs, scrub verification) before it's used as the ruler / published.
- Before any public dataset/model card goes live: scrub + license review.

## Risks
- **Overclaiming** — "no limitations" would gut credibility; honest residuals ARE the USP. Report weaknesses.
- **Test-set overfitting at scale** — bigger sweeps risk selecting on test; the trustworthy dev set (Phase 1.2) guards it.
- **Licensing** — a public model/benchmark on non-commercial data is a legal problem; gate every source.
- **Credit burn** — cap spend, spot GPUs, shut down instances; report usage.
- **Diminishing returns** — if scaled data+training doesn't beat current CI-significantly, that's an honest finding (and the real remaining unlock is player data post-launch) — report it, don't force it.
```
