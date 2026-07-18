# Warmer — Hinglish: Benchmark, Then Break It Further

## Goal
Make "best-quality Hinglish relatedness model" a MEASURED claim, then push accuracy against that measure. Current: v3 fine-tune shipped at full-set Spearman 0.800 (EN 0.837), but held-out eval is only n=16 secrets and there's no comparison to the field. Two phases: (1) a trustworthy, comparative benchmark; (2) accuracy improvements gated on it.

## Guiding principle
"Best out there" is a COMPARATIVE, STATISTICALLY-TRUSTWORTHY claim. First build a ruler we trust and compare against alternatives; then improve with every gain measured against that ruler. Diagnose and push — do not settle at 0.800 without establishing whether it's genuinely leading and how much further the method can go.

---

## PHASE 1 — Trustworthy + comparative benchmark (do FIRST)

### 1a. Expand + stabilize the held-out eval
- n=16 test secrets is too few for a defensible number. Expand the held-out set substantially (more secrets across diverse domains — nature, emotion, abstract, object, place, food, kinship), keeping the frozen no-leakage guarantee (nothing in test appears in training, incl. translations).
- Report every headline metric WITH bootstrap 95% CIs. Establish the minimum CI-significant delta so future improvements are judged as signal, not noise.
- Keep dim1 (in-language relatedness) and dim2 (cross-lingual) separate, plus the translation-tier vs in-language split.

### 1b. Comparative benchmark vs the field
- Run, on the SAME expanded held-out set, the current shipped model AND a slate of alternatives: the off-the-shelf baselines from the original bake-off (paraphrase-multilingual-MiniLM, l3cube base, MuRIL, BGE-M3, multilingual-e5) PLUS 2-3 NEWER multilingual/Indic embedding models released since the original bake-off (search HF for current best — the field moves).
- Produce ONE comparison table: model × {dim1 Spearman+CI, dim2 pass-rate+CI, band-accuracy, near/far separation}. This is the "best out there" evidence — our model must top it to claim leadership, and if something newer beats it, that's a finding (maybe a better base to fine-tune).

### 1c. Consider publishing the benchmark itself (portfolio + field value)
- There is no strong public romanized-Hinglish relatedness benchmark. Package the expanded held-out eval set (WITHOUT any Warmer game secrets/answers — use non-game vocabulary, same scrub discipline as the model card) as a small public eval dataset + the comparison results. This is a genuine contribution and a portfolio centerpiece. Optional but recommended; if done, licensing/attribution + zero-game-leak scrub are mandatory.

### Phase 1 gates
- Held-out set expanded (report n), CIs on all metrics, min-significant-delta stated.
- Comparison table across ≥6 models (baselines + newer) on the same set.
- Clear verdict: is our model leading? By how much (CI-significant)? Which alternative is closest / is any newer base worth fine-tuning?
- If a public benchmark is published: zero game-content leak (automated scrub), proper license/attribution.

---

## PHASE 2 — Push accuracy against the benchmark (after Phase 1)

Every change measured on the expanded held-out set with CIs; ship only CI-significant, zero-net-regression gains.

### 2a. More + better training data (the learning curve says this helps)
- The v3 learning curve rose monotonically (0.47→0.55→0.63 at 25/50/100%) — more good data helps now that LoRA controls capacity. Add: more mined IndicCorp v2 relatedness (commercial-clean), targeted pairs, WordNet-structure positives IF a commercial-OK Hindi source exists (re-verify licensing).
- (Note the real future unlock: player-guess data post-launch — in-domain, license-free. Flag, don't block.)

### 2b. Attack residual-weak clusters specifically
- khamoshi still reads Cold (#882, hugely improved from 8244 but not Hot), plus its abstract/emotional kin. Targeted hard-negatives + strong positives for the abstract-emotion cluster. Measure the cluster's held-out lift specifically.

### 2c. Method refinement
- LoRA hyperparameter sweep beyond r=8 (rank, alpha, target modules, LR) — the v3 sweep found r=8 works but wasn't exhaustive.
- If Phase 1b surfaced a newer/stronger base model, fine-tune IT with the v3 recipe and compare — a better starting point may beat improving the current base.

### Phase 2 gates (unchanged rigor)
- Every candidate evaluated on the expanded held-out set; report Spearman+CI, regression floor (fixed vs broken), residual-cluster lift.
- Ship only CI-significant improvement with zero net regression on currently-working pairs.
- If a change wins: republish the model (update HF repo + card with new numbers), flip config, regenerate payloads, gates, deploy byte-verified, live spot-check incl. unseen puzzles.
- EN untouched throughout.

## Acceptance criteria
1. Expanded held-out eval (report n, ≥ several-fold larger than 16), all metrics with bootstrap CIs, min-significant-delta stated.
2. Comparison table across ≥6 models (old baselines + ≥2 newer) on the same held-out set; explicit leadership verdict.
3. (If published) public benchmark dataset scrubbed of all game content, licensed + attributed.
4. Phase 2: each improvement lever evaluated against the benchmark; the best CI-significant, zero-net-regression config identified.
5. If shipped: HF model + card updated, payloads regenerated + gated, deployed byte-verified, live spot-check incl. unseen puzzles; residual-weak cluster status reported.
6. Frozen no-leakage discipline preserved throughout; EN unchanged; all tests green; every experiment logged + rerunnable.

## Risks
- **Claiming "best" on a weak ruler** — Phase 1 exists precisely to prevent this; don't push accuracy until the benchmark is trustworthy.
- **A newer base beats us** — that's a WIN (better foundation), not a threat; fine-tune it.
- **Diminishing returns** — honestly report when gains fall below CI-significance; at that point the real remaining lever is player data, stated as an attack plan not an acceptance.
- **Benchmark leaking game answers** — automated scrub mandatory if published.
```
