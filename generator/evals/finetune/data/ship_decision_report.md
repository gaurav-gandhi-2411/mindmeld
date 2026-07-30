# Hinglish Embedding Fine-Tune — Ship Decision Report

Base model: `l3cube-pune/indic-sentence-bert-nli` (off-the-shelf champion, Spearman 0.639
on the full 25-secret / 227-scenario production dim1 set, per `evals/reports/baseline_report.md`).
Fine-tune recipe: `evals/finetune/train.py`, seed 42, reproducible from committed data.

## Split (frozen, no leakage — see `data/split.json`)

60 daily-schedule hi-en secrets -> 33 train / 11 dev / 16 test. The 5 documented residual-weak
secrets (titli, khamoshi, rasoi, samunder, bachpan) forced into test. All training data
(543 MNRL pairs, 705 graded pairs, 4 sources) asserted to exclude every held-out secret and its
EN translation — see `data/counts.json` / `tests/test_finetune_no_leakage.py`.

## Training

SBERT contrastive fine-tune, `MultipleNegativesRankingLoss` (MNRL dataset) +
`CosineSimilarityLoss` (graded dataset), 4 epochs, lr=2e-5, batch=16, warmup_ratio=0.1,
early-stopping patience=2 on a DEV-only evaluator. Dev-curve (`data/dev_curve.json`):
spearman_cosine 0.840 -> 0.833 -> 0.845 -> 0.842 across epochs 1-4 (best: epoch 3, loaded
via `load_best_model_at_end`). No runaway divergence; conservative hyperparameters held.

## Held-out TEST results (the only reportable numbers — never train)

Restricted to the 16 frozen TEST secrets (8 of which have dim1 curated scenarios; all 16
have dim2 cross-lingual pairs), comparing the SAME off-the-shelf baseline against the
fine-tuned checkpoint on identical held-out data:

| Metric | Baseline (off-the-shelf) | Fine-tuned | Delta |
|---|---|---|---|
| dim1_test Spearman (n=73 scenarios, 8 secrets) | 0.4350 | 0.3764 | **-0.0586 (worse)** |
| dim1_test band-accuracy overall | 0.6027 | 0.5753 | **-0.027 (worse)** |
| dim1_test near/translation-tier accuracy (n=7) | 0.5714 | 0.4286 | **-0.143 (worse)** |
| dim1_test near/associate-tier accuracy (n=9) | 0.2222 | 0.2222 | unchanged |
| dim2_test pass-rate Scorching/Hot (n=16 pairs) | 0.3750 | 0.3750 | unchanged |
| dim2_test median rank percentile (lower=better) | 5.31 | 9.66 | **worse (~2x farther)** |

For reference only (DEV, never reported as a result — used solely for checkpoint
selection): dim1_dev Spearman 0.7808 -> 0.8378 (improved), dim2_dev pass-rate 0.70 -> 0.80
(improved). **This dev-only improvement without matching test improvement is exactly the
overfitting signature spec-hinglish-finetune.md warned about** — the fine-tune adapted to
the dev-adjacent lexical neighborhood without generalizing to genuinely unseen test words.

## Regression floor (per-pair, TEST split only)

- dim1_test: 3 pairs fixed (wrong->right) — `bachpan/childhood`, `bachpan/notch`,
  `samunder/jimmy` — vs. **5 pairs broken (right->wrong)**: `chaand/moon`, `khazana/treasure`,
  `phool/walsh`, `samunder/wave`, `samunder/btw`. **Net -2, regression floor FAILS.**
- dim2_test: 2 pairs fixed (`kitchen->rasoi`, `childhood->bachpan`) vs. **2 pairs broken**
  (`treasure->khazana`, `moon->chaand`) — net 0, but real previously-working pairs were
  broken, which fails "zero net regression" on its own terms regardless of the net count.

## Residual weak pairs (titli, khamoshi, rasoi, samunder, bachpan — held out, never trained)

| Pair | Baseline rank (band) | Fine-tuned rank (band) | Status |
|---|---|---|---|
| rasoi<-kitchen | 6393 (Freezing) | 367 (Hot) | **FIXED** |
| bachpan<-childhood | 3773 (Freezing) | 184 (Hot) | **FIXED** |
| khamoshi<-silence | 8244 (Freezing) | 1654 (Cold) | improved, still fails |
| titli<-butterfly | 3761 (Freezing) | 2784 (Freezing) | still fails |
| samunder<-ocean | 3809 (Freezing) | 5224 (Freezing) | **worse** |

dim2 pass-rate on this subset: 0.0 -> 0.4 (2 of 5 now pass) — the one genuinely encouraging
signal, but it doesn't offset the broader regression on pairs the harness didn't specifically
target, and the ship gate requires ALL criteria, not a favorable subset.

## EN-unchanged proof

The fine-tune pipeline never reads or writes `config.MODELS["en"]` — `eval_model.py`'s
`_model_override` context manager only ever touches the `"hi-en"` key, and `train.py` only
ever loads/saves the hi-en checkpoint. Verified: `config.MODELS["en"]` ==
`"sentence-transformers/all-MiniLM-L6-v2"`, byte-identical to before this session, by
construction (no code path touches it) — not just by re-running the EN eval.

## SHIP DECISION: **DO NOT SHIP**

Against the stated ship criteria (spec-hinglish-finetune.md):

1. Held-out test Spearman meaningfully > baseline — **FAILS** (0.376 < 0.435 baseline; a
   regression, not an improvement, on this restricted-but-honest held-out sample).
2. Cross-language consistency improved — **FAILS** (flat pass-rate, worse median rank).
3. Zero net regression on currently-working pairs — **FAILS** (5 dim1 pairs broken, 2 dim2
   pairs broken that were previously fine).

All three primary gates fail. Per spec: *"If any fails -> DON'T ship the fine-tune; keep
off-the-shelf and report why."* The off-the-shelf `l3cube-pune/indic-sentence-bert-nli`
stays in production. `docs/known-limitations.md` entry #1 is updated to record this
attempt and result, not silently dropped.

## Why it likely failed (documented next step, not a hidden failure)

543 MNRL / 705 graded training pairs is small relative to a 197k-vocab multilingual BERT-base
model (~110M non-embedding params). The dev/test improvement split is the classic signature
of a fine-tune that nudges embeddings toward the specific words it saw (and their close
neighbors, which is why the residual-weak pairs sharing training-adjacent vocabulary
improved) while degrading calibration for the many words the off-the-shelf model already
had correctly placed. Likely next steps if this is revisited: substantially more training
data (the spec's "thousands of pairs" target was only partially reached — cross-lingual
pairs from hinglish.txt dominate at 421/543, LLM-augmentation contributed only 89 after
quality/homograph filtering), a lower learning rate or fewer epochs, stronger regularization
(e.g. freezing lower transformer layers), or LoRA to reduce the effective parameter budget
being moved. None of these were attempted in this session — the honest result is reported
as-is rather than iterated on until a number looked good, per the cardinal rule.

## Reproducibility

Recipe fully committed: `evals/finetune/{split,assemble_data,llm_augment,homograph_audit,
train,eval_model}.py`, frozen split (`data/split.json`), assembled training data
(`data/train_{mnrl,graded}_pairs.jsonl`), cached LLM triplets
(`data/llm_triplets_accepted.json`), homograph audit (`data/homograph_exclusions.json`).
Seed 42 throughout. The trained checkpoint itself (913MB) and training checkpoints (5.4GB)
are NOT committed (gitignored) since nothing shipped — re-running
`uv run python -m evals.finetune.train` against the committed data reproduces the same
result bit-for-bit-modulo-hardware.
