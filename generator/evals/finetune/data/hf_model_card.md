---
license: cc-by-4.0
language:
- hi
- en
tags:
- sentence-transformers
- sentence-similarity
- feature-extraction
- hinglish
- code-mixed
- romanized-hindi
base_model: l3cube-pune/indic-sentence-bert-nli
pipeline_tag: sentence-similarity
library_name: sentence-transformers
---

# hinglish-relatedness-sbert

A [sentence-transformers](https://www.sbert.net) model for **semantic relatedness between
romanized Hindi ("Hinglish") words and their English counterparts** — fine-tuned from
[l3cube-pune/indic-sentence-bert-nli](https://huggingface.co/l3cube-pune/indic-sentence-bert-nli)
with LoRA + mined hard negatives. Built for [Warmer](https://playwarmer.vercel.app), a
semantic word-guessing game, where it ranks a player's guess against a secret word by
cosine similarity.

**Task:** given two short romanized-Hindi and/or English words/phrases (1-5 tokens), score
how *related* they are — not just synonymous. "weather" and "forecast" should score high
(domain relatedness), matching a WordSim-353-style relatedness notion rather than a strict
SimLex-999 similarity notion. This is a relatedness model, not a pure-synonymy model.

## Why this exists

Off-the-shelf multilingual sentence embedders handle romanized Hindi (Latin-script, not
Devanagari) poorly — a 9-candidate bake-off found every general multilingual model scored
near-random on this input form; `l3cube-pune/indic-sentence-bert-nli` (itself trained on
code-mixed Hindi+English text) was the best off-the-shelf option at Spearman 0.639 on a
25-secret production benchmark. Two straightforward attempts to fine-tune it further by
adding more training data (543 pairs, then 756/1028 pairs) both made held-out performance
*worse* — the classic small-fine-tune overfitting signature. A follow-up diagnostic swept
the training METHOD instead of data volume: 13 capacity-control configs (full fine-tune at
several learning rates, frozen transformer layers, a fresh randomly-initialized projection
head, LoRA at rank 8/16/32) on the *same* fixed dataset. Every full-parameter and
frozen-layer config stayed within noise of the off-the-shelf baseline; every LoRA config
beat it. Layering mined hard negatives onto the best LoRA config (rank 8) pushed held-out
performance further still. **The bottleneck was optimization capacity, not data.**

## Evaluation

**Field-leading claim, on a public, dedicated benchmark**: this model was compared against
7 off-the-shelf alternatives (including 2 released after this project's original bake-off)
on a public, scrubbed, 50-secret held-out set — **this model leads all 7 on both metrics,
CI-significant in all 14 comparisons, zero exceptions** (dim1 semantic-ranking Spearman
**0.675** [95% CI 0.601, 0.741]; dim2 cross-language pass-rate **0.740** [0.62, 0.86]).
Full comparison table and methodology:
[`gauravgandhi2411/hinglish-relatedness-benchmark`](https://huggingface.co/datasets/gauravgandhi2411/hinglish-relatedness-benchmark)
(a public dataset published alongside this model — the reference romanized-Hinglish
relatedness benchmark this field didn't previously have). That benchmark's own dev/test
split achieves dev↔test Pearson r = **0.920** (vs. this earlier ~0.12 problem below),
so checkpoint-selection decisions built on it are now trustworthy in a way the original
held-out split wasn't.

**Original held-out generalization claim** (frozen train/dev/test split of the game's
secret-word schedule, 60 words, 33/11/16 train/dev/test, plus 5 independently-documented
hardest-known cases forced into test — kept below for historical continuity with this
model's original ship decision; superseded as the field-leading claim by the public
benchmark above):

| Metric | Off-the-shelf baseline | This model | Delta (95% paired bootstrap CI) |
|---|---|---|---|
| Semantic-ranking Spearman correlation | 0.4350 | **0.7044** | +0.2694, CI [+0.130, +0.412] (significant) |
| Cross-language consistency (translation lands in the correct similarity band) | 37.5% | **81.25%** | +43.75pp, CI [+18.75pp, +68.75pp] (significant) |
| Regression floor (pairs that flipped correct↔incorrect vs. baseline) | — | net **+7** on both metrics | 9 fixed / 2 broken (ranking); 7 fixed / 0 broken (cross-language) |
| 5 independently-documented hardest cases: cross-language consistency | 0% | **80%** | best prior fine-tune attempt reached 40% |

**Confidence intervals use a paired bootstrap** (the same resampled test items scored by
both models in each draw) rather than comparing two independent confidence intervals —
this removes shared variance and is the statistically appropriate test for "does the
candidate beat the baseline on identical items." The marginal (non-paired) confidence
interval on the baseline alone is considerably wider ([0.223, 0.632]) because that
ranking metric's independent sample size is only 8 word-clusters — a real limitation of
that smaller eval; the public 50-secret benchmark above (42 dim1-eligible secrets) exists
specifically to fix this.

## Method

- **Base:** `l3cube-pune/indic-sentence-bert-nli` (SBERT, mean pooling, 768-dim, BERT-base
  architecture, CC-BY-4.0).
- **LoRA:** rank 8, alpha 16, dropout 0.1, applied to the `query`/`value` projections in
  every self-attention layer only (the base weights stay frozen — 0.12% of parameters
  trainable). This was found to be the decisive fix after full-parameter fine-tuning
  regressed twice.
- **Objective:** joint `MultipleNegativesRankingLoss` (anchor/positive/mined-hard-negative
  triples) + `CosineSimilarityLoss` (graded pairs), 4 epochs, learning rate 2e-4, batch
  size 16, seed 42.
- **Hard-negative mining:** for each anchor/positive training pair, one additional
  negative was mined — a vocabulary word the *off-the-shelf* (pre-fine-tune) model already
  ranked moderately close to the anchor (rank 50-500 out of ~10k words) — genuinely
  confusable rather than a random easy negative. This alone outperformed simply doubling
  the in-batch negative count.

## Training data

756 `(anchor, positive)` contrastive pairs / 1028 graded similarity pairs (0.05-0.95
scored), from 5 sources, all commercial/redistribution-clean:

| Source | License | Graded pairs |
|---|---|---|
| Hand-curated word-relatedness triplets | Original authorship | 108 |
| LLM-augmented pairs, generated locally via Qwen3-8B (Alibaba) | Apache-2.0 | 178 |
| Cross-lingual anchor pairs, hand-curated romanized-Hindi vocabulary | Original authorship | 421 |
| Spelling-alias variants, hand-curated | Original authorship | 32 |
| Corpus co-occurrence (PMI) mining over IndicCorp v2, transliterated via Aksharantar's dictionary + a corpus-occurrence-verified LLM fallback (Qwen3-8B), LLM-judge quality-filtered | IndicCorp v2: CC0 (AI4Bharat). Aksharantar: CC-BY (manually-collected portion) / CC0 (mined portion), AI4Bharat | 325 |
| **Total (deduplicated)** | | **1028** |

Two candidate sources considered during dataset research were **excluded and contributed
nothing** to this model: HingCorpus (CC-BY-NC-SA-4.0 — non-commercial, incompatible with a
CC-BY release) and IndoWordNet (license text states "provided openly for the purpose of
research" — research-only). Every training record was independently checked to exclude
any word from the eval's held-out test/dev split, verified by an automated assertion +
test before training.

## Attribution

This model is a derivative of `l3cube-pune/indic-sentence-bert-nli`
([L3Cube-Pune](https://huggingface.co/l3cube-pune), CC-BY-4.0). Training data derives in
part from **IndicCorp v2** and **Aksharantar** (both [AI4Bharat](https://ai4bharat.iitm.ac.in/)).
LLM-augmented training pairs and one transliteration-fallback path were generated locally
using **Qwen3-8B** (Alibaba, Apache-2.0). Released under **CC-BY-4.0** — attribution to
the above sources required for reuse/redistribution.

## Usage

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("gauravgandhi2411/hinglish-relatedness-sbert")

words = ["namaste", "cricket", "aeroplane"]
embeddings = model.encode(words)

similarities = model.similarity(embeddings, embeddings)
print(similarities)
```

## Intended use

Ranking a small candidate vocabulary (thousands to tens of thousands of short
romanized-Hindi/English words) against a query word by relatedness — e.g. a word-guessing
game's "how warm is this guess" signal. Not evaluated for long-form sentence similarity,
retrieval-augmented generation, or Devanagari-script input (romanized/Latin-script Hindi
only, matching the base model's training distribution).

## Limitations (reported honestly, not smoothed over)

- **Small held-out eval set.** The ranking-correlation metric above is computed over only
  8 independent word-clusters (73 individual scenarios) — the marginal 95% confidence
  interval on the baseline alone is [0.223, 0.632], i.e. wide. The paired-bootstrap
  comparison above is the statistically correct way to read "does this model beat the
  baseline," but readers should not treat 0.7044 as a precise point estimate on a larger
  benchmark.
- **The training loop's own checkpoint-selection metric barely predicts held-out
  performance on the ORIGINAL small split** — across the diagnostic sweep that produced
  this model, the dev-set metric used for early stopping correlated with the held-out
  test metric at only Spearman 0.12 there. **Fixed on the larger public benchmark**
  (dev↔test Pearson r = 0.920, see Evaluation) — a future re-training run should select
  checkpoints against that split, not the original one.
- **The hardest-known cases are improved but not solved.** 5 independently-documented
  hardest word pairs went from a Spearman correlation of ~0 to 0.562 on the ranking metric
  — a large improvement, but still below the 0.7044 full-test-set average, i.e. these
  remain the relatively harder cases even after fine-tuning.
- **Small training set** (1741 total pairs after hard-negative augmentation) relative to a
  ~110M-parameter base model. A learning-curve check found held-out performance still
  rising at 100% of available data — more (real, in-domain) training data would likely
  help further; this was not a data-quality ceiling, LoRA's low effective capacity is what
  made the existing data usable without overfitting.
- **A residual weakness on a specific, characterized (not fully understood) class of
  short/rare romanized words** — the public benchmark localizes this to the
  emotion/nature domains specifically (`junoon`/passion, `registan`/desert being the
  clearest cases). Root cause: these words' own embeddings are dominated by unrelated
  English words sharing a coincidental subword-tokenization fragment (e.g.
  `junoon`→afternoon/noon/june) — likely a mix of a base-tokenizer artifact and genuine
  associative/world-knowledge relatedness this distributional approach doesn't capture
  for free. **Tested and ruled out**: more of the same style of hard-negative training
  data at the current LoRA capacity does not reliably fix this (a targeted probe on 9
  words with the same signature came back statistically null/directionally negative).
  This is an open, characterized boundary with untested next-attack candidates (higher
  LoRA capacity, retrieval-time reranking, a base model with better romanized-Hindi
  tokenization, real player-guess data post-launch) — not a closed, believed-unfixable
  limitation. Full detail: this project's `docs/known-limitations.md` entry 20.

## Citation

If you use this model, please cite the base model and the data sources above per their
licenses. This fine-tune itself has no associated paper.
