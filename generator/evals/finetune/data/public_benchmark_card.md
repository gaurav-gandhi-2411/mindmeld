---
license: cc-by-4.0
language:
- hi
- en
tags:
- hinglish
- code-mixed
- romanized-hindi
- semantic-relatedness
- word-similarity
- benchmark
task_categories:
- sentence-similarity
pretty_name: Hinglish Relatedness Benchmark
---

# Hinglish Relatedness Benchmark

A practical, reproducible, **AI-authored** romanized-Hinglish (Latin-script Hindi-English)
semantic-relatedness benchmark: 34 secret words across 7 domains (nature, emotion,
abstract, object, place, food, kinship), each with tiered near/mid/far associate words
scored for expected relatedness band, plus a parallel English-language version and
cross-lingual translation-consistency pairs.

**This is not a peer-reviewed gold standard.** It is a small, honestly-sourced, methodologically
transparent benchmark built to fill a real gap: no public romanized-Hinglish relatedness
benchmark exists to compare against. Report weaknesses and residuals when you use it — that's
the standard this card holds itself to.

## What's in it

| File | Records | Purpose |
|---|---|---|
| `dim1_hien.json` | 302 | Headline metric: romanized-Hindi secret -> near/mid/far tiered associate words, English-side associates included, translation-tagged where applicable |
| `dim1_en.json` | 303 | Parallel English-language version of the same 34 secrets/tiers |
| `dim2_pairs.json` | 34 | Secondary metric: cross-lingual (hi-en secret, EN translation) consistency pairs |
| `public_benchmark_split.json` | — | Domain-stratified dev/test split (17/17), seed=42, for checkpoint selection |

Each `dim1_*` record: `{secret, word, tier (near/mid/far), expected_bands, subtype, note}`.
Each `dim2_pairs` record: `{hien_secret, en_gloss, domain}`.

## Provenance — read this before citing "expert-annotated"

This benchmark is **majority AI-authored content**, not independently human-annotated, not
externally-sourced commercial data, and not a crowd-sourced or academically-validated
dataset:

- **Near/mid tier word associations** (the semantically load-bearing part): hand-authored as
  literal code by an AI coding assistant (Claude, Anthropic) during this project's
  development. Spot-checked by the project owner at specific review gates (e.g. a
  homograph-collision audit on the earlier 25-secret core set), **not independently
  re-annotated word-by-word by a human linguist.**
- **Far-tier filler words**: mechanically sampled via a hash-seeded RNG over the project's
  own vocabulary — not curated at all, by design; their only intended property is
  "not near/mid," verified after the fact.
- **Safety-scrub and semantic-proximity review**: an AI coding-assistant subagent ran an
  automated string-collision scrub and a semantic-proximity scan (embedding-rank based)
  against all live game content, fixed 17 real string collisions and 20 semantic near-misses,
  all disclosed with before/after word tables in the full Phase 1 report (see Reproducibility).

**Do not describe this dataset as "human-annotated" or "expert-annotated" in the sense of an
independent linguist's judgment.** It is AI-authored, methodologically rigorous (documented
tiering discipline, verified vocabulary membership, two independent scrub passes), and
transparently disclosed as such.

## Attribution

- Base romanized-Hindi vocabulary and transliteration resources build on
  [AI4Bharat's Aksharantar](https://huggingface.co/datasets/ai4bharat/Aksharantar) and
  IndicCorp v2 (CC0), used earlier in this project's data pipeline.
- The reference fine-tuned model this benchmark evaluates,
  [gauravgandhi2411/hinglish-relatedness-sbert](https://huggingface.co/gauravgandhi2411/hinglish-relatedness-sbert),
  is built on [L3Cube's indic-sentence-bert-nli](https://huggingface.co/l3cube-pune/indic-sentence-bert-nli).
  Neither L3Cube nor AI4Bharat authored or reviewed this specific benchmark's word pairs.

License: **CC-BY-4.0**. Attribution to this project (Warmer / gauravgandhi2411) requested.

## Headline metric: dim1 (semantic-ranking quality)

Spearman rank correlation between expected closeness tier (near/mid/far) and a model's
actual embedding-rank, pooled per secret. Dev/test split (17/17, domain-stratified, seed=42)
was built to fix a known problem in this project's earlier, smaller held-out set (dev-test
Pearson correlation only ~0.12, i.e. dev performance barely predicted test performance,
making checkpoint selection untrustworthy). Measured on this split: **dev<->test Pearson
r = 0.894 (n=8 models)** — dev now materially predicts test.

Reference model (`gauravgandhi2411/hinglish-relatedness-sbert`) dim1 Spearman: **0.656
[95% CI 0.569, 0.735]** full 34-secret set (0.671 dev-only, 0.641 test-only — CI-overlapping,
stable across the split).

## Secondary metric: dim2 (cross-lingual consistency) — honest cluster-dependence

Dim2 measures whether a secret's correct English translation lands in the expected
relatedness band. **This metric is noticeably less stable across domains than dim1**, and
degrades in specific, identifiable clusters rather than uniformly.

**Methodology note (found during Phase 1 review, corrected before this was final)**: 2 of
the 34 secrets (`paneer`, `khichdi`) are loanwords spelled identically in both languages —
their EN gloss and hi-en secret are the literal same string, so they trivially self-match
at rank 1 ("win" band). The pass/fail definition here treats only bands 1-2 ("scorching"/
"hot") as consistent, deliberately excluding band 0 to prevent literal string duplicates
from gaming the metric in the general case — but for a genuinely-identical loanword pair
this excludes the ONE correct outcome, scoring a trivial self-match as a "failure." These 2
items are not a meaningful test of cross-lingual understanding either way (a lookup table
scores them identically) and are excluded from the domain rates below, which reflect only
the 32 informative (non-degenerate) pairs.

| Domain | Fail rate (32 informative pairs, n=3-5/domain) |
|---|---|
| emotion | 2/5 (40%) |
| nature | 2/5 (40%) |
| food | 1/3 (33%)* |
| kinship | 1/4 (25%) |
| place | 1/5 (20%) |
| object | 1/5 (20%) |
| **abstract** | **0/5 (0%)** |

*food's denominator is 3, not 5 — `paneer`/`khichdi` excluded as degenerate, see above.

**Emotion and nature cluster weakest, food closely behind at a much smaller informative
n**; abstract and object cluster strongest (abstract is, in fact, perfect on this small
sample). Read this as **soft cluster (food/nature/emotion — concrete-sensory, culturally-
specific concepts) vs. strong cluster (abstract/object/place/kinship), not a precise rank
order within the soft cluster** — at n=3-5 secrets per domain this is a
directional signal, not a statistically tight one — a single item flipping changes a
domain's rate by 20-25 points. Reported honestly rather than smoothed into a single
aggregate pass-rate (0.706 [0.559, 0.853] overall), which would hide this structure.

## Scrub / safety notice (for anyone extending this benchmark)

Every secret and associate word was checked against this project's live game content
(daily-schedule secrets, all themed-pack secrets, aliases) two ways: string/morphological
collision, and embedding-rank semantic proximity. Zero blocking collisions of either kind
remain in the published files. Full methodology, the calibration analysis behind the
semantic-proximity check's severity thresholds, and every word substitution made (37 total
across both scrub passes) are documented in the full Phase 1 report (Reproducibility below).

## Reproducibility

Full methodology, all intermediate numbers, the complete word-substitution history, and the
scrub calibration analysis: `public_benchmark_phase1_report.md` in the source repository
(`gauravgandhi2411/mindmeld`, `generator/evals/finetune/data/`). Split seed 42 throughout.
