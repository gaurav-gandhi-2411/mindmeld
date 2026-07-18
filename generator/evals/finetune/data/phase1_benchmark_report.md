# Hinglish Relatedness — Phase 1 Benchmark Report

Spec: `spec-hinglish-benchmark.md`. Branch `feat/hinglish-finetune`, commits
`16f35d1` (RNG fix) -> `704cabd` (held-out expansion) -> `d73db64` (8-model
bake-off) -> `78df6f2` (vocab-coverage fix + rerun, final numbers below).

## Guiding principle, restated

"Best out there" is a comparative, statistically-trustworthy claim, not an
assertion. This report exists to make that claim measurable before Phase 2
pushes accuracy further. **Verdict: the shipped model leads every
alternative tested, by a CI-significant margin, on both dimensions. No
newer base model beats it.**

---

## 1a — Expanded, stabilized held-out eval

### The blocking bug, fixed first

`gen_dim1_scenarios.py`'s far-tier word sampler used one shared,
sequentially-advanced `random.Random(42)` across all 25 secrets in sorted
order — adding any new secret would silently shift every other secret's
far-tier draw, corrupting the checked-in `baseline_report.md` numbers
without any visible signal. Fixed (`16f35d1`) with a per-secret
hash-derived RNG, independent of iteration order or which other secrets
exist. This is a one-time, deliberate, documented break of the old
(buggy) numbers, not a silent regression:

| Metric | Before fix | After fix |
|---|---|---|
| Full-set EN dim1 Spearman | 0.837 | 0.842 |
| Full-set hi-en dim1 Spearman | 0.800 | 0.813 |
| EN monotonicity violations | 6.2% | 5.9% |
| hi-en monotonicity violations | 5.5% | 6.7% |
| dim2 cross-lang pass-rate | 78.0% | 78.0% (unaffected — dim2 never reads dim1 scenarios) |

Full test suite: 458 passed/4 skipped before and after (2 unrelated,
pre-existing Ollama-availability errors in `tests/test_harness_judge.py`,
independently reproduced and confirmed unrelated to this change — see
"Known issues" below).

### Expansion: 16 -> 50 held-out test secrets

Added 34 brand-new secrets across the 7 required domains (`704cabd`), kept
**fully separate** from the production 25-secret/60-word daily-schedule
pipeline (own curated-scenario module, own split-export path) so
`baseline_report.md`'s full-production-set scope is completely unchanged
by this expansion:

| Domain | Secrets added (hien / EN gloss) |
|---|---|
| nature (5) | registan/desert, jheel/lake, chattan/rock, dhoop/sunlight, patta/leaf |
| emotion (5) | sharm/shyness, chinta/worry, mazaa/enjoyment, junoon/passion, udaasi/sadness |
| abstract (5) | azaadi/freedom, insaaf/justice, waqt/duration, sawaal/question, kanoon/law |
| object (5) | chaabi/key, sandook/trunk, thaali/platter, tokri/basket, chimni/chimney |
| place (5) | sadak/road, sarhad/border, basti/settlement, mohalla/neighborhood, dehat/countryside |
| food (5) | mithai/dessert, dahi/yogurt, paneer/paneer, besan/gram, khichdi/khichdi |
| kinship (4) | mausi/auntie, bhanja/nephew, bhanji/niece, judwaa/twin |

`test_secrets`: 16 -> **50**. `held_out_secrets` (dev union test): 27 -> **61**.

**No-leakage discipline, verified twice**: every one of the 34 secrets and
every one of their curated near/mid neighbor words (192 distinct tokens)
was checked by direct case-insensitive membership grep against all 5
assembled training files (`train_mnrl_pairs*.jsonl`,
`train_graded_pairs*.jsonl`, raw and cleaned variants) — zero hits, twice
(once during curation, once independently post-integration, and a third
time independently by me, sampling 8 of the 34 secrets directly against
the training files with zero hits). `tests/test_finetune_no_leakage.py`
passes 3/3 against the enlarged set.

**Important, deliberately-verified finding**: the game's existing
Bollywood/Cricket theme packs were considered and **rejected** as an
"unused-secret" source — direct grep found ~24/25 Bollywood and ~21+/25
Cricket pack secrets already present in the assembled training data (via
the open-vocabulary `crosslingual_source`/`corpus_pmi_source`/
`llm_augment.py` paths, which scope only against the 60-word daily
schedule, not against pack secrets). Reusing them would have silently
contaminated the "held-out" claim. The 34 new secrets are either brand-new
to `vocab/hinglish.txt` or drawn from the two `status: "coming_soon"`,
zero-secret packs (Indian Food, Nature & Wild) — genuinely never seen by
training in any form.

### Data-quality gap found and fixed during my own review

