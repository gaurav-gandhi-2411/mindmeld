# Warmer — Hinglish Fine-Tune: Diagnose & Break the Ceiling

## The real signal we missed
Two full fine-tunes both regressed below the 0.639 off-the-shelf baseline on held-out test — and adding 43% more data made it STRICTLY WORSE on every metric. That is not a "need more data" result. A regression that worsens with more data means the TRAINING METHOD is destroying signal (classic overfitting / catastrophic forgetting of a 470MB model on hundreds of pairs). We changed the data twice and never touched the method. This spec holds data roughly fixed and sweeps the METHOD to find and fix the actual fault.

## Guiding principle
Diagnose root cause, then break the ceiling. Do NOT conclude "limitation" — every hypothesis below is testable and we've tested none of them. Only after this full sweep genuinely exhausts the method axis do we reconsider scope.

## Step 0 — Trust the eval before trusting any result
- **Bootstrap the held-out test set** (n=16 secrets is small): compute a confidence interval on dim1 Spearman by resampling. Establish how large a change must be to count as signal vs noise. Report the baseline 0.639 WITH its CI. Every subsequent result is judged against this, not against a point estimate.
- If the eval is too noisy at n=16, expand the TEST set (add more held-out secrets from vocab, keeping the no-leakage guarantee) so results are trustworthy. A reliable ruler comes first.

## Step 1 — Diagnostic sweep (hold data ~fixed, vary the method)
Run each as a controlled experiment against the SAME frozen split + eval; report held-out test Spearman (+CI) for each. This is a hyperparameter/method search, not a data change.

1. **Capacity control (highest-priority hypothesis — untested):**
   - LoRA (low rank, e.g. r=4/8/16) instead of full fine-tune.
   - Freeze lower N transformer layers, train only top layers + pooling.
   - Much lower learning rate (sweep e.g. 1e-6 … 5e-5), fewer steps, aggressive early-stopping on dev.
   - Train ONLY the pooling/projection head, base frozen entirely (the minimal-capacity extreme).
   Goal: find the capacity that improves dev WITHOUT regressing test — the signature that overfitting is the fault and is now controlled.

2. **Objective alignment:**
   - The game scores by RANK against the whole vocab; we optimized pairwise cosine. Test a ranking-aware setup: larger in-batch negatives, harder negatives (mine near-miss negatives from the vocab, not random), and/or a loss that shapes global neighborhood structure.
   - Verify the training objective's improvement actually correlates with held-out Spearman (if train-loss drops but Spearman doesn't move, the objective is misaligned — key diagnostic).

3. **Catastrophic-forgetting check:**
   - Measure how far the fine-tuned embeddings drift from the base on a broad set of general Hinglish words (not just training words). Heavy drift + test regression = forgetting. If so, capacity control (#1) is confirmed as the fix.

4. **Input quality:**
   - Quantify transliteration error in the training set (the 34.6% dict/LLM agreement is alarming). Clean or normalize romanized forms; retrain the best config from #1 on cleaned inputs and measure the delta. Bad surface forms teach bad embeddings.

5. **Learning-curve diagnostic:**
   - Train the best config on 25% / 50% / 100% of the data and plot held-out Spearman vs data size. If the curve is RISING at 100%, more data genuinely helps (revisit data). If FLAT/FALLING, the method — not data volume — is the bottleneck. This definitively answers the "more data" question with evidence.

## Step 2 — Converge on the best configuration
- Pick the config that maximizes held-out test Spearman (beyond the baseline CI) with zero net regression on currently-working pairs.
- If a config beats 0.639 meaningfully (target ≥ 0.70, but ANY robust, CI-significant gain over baseline is a real win worth considering): proceed to ship criteria.
- Report the full sweep table: every config, its held-out Spearman + CI, regression floor, so the winner is evidenced.

## Step 3 — Ship criteria (unchanged, rigorous)
- Held-out test Spearman robustly (CI-significant) > 0.639, zero net regression on working pairs, cross-lang improved, EN untouched, live spot-check incl. ≥2 unseen puzzles.
- If it clears: regenerate hi-en payloads (daily+packs), gates pass, baseline report updated to the new number, live spot-check, deploy byte-verified.

## If the full sweep still doesn't beat baseline
This is NOT "accept the limitation." It's "the off-the-shelf model + available data has been exhausted across BOTH data and method axes, and here is the evidenced set of remaining levers that require inputs we don't yet have" — specifically:
- A larger/better base model (test 2-3 alternative multilingual/Indic bases the original bake-off didn't cover, e.g. newer BGE/E5/Indic releases).
- Real player-guess data (in-domain, license-free, post-launch).
Frame any residual as "here's exactly what would break it and why," with the diagnostic evidence — a live problem with a known attack plan, not a closed one.

## Acceptance criteria
1. Eval reliability established (bootstrap CI on baseline; test set expanded if needed).
2. Full method sweep run (capacity control, objective alignment, forgetting check, input cleaning, learning curve) — each a controlled experiment vs the frozen split, held-out results + CI reported in one table.
3. Learning-curve diagnostic explicitly answers whether data volume or method is the bottleneck, with evidence.
4. Best config identified; if it beats baseline CI-significantly with no net regression → ship path; else the evidenced remaining-levers writeup (NOT an "accept" framing).
5. EN untouched throughout; frozen split + no-leakage preserved; all tests green.
6. Reproducible: every experiment's config + seed logged; the sweep is rerunnable.

## Risks
- **Reading noise as signal** — Step 0's CI is the guard; do not act on sub-CI differences.
- **Sweep breadth vs time** — prioritize capacity control (#1) first; it's the likeliest fix. If LoRA/frozen-head immediately beats baseline, that may be the answer before the full sweep completes.
- **Confirmation bias toward shipping** — the regression floor + held-out-only + CI significance prevent shipping a fake win; keep them strict.
