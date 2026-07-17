# Hinglish Embedding Fine-Tune — Ship Decision Report v2 (retry with expanded data)

Base model: `l3cube-pune/indic-sentence-bert-nli` (off-the-shelf champion, Spearman 0.639
on the full 25-secret / 227-scenario production dim1 set, per `evals/reports/baseline_report.md`).
Fine-tune recipe: `evals/finetune/train.py` — **unchanged from the v1 attempt** (commit
`1ac318e`), seed 42, reproducible from committed data. This is a retry with substantially
more/better training data; the method, hyperparameters, and eval harness are held constant
so the delta is attributable to data alone.

## Split (frozen, unchanged from v1 — no leakage — see `data/split.json`)

60 daily-schedule hi-en secrets -> 33 train / 11 dev / 16 test. The 5 documented residual-weak
secrets (titli, khamoshi, rasoi, samunder, bachpan) forced into test. `tests/test_finetune_no_leakage.py`
passes (3/3) against the regenerated data.

## Training data (expanded vs v1: 543/705 pairs -> 756/1028 pairs, 5 sources)

Per `evals/finetune/data/counts.json`:

| Source | MNRL pairs | Graded pairs |
|---|---|---|
| dim1 triplets | 24 | 108 |
| LLM-augmented (90 accepted after judge) | 89 | 178 |
| crosslingual (hinglish.txt) | 421 | 421 |
| alias | 32 | 32 |
| corpus-PMI-mined + LLM-judge-filtered (new source) | 214 | 325 |
| **Total after dedup** | **756** | **1028** |

13 homograph collisions and 2 fuzzy-negative pairs excluded (unchanged filtering logic from
the v1 remediation commit `694b2a0`). No-leakage assertion passed — no training record
touches a held-out secret or its EN translation.

## Training

SBERT contrastive fine-tune, `MultipleNegativesRankingLoss` (MNRL dataset) +
`CosineSimilarityLoss` (graded dataset), 4 epochs, lr=2e-5, batch=16, warmup_ratio=0.1,
early-stopping patience=2 on a DEV-only evaluator. Ran to completion (all 4 epochs, no
early stop triggered). Dev-curve (`data/dev_curve.json`): spearman_cosine 0.7796 -> 0.7962
-> 0.8093 -> 0.8158 across epochs 1-4, monotonically improving, best at epoch 4 (loaded via
`load_best_model_at_end`). Train runtime 541.2s (~9 minutes CPU), train_loss 0.4825.

**Dev numbers are NEVER the reported result** — logged here purely for training-run
sanity (no divergence, no NaN, no early collapse). Only the TEST-split numbers below count.

## Held-out TEST results (the only reportable numbers — never train)

Restricted to the 16 frozen TEST secrets (8 of which have dim1 curated scenarios; all 16
have dim2 cross-lingual pairs), comparing the SAME off-the-shelf baseline against the
fine-tuned checkpoint on identical held-out data. Full JSON:
`evals/finetune/data/held_out_comparison_v2.json`.

| Metric | Baseline (off-the-shelf) | Fine-tuned v2 | Delta | (v1 fine-tuned, for reference) |
|---|---|---|---|---|
| dim1_test Spearman (n=73 scenarios, 8 secrets) | 0.4350 | **0.3244** | **-0.1106 (worse)** | 0.3764 |
| dim1_test band-accuracy overall | 0.6027 | 0.5616 | **-0.0411 (worse)** | 0.5753 |
| dim1_test near/translation-tier accuracy (n=7) | 0.5714 | 0.2857 | **-0.2857 (worse)** | 0.4286 |
| dim1_test near/associate-tier accuracy (n=9) | 0.2222 | 0.2222 | unchanged | 0.2222 |
| dim2_test pass-rate Scorching/Hot (n=16 pairs) | 0.3750 | **0.2500** | **-0.125 (worse)** | 0.3750 (unchanged) |
| dim2_test median rank (lower=better) | 555.5 | 1916.0 | **worse (~3.4x farther)** | n/a (percentile only reported previously) |
| dim2_test median rank percentile (lower=better) | 5.31 | **18.31** | **worse (~3.4x farther)** | 9.66 |

**v2 is worse than v1 on every single metric above, including the metrics v1 already
failed on.** More training data (1784 total pairs vs 1248 in v1) did not fix the
overfitting/generalization problem — it made held-out generalization measurably worse.

## Regression floor (per-pair, TEST split only)