Independently re-checking the first bake-off pass, I found 45/379 (12%) of
dim1 scenarios unresolvable (`resolution_error: "... not in vocab"`), 100%
concentrated in near/mid tiers of the new secrets (27 near + 18 mid, 0
far) — 42 curated near/mid English words (e.g. "hamlet", "legume",
"boulder", "curd", "meadow", "checkpoint") were real, already
leak-verified words that simply fell outside `HIEN_EN_TOP_N=10,000`'s
wordfreq-frequency cutoff, so were absent from the embeddable hi-en
vocabulary entirely — a resolvability gap, not a leakage gap. This
affected all 8 models identically (same vocab for every model, so the
comparison was still fair) but weakened confidence in the near-tier
numbers specifically, since near-tier is the most diagnostic part of the
benchmark. Fixed (`78df6f2`) by moving those 42 words to the front of
`vocab/en.txt` (same mechanism already used for `paneer`/`khichdi` during
curation) and re-ran the full 8-model bake-off. Resolution: dim1
334/379 -> **376/379 (99.2%)**; dim2 45/50 -> **50/50 (100%)**.

**Residual, honestly reported, not chased further**: 3/379 dim1 scenarios
remain unresolved (`basti`/migrant, `judwaa`/retailer, `udaasi`/pleasing)
— same root cause (just past the 10k cutoff) but outside the audited
42-word list; two of the three are far-tier words auto-sampled from the
wrong vocab source (`load_en_vocab()`'s full 55k list rather than the
capped hi-en vocab) in `gen_dim1_benchmark_supplement.py`, a small,
separate bug. At 99.2% resolution with an unambiguous statistical result,
I judged chasing the last 0.8% not worth another ~36-minute, 8-model
re-embedding cycle (diminishing returns, per the spec's own risk
framing) — flagging rather than silently declaring 100%.

**A second, more consequential bug surfaced as a side effect** (found,
worked around, NOT fixed — out of this phase's scope, needs a decision):
`embeddings.py`'s cache key hashes `(model_name, sorted(vocab))` so that
"insertion-order changes don't bust the cache" — but the cached matrix's
rows are laid out in the model's actual *encode-time* list order, not
sorted order. Reordering `en.txt` with an unchanged word set (exactly
what the vocab fix did) left the cache key unchanged, so a stale cached
matrix was silently served with rows in the wrong order — production EN
dim1 Spearman appeared to collapse to 0.165 transiently until I traced it
to the stale `.model-cache/*.npy` file and deleted it (regenerated
cleanly, confirmed `baseline_report.md`'s committed 0.842/0.813 numbers
are correct and untouched by this). **This is a latent correctness bug in
a production module** (`generator/embeddings.py`) that could silently
misalign a cached embedding matrix any time the vocab file is reordered
without changing its word set — it has not (to my knowledge) manifested
in a real deploy, but it is a real risk given `payload` generation reads
from the same cache. Flagging for your decision on priority; not fixed
here since it touches the production embedding pipeline and warrants its
own careful before/after payload-byte verification, out of scope for a
benchmark-only phase.

### Bootstrap CI methodology

Cluster-by-secret (dim1) / cluster-by-pair (dim2), `n_boot=10,000`,
`seed=42`. Marginal CI resamples cluster identities with replacement;
paired CI (used for every leadership claim below) resamples **the same**
secret/pair multiset for both models in each of the 10,000 draws,
removing shared variance — the correct test for "does the candidate beat
the incumbent on the same items," and much tighter than two independent
marginal CIs.

**Min CI-significant delta observed in this run**: the tightest
CI-significant paired delta among all 14 comparisons below is dim1
+0.2035 [+0.112, +0.298] (shipped vs. l3cube-pune base) — deltas below
roughly ±0.11 on dim1 (at n=42 secret clusters) or wider for dim2 (at
n=50 pair clusters, tightest observed ±0.12) should be treated as noise,
not signal, in any Phase 2 comparison against this same held-out set.

---

## 1b — Comparative bake-off vs. the field

8 models, same expanded held-out set (42 dim1-eligible secrets / 376
resolved scenarios, 50/50 resolved dim2 pairs), plain `model.encode(vocab)`
for every model — **no per-model instruction/prefix prompting** (e.g.
e5's "query:"/"passage:" convention, Qwen3's instruction-aware prompting),
matching how `embeddings.py` actually calls models in production and how
the original 9-candidate bake-off (`PLAN.md`) treated every candidate
("raw romanized" input, uniformly). This measures true drop-in
replaceability, not each model's best-case published number — Qwen3-Embedding
and e5-large in particular likely score below their MTEB leaderboard
figures here for exactly this reason; noted as a limitation, not a flaw
in those models generally.

| model | dim1 Spearman [95% CI] | dim2 pass-rate [95% CI] | band-acc (overall/near/mid/far) | near/far sep. | delta vs. shipped |
|---|---|---|---|---|---|
| paraphrase-multilingual-MiniLM-L12-v2 | -0.024 [-0.140, 0.095] | 0.000 [0.00, 0.00] | 0.533 / 0.012 / 0.000 / 0.957 | 0.022 | dim1 **+0.699** (sig.); dim2 **+0.740** (sig.) |
| l3cube-pune/indic-sentence-bert-nli (fine-tune base, off-the-shelf) | 0.471 [0.360, 0.571] | 0.420 [0.28, 0.56] | 0.609 / 0.393 / 0.000 / 0.943 | 0.332 | dim1 **+0.204** (sig.); dim2 **+0.320** (sig.) |
| google/muril-base-cased | 0.202 [0.089, 0.311] | 0.500 [0.36, 0.64] | 0.591 / 0.321 / 0.012 / 0.933 | 0.178 | dim1 **+0.473** (sig.); dim2 **+0.240** (sig.) |
| BAAI/bge-m3 | 0.114 [0.014, 0.215] | 0.100 [0.02, 0.20] | 0.554 / 0.095 / 0.012 / 0.957 | 0.079 | dim1 **+0.561** (sig.); dim2 **+0.640** (sig.) |
| intfloat/multilingual-e5-large | 0.179 [0.053, 0.303] | 0.100 [0.02, 0.20] | 0.570 / 0.131 / 0.000 / 0.976 | 0.129 | dim1 **+0.496** (sig.); dim2 **+0.640** (sig.) |
| ibm-granite/granite-embedding-311m-multilingual-r2 *(newer, 2026-05)* | 0.160 [0.045, 0.270] | 0.080 [0.02, 0.16] | 0.559 / 0.095 / 0.000 / 0.971 | 0.102 | dim1 **+0.515** (sig.); dim2 **+0.660** (sig.) |
| Qwen/Qwen3-Embedding-0.6B *(newer, 2025-06)* | 0.177 [0.065, 0.291] | 0.140 [0.06, 0.24] | 0.562 / 0.167 / 0.000 / 0.948 | 0.142 | dim1 **+0.498** (sig.); dim2 **+0.600** (sig.) |
| **gauravgandhi2411/hinglish-relatedness-sbert (shipped, ours)** | **0.675 [0.601, 0.741]** | **0.740 [0.62, 0.86]** | **0.673 / 0.655 / 0.012 / 0.948** | **0.448** | — |

All 14 paired-bootstrap comparisons (7 models x 2 dimensions):
`ci_significant_improvement = True`, `ci_significant_regression = False`,
zero exceptions. Every model, including both newer 2025/2026 candidates,
loaded and embedded successfully — none skipped or excluded from the table.

### Explicit verdict

1. **We are leading, and it is CI-significant.** The shipped fine-tune
   beats all 7 alternatives on both dim1 Spearman and dim2 pass-rate, with
   95% CI lower bounds strictly above zero in every one of 14 comparisons.
2. **Closest competitor: `l3cube-pune/indic-sentence-bert-nli`** — the
   same base model we already fine-tune, off-the-shelf. Its off-the-shelf
   dim1 (0.471) is also the *strongest of all 7 off-the-shelf candidates*,
   including both newer entrants — confirming it remains the best
   available foundation.
3. **No newer base model is worth fine-tuning instead.** IBM Granite
   embedding-311m-r2 (Apache 2.0, 2026-05) and Qwen3-Embedding-0.6B
   (Apache 2.0, 2025-06) were the two most promising newer candidates
   identified by a fresh HF/MTEB search (both clean-licensed, both
   sentence-transformers-loadable with no `trust_remote_code`) — both
   scored well below l3cube-pune off-the-shelf on this Hinglish-specific
   benchmark (dim1 0.160 and 0.177 respectively, vs. l3cube's 0.471).
   General multilingual MTEB strength does not transfer to romanized
   Hinglish relatedness — consistent with the original bake-off's root
   finding that Devanagari-trained multilingual encoders fail on
   romanized script specifically. **Phase 2c's "fine-tune a newer base"
   branch does not apply — stick with l3cube-pune.**
4. A third candidate, `ai4bharat/IndicBERT-v3-1B` (MIT, 2026-01, trained
   partly on the same IndicCorp v2 corpus this project already uses), was
   considered but excluded from this table — it has no released
   sentence-embedding head yet (base LM only), so it isn't a fair
   off-the-shelf comparison. It remains a candidate *fine-tuning base* for
   a future Phase 2 experiment, not a Phase 1 entrant.
5. `jinaai/jina-embeddings-v3` was excluded outright — CC BY-NC 4.0,
   non-commercial-only, incompatible with this product's licensing
   requirements.

### Known issues carried forward, not fixed in this phase

- `tests/test_harness_judge.py`'s two Ollama-dependent calibration tests:
  pre-existing, reproducible ~30s-to-30min timeout depending on whether a
  concurrent process holds the local Ollama server; confirmed unrelated to
  any change in this phase (never touched judge/LLM code). Also found: the
  test's self-skip logic can *hang* rather than skip if Ollama is
  reachable but the actual generate call stalls — worth a ticket.
- `embeddings.py` cache-key/row-order latent bug (see above) — real,
  contained, not yet fixed, needs a decision on priority.
- 3/379 dim1 scenarios still unresolved (99.2% overall resolution) — same
  root cause as the fixed 42, different specific words; low priority given
  the statistical margin already achieved.
- `generator/evals/finetune/data/hf_model_card.md`'s published held-out
  table (0.4350->0.7044 dim1, 0.375->0.8125 dim2, on the OLD 16-secret set
  and the OLD buggy scenario RNG) is now stale on two counts: the RNG fix
  changed the numbers even on the old 16-secret set (now 0.4275->0.7613),
  and this phase's proper comparator is the new 50-secret set (0.675
  dim1 / 0.740 dim2, tighter CIs, n=42 clusters vs. the old n=8). **No
  HF Hub push was made** (would need `HF_TOKEN`, a deliberate publish
  decision, and is arguably better bundled with Phase 2 if that phase also
  changes the model) — flagging for your call on timing.

---

## 1c — Public benchmark: proposal only, not published

A genuine gap exists: no strong public romanized-Hinglish relatedness
benchmark currently exists. Proposing (not doing) the following, pending
your explicit confirmation of the scrub per the spec's mandatory gate:

- **Package**: the 50-secret held-out set's scenarios/pairs (dim1 + dim2),
  the 8-model comparison table, and the bootstrap CI methodology, as a
  small HF Datasets repo + a short paper-style README.
- **Scrub requirement, and an important asymmetry to flag**: the ORIGINAL
  16 test secrets are real, currently-live Warmer daily-schedule game
  secrets — publishing their near/mid/far scenario words would leak actual
  game answers and must be excluded or scrubbed. The **34 NEW secrets are
  categorically safer** — they were deliberately built as a
  benchmark-only track, kept out of the daily schedule and every pack, and
  are not (and per this design, cannot silently become) live game secrets.
  A defensible minimal-risk publish would be the **34-secret supplement
  only**, explicitly excluding the original 16 — still several-fold over
  the old n=16 in absolute size, zero game-secret exposure, no scrub
  ambiguity.
- **License/attribution**: CC-BY-4.0, matching the shipped model's license;
  attribution to this project.
- **Explicit gate, per spec**: do not publish anything until you confirm
  the scrub scope (34-only vs. some scrubbed version of all 50) and the
  license choice.

---

## Acceptance criteria checklist

1. Expanded held-out eval, n reported, several-fold over 16: **done** (50
   test secrets, 3.1x; 376/379 dim1 scenarios and 50/50 dim2 pairs
   resolved; all metrics with bootstrap 95% CIs; min CI-significant delta
   stated above).
2. Comparison table, >= 6 models (old baselines + newer), explicit
   leadership verdict: **done** (8 models; shipped model leads all 7 with
   CI-significance on both dimensions; closest competitor and "any newer
   base worth fine-tuning" both explicitly answered).
3. Public benchmark: **proposed, not published** — awaiting your scrub/
   license confirmation per the spec's mandatory gate.
4. Frozen no-leakage discipline: **preserved** (`tests/test_finetune_no_leakage.py`
   3/3, independently re-verified by direct grep against all 5 training
   files for a sample of new secrets).
5. EN unchanged: **confirmed** (`config.py` byte-identical throughout;
   EN's only apparent regression was a transient stale-cache artifact in
   my own review process, traced, fixed, and confirmed not to have reached
   any committed file).
6. Full suite green throughout: **474 passed / 4 skipped** (Ollama-judge
   tests excluded per the documented, pre-existing, independently-confirmed
   unrelated flakiness above); every experiment logged and rerunnable
   (`bakeoff_raw/*.json` per-model checkpoints, `method_sweep_results.jsonl`
   precedent pattern followed).

## STOP — awaiting GG's go before Phase 2

Per the spec: Phase 1 is complete and the benchmark is trustworthy. Do NOT
proceed to Phase 2 (accuracy push) without explicit confirmation, since
Phase 2's plan (LoRA sweep on the current l3cube-pune base, more data,
residual-cluster work) is validated by this report's finding that no newer
base beats the current one — but the two flagged issues (embeddings.py
cache bug, HF model card staleness, public-benchmark scrub scope) are
decisions for you, not calls I should make unilaterally.