- dim1_test: **3 pairs fixed** (wrong->right) — `bachpan/notch`, `phool/bagicha`,
  `samunder/jimmy` — vs. **6 pairs broken** (right->wrong): `bachpan/panthers`,
  `chaand/moon`, `khazana/treasure`, `phool/walsh`, `samunder/wave`, `samunder/btw`.
  **Net -3, regression floor FAILS** (worse than v1's net -2).
- dim2_test: **0 pairs fixed** vs. **2 pairs broken** (right->wrong): `treasure->khazana`,
  `moon->chaand` (the same two pairs v1 broke). **Net -2, regression floor FAILS** (worse
  than v1's net 0 — v1 at least fixed 2 dim2 pairs to offset the 2 it broke; v2 fixes none).

## Residual weak pairs (titli, khamoshi, rasoi, samunder, bachpan — held out, never trained)

dim1 (Spearman restricted to these 5 secrets' scenarios): baseline 0.0 -> finetuned 0.0046
(both effectively zero — no meaningful signal either way). Band-accuracy overall: baseline
0.5000 -> finetuned 0.4444 (worse); near-tier 0.0 -> 0.0 (unchanged, both fail); mid-tier
0.25 -> 0.0 (worse); far-tier 0.8 -> 0.8 (unchanged).

| Pair | Baseline rank (band) | Fine-tuned v2 rank (band) | v1 rank (band), for reference | Status (v2) |
|---|---|---|---|---|
| samunder<-ocean | 3809 (Freezing) | 3014 (Freezing) | 5224 (Freezing, worse) | improved vs baseline, still fails; better than v1's regression |
| rasoi<-kitchen | 6393 (Freezing) | 1418 (Cold) | 367 (Hot, **FIXED**) | improved vs baseline, still fails — v1 had actually crossed to passing, v2 does not |
| titli<-butterfly | 3761 (Freezing) | 2417 (Cold) | 2784 (Freezing, still fails) | improved vs baseline and vs v1, still fails |
| khamoshi<-silence | 8244 (Freezing) | 2817 (Freezing) | 1654 (Cold, still fails) | improved vs baseline, worse than v1, still fails |
| bachpan<-childhood | 3773 (Freezing) | 1127 (Cold) | 184 (Hot, **FIXED**) | improved vs baseline, still fails — v1 had crossed to passing, v2 does not |

dim2 pass-rate on this subset: baseline 0.0 -> finetuned v2 **0.0 (0 of 5 pass)** — worse
than v1's 0.4 (2 of 5 passed). Every pair's raw rank moved closer to the secret (lower
rank number) than baseline, but none crossed the Scorching/Hot threshold (rank <= 500,
n=10462 hi-en vocab) required to count as "consistent." v1 had specifically pushed
`rasoi` and `bachpan` across that threshold; v2's broader, noisier training signal pulls
embeddings in a more diffuse direction that improves raw distance without improving the
discrete pass/fail outcome that the game actually uses.

## EN-unchanged proof

`config.MODELS["en"]` == `"sentence-transformers/all-MiniLM-L6-v2"` after this run,
verified by direct inspection: `git diff --stat config.py` and `git status --short config.py`
both empty (file byte-identical to the pre-session commit). `grep -n "config\." evals/finetune/train.py`
returns zero matches — `train.py` never imports or references `config` at all, it only loads/saves
the hi-en SentenceTransformer checkpoint directly. `eval_model.py`'s `_model_override` context
manager only ever reads/writes `config.MODELS["hi-en"]` (three occurrences, all keyed
`"hi-en"`) and restores the original value in its `finally` block. No code path in this
pipeline can touch `config.MODELS["en"]` — not just by re-running the EN eval, but by
construction (grep confirms the string `"en"` as a MODELS key never appears in
`evals/finetune/*.py`).

## SHIP DECISION: **DO NOT SHIP**

Against the stated ship criteria (`spec-hinglish-finetune.md`), evaluated against the
TEST-restricted baseline (0.4350) that both models were scored on identically — the
spec's headline 0.639 is the baseline's score on the FULL 25-secret production set,
not a number either model was measured against on the held-out 8-secret/73-scenario
TEST slice, so 0.4350 is the correct apples-to-apples comparator, per the same
methodology v1 used:

| Gate | Criterion | Result |
|---|---|---|
| 1. Held-out TEST Spearman | meaningfully > 0.4350 baseline (target >=0.70) | **FAILS** — 0.3244 < 0.4350, a regression, and worse than v1's already-failing 0.3764 |
| 2. Cross-language consistency (dim2) | improved | **FAILS** — pass-rate 0.25 < 0.375 baseline (worse); median rank percentile 18.31 vs baseline 5.31 (~3.4x farther); residual-weak dim2 pass-rate 0.0, worse than v1's 0.4 |
| 3. Zero net regression on currently-working pairs | fixed >= broken, no working pair broken | **FAILS** — dim1_test net -3 (3 fixed / 6 broken); dim2_test net -2 (0 fixed / 2 broken) |

All three primary gates fail, more severely than the v1 attempt. Per spec: *"If any fails ->
DON'T ship the fine-tune; keep off-the-shelf and report why."* The off-the-shelf
`l3cube-pune/indic-sentence-bert-nli` stays in production, unchanged from before this
session (see EN-unchanged proof above — the hi-en model in `config.MODELS` was only ever
overridden inside eval's `with` block and is restored on exit; nothing in this repo's
checked-in config points at the fine-tuned checkpoint).

## Why it likely failed — and why MORE data made it WORSE, not better

The v1 hypothesis was "543/705 pairs is too small relative to a ~110M-parameter BERT-base
model; more data should help." v2 tested that hypothesis directly — same model, same
hyperparameters, same split, 1.43x more training pairs (1784 vs 1248) — and the held-out
TEST result got uniformly worse, not better, on every metric measured. That is itself the
useful (negative) finding of this session: **the bottleneck is not training-data volume**.
Plausible mechanisms, none confirmed by an ablation in this session (stated as hypotheses,
not established facts):

- The new corpus-PMI-mined source (214 MNRL / 325 graded pairs, ~28%/32% of the respective
  totals) is co-occurrence-derived rather than curated-semantic, and PMI co-occurrence in a
  general Hindi corpus is a noisier proxy for "these two words should be close in embedding
  space for a word-guessing game" than the hand-authored dim1 triplets or LLM-judged pairs
  are. Adding a large volume of a noisier signal can dilute a small clean signal rather than
  reinforcing it.
- Dev Spearman kept climbing every epoch (0.7796 -> 0.8158) with no early-stopping trigger —
  same overfitting signature as v1 (dev improves, test does not), now with a *steeper* dev
  climb (v1's best dev was 0.845; the training data for v1 is different so not directly
  comparable, but the shape — monotonic dev improvement fully decoupled from test — repeats).
  This is consistent with the model continuing to specialize toward the dev-adjacent lexical
  neighborhood regardless of how much train data is added, because dev secrets are only
  11 items and the MNRL/graded losses pull anchors and positives together globally, including
  pairs lexically close to dev/test words even when the exact secrets are excluded.
- Conservative hyperparameters (lr=2e-5, 4 epochs) were held constant per this task's
  explicit scope (do not modify train.py); this session did not test lower LR, fewer epochs,
  layer-freezing, or LoRA — those remain untested next steps, now with stronger evidence
  that data volume alone is not sufficient and one of these regularization changes is likely
  necessary before another data-only retry would be worth running.

Recommended next step if this is revisited (not undertaken in this session, out of scope):
an ablation that varies ONLY the loss/regularization axis (freeze lower transformer layers,
or LoRA, or fewer epochs/lower LR) while holding this same v2 dataset fixed, to isolate
whether the problem is data quality/composition or optimization — rather than another
data-volume increase, which this session's result argues will not help on its own.

## Reproducibility

Recipe fully committed (pending orchestrator review/commit of the regenerated data files
per this session's scope boundary): `evals/finetune/{split,assemble_data,pmi_mine,
pmi_quality_filter,llm_augment,homograph_audit,train,eval_model}.py`, frozen split
(`data/split.json`, unchanged from v1), assembled training data (`data/train_{mnrl,graded}_pairs.jsonl`,
regenerated), cached LLM triplets (`data/llm_triplets_accepted.json`), homograph audit
(`data/homograph_exclusions.json`), corpus-PMI raw/filtered pairs (`data/raw/corpus_pmi_pairs*.jsonl`).
Seed 42 throughout. The trained checkpoint itself and training checkpoints are NOT committed
(gitignored) since nothing shipped — re-running `uv run python -m evals.finetune.train`
against the committed data reproduces the same result bit-for-bit-modulo-hardware.
Full numeric comparison: `evals/finetune/data/held_out_comparison_v2.json`.
