# Public Hinglish-Relatedness Benchmark — Phase 1 Report

Spec: `spec-hinglish-benchmark.md`, section "1c — Public benchmark". Branch
`feat/hinglish-finetune`, this session (built on top of an interrupted prior
attempt at `evals/finetune/data/public_benchmark_staging/`, treated as
legitimate prior progress per GG's status-check confirmation, not discarded).

New/changed in this session:
- `evals/finetune/data/public_benchmark_staging/dim1_en.json`,
  `dim1_hien.json`, `dim2_pairs.json` — completed to the full 34-secret set
  (was 31/34) and fixed 16 blocking safety-scrub collisions (see below).
- `evals/finetune/scrub_public_benchmark.py` — new safety-gate script.
- `evals/finetune/public_benchmark_split.py` — new dev/test split builder.
- `evals/finetune/public_benchmark_analysis.py` — new dev/test-correlation
  + bootstrap-CI analysis, reading only already-computed bake-off data.
- `evals/finetune/data/public_benchmark_split.json`,
  `public_benchmark_analysis.json` — generated outputs of the above two.
- `tests/test_scrub_public_benchmark.py`,
  `tests/test_public_benchmark_split.py`,
  `tests/test_public_benchmark_analysis.py` — new test coverage.

---

## 1. Benchmark size and domain breakdown

**34 secrets, 7 domains** — the full benchmark-only supplement from
`phase1_benchmark_report.md`'s "Expansion: 16 -> 50" table, now completely
represented in the public-facing staging files (previously 31/34; this
session added `junoon`/passion, `insaaf`/justice, `udaasi`/sadness, the 3
secrets missing from the interrupted draft).

| Domain | n secrets | hien secrets |
|---|---|---|
| nature | 5 | registan, jheel, chattan, dhoop, patta |
| emotion | 5 | sharm, chinta, mazaa, junoon, udaasi |
| abstract | 5 | azaadi, insaaf, waqt, sawaal, kanoon |
| object | 5 | chaabi, sandook, thaali, tokri, chimni |
| place | 5 | sadak, sarhad, basti, mohalla, dehat |
| food | 5 | mithai, dahi, paneer, besan, khichdi |
| kinship | 4 | mausi, bhanja, bhanji, judwaa |
| **total** | **34** | |

Dataset file sizes:

| File | n records | n secrets | notes |
|---|---|---|---|
| `dim1_en.json` | 303 | 34 | EN-gloss scenarios; tiers: 67 near / 68 mid / 168 far |
| `dim1_hien.json` | 301 | 34 | hi-en scenarios; tiers: 67 near / 68 mid / 166 far |
| `dim2_pairs.json` | 34 | 34 | one cross-lingual (hien_secret, en_gloss) pair per secret |

The 3 newly-added secrets' near/mid tiers and far-tier fillers were taken
**verbatim from the already-generated, already-verified production
scenario files** (`evals/scenarios/dim1_benchmark_supplement_{en,hien}.json`,
produced by `evals/gen_dim1_benchmark_supplement.py` — the same module that
generated the OTHER 31 secrets already in staging, and the exact source
`benchmark_bakeoff.py` reads for the real 8-model bake-off numbers already
reported in `phase1_benchmark_report.md`). This guarantees the 3 new
secrets' words are the identical words already embedded and scored in that
bake-off — not new, unverified content — with one exception: `udaasi`'s
far-tier word `pleasing` is a documented residual-unresolved word from the
production report ("3/379 dim1 scenarios remain unresolved ... udaasi/
pleasing"), confirmed still unresolvable in the current hi-en vocab
(`'pleasing' in load_hien_vocab()` → `False`), so it was swapped for a
verified in-vocab far-tier word before publication consideration (see next
section for why that swap needed a second attempt).

---

## 2. Scrub verification (safety gate)

**Script**: `evals/finetune/scrub_public_benchmark.py`
**Result**: **PASS** — 0 blocking collisions.

```
scrub scan: 34 secrets, 1276 benchmark word instances checked
  (521 distinct) against 256 live-content items
  (205 distinct: daily schedule x2 langs + every pack x lang + aliases)
scrub scan OK: 0 blocking collisions between the public benchmark and
  live game content (539 advisory hits reported, non-blocking)
```

Live-content set checked against: all 60 daily-schedule secrets in both
langs (`schedule.load_schedule("en")` / `("hi-en")`), every pack's secrets
across every pack × lang declared in `packs.json` (bollywood, cricket —
indian-food and nature-wild are `coming_soon` with 0 authored secrets,
contributing nothing, which is valid per `packs.py`'s own documented
semantics), and every alias of all of the above
(`build_packs.aliases_for_secret`). Every benchmark word — every record's
`secret` and `word` (dim1_en/dim1_hien), every `hien_secret` and `en_gloss`
(dim2) — was checked **individually** against this full live set, not just
checked for co-occurring pairs (this is a stricter, more direct check than
`publish_to_hf.py`'s training-data scrub, per the reasoning in the scrub
script's own module docstring).

### Two severity tiers, and why

Every check reuses `payload._is_morphological_variant` — the exact
predicate `build_packs.clue_leak_reason` already uses to gate every pack/
schedule clue against leaking its own secret. Run naively (any hit = fail)
across ~500 distinct benchmark words × ~200 live items, this produced
**539 raw hits (101 distinct benchmark/live word pairs)** — almost all of
them coincidental short edit-distance matches between semantically
unrelated words (`basket`/`market`, `border`/`bowler`, `chinta`/`chhata`,
`dehat`/`defeat`). This is an emergent, previously-undocumented finding:
the predicate's Levenshtein branch is calibrated for checking ONE candidate
word against ONE known secret per clue (where a coincidental hit is rare);
sweeping it across hundreds of benchmark words against hundreds of live
items makes coincidental edit-distance-≤2 matches common by combinatorics,
not signal.

The scrub script therefore reports two tiers (full methodology and
rationale in the script's module docstring):

- **BLOCKING** (gates PASS/FAIL): exact match (case-insensitive), or a
  prefix/substring containment where the shorter string is ≥ 4 characters
  — the genuine "same word, different inflection" risk (`payload.py`'s own
  documented "oceans"/"ocean" example; e.g. `doctors` is literally the
  plain plural of the live secret `doctor`).
- **ADVISORY** (reported in full, never blocks): a hit whose only trigger
  is the free-floating Levenshtein-distance branch with no containment
  relationship — different-root words that happen to be a couple of edits
  apart. All 539 of these are printed by the script for human review; none
  are silently dropped.

**16 real (blocking) collisions were found and fixed** before this report
— 7 in `dim1_en.json`, 9 in `dim1_hien.json` (mirrored pairs like
`key`/`chaabi`'s shared near-word count as 2 separate fixes, one per
file). One was `udaasi`'s replacement for `pleasing` — my first attempt,
`umbrella`, turned out to be an EXACT match for a live daily-schedule EN
secret, caught by the very first scrub run and swapped again (to
`optical`). Every replacement word was verified in-vocab
(`load_en_vocab()` / `load_hien_vocab()`) and re-scrubbed clean before
being kept. Full (secret, tier, old→new) list:

| File | Secret | Tier | Old word | New word |
|---|---|---|---|---|
| dim1_en | key | near | lock | bolt |
| dim1_en | key | far | dangerously | textiles |
| dim1_en | nephew | mid | elder | cousin |
| dim1_en | passion | far | sold | warehouse |
| dim1_en | question | far | start | optical |
| dim1_en | rock | far | straining | budgets |
| dim1_en | yogurt | far | chandeliers | physician |
| dim1_hien | chaabi | near | lock | bolt |
| dim1_hien | bhanja | mid | elder | cousin |
| dim1_hien | chattan | far | doctors | municipal |
| dim1_hien | chattan | far | spinal | archive |
| dim1_hien | jheel | far | organizations | carpenter |
| dim1_hien | patta | far | tory | gallery |
| dim1_hien | waqt | far | newsletter | cabinet |
| dim1_hien | insaaf | far | starts | textbook |
| dim1_hien | udaasi | far | pleasing → umbrella | optical |

After these fixes, the scrub re-ran clean: **0 blocking collisions**, 539
advisory (non-blocking) hits fully disclosed above and in the script's
verbose output. `tests/test_scrub_public_benchmark.py` (9 tests, including
a regression test that re-runs the real scrub against the real staging
files) — all pass.

### Correction (found during GG's review pass): a 17th collision was silently dropped, not substituted

Re-verifying this table against the live staging files (not just trusting
the report) found a discrepancy: `bhanji`'s hi-en far tier had only 4 words
where its EN counterpart (`niece`) had 5. Root cause: `helmet` (bhanji's
5th far-tier word, sourced from the production supplement) is an EXACT
match for the live Cricket pack secret `helmet` — a real 17th blocking
collision — but it was removed rather than substituted, and the removal
was never added to the table above or disclosed as a change. Fixed:
added a verified replacement (`muscle` — confirmed far/band-4 from
`bhanji`, zero string collisions, zero semantic collisions per the section
below) restoring `bhanji`'s hi-en far tier to 5 words. `dim1_hien.json` is
now 302 records (was 301). Flagging this plainly: the original 16-item
table undercounted; the correct count is 17, and this specific one was a
straight drop, not a same-tier swap.

---

## 2b. Semantic-proximity scrub (addendum — requested by GG, not in original scope)

`scrub_public_benchmark.py` (above) catches STRING/morphological collisions
only. It cannot catch a benchmark word that is a strong SEMANTIC associate
of a live secret with zero string overlap (e.g. a benchmark word meaning
something ocean-adjacent, where a live pack secret genuinely IS "ocean").
Built `evals/finetune/semantic_scrub_public_benchmark.py` to check this,
reusing the exact production rank/band machinery (`embeddings.embed_vocab`
+ `rival.band_for_rank` — the same code a real payload build uses), not an
invented cosine threshold.

**A necessary calibration finding, not initially anticipated**: the 34-
secret benchmark's ~325 distinct words per language are themselves **~3%
(EN, 55k vocab) to ~3% (hi-en, 10.5k vocab)** of the entire embeddable
vocabulary. At that density, a meaningful number of (benchmark word, live
secret) pairs land in a tight embedding-rank band **by pure chance**, with
zero real semantic relationship — the exact same "combinatorial noise"
failure mode the string scrub already found for coincidental edit-distance
matches, but for embedding rank instead of Levenshtein distance. Computed
the actual chance baseline rather than guessing:

| Lang | distinct bench words | distinct live secrets | expected hits/secret @rank≤50 | actual hits/secret @rank≤50 | expected @rank≤500 | actual @rank≤500 |
|---|---|---|---|---|---|---|
| en | 327 | 110 | 0.30 | 0.87 | 2.97 | 6.95 |
| hi-en | 325 | 110 | 1.55 | 1.86 | 15.49 | 19.51 |

Actual rates run only **~1.3–2.9x** chance-expected — elevated, but nowhere
near the "nearly every pair collides" read the raw hit count (3,159 total
across both langs, mostly at the loose rank≤500 "hot" band) would suggest
in isolation. Treating every hot-band hit as "blocking" would fail the
scrub almost everywhere and force degrading dozens of words to fix
statistical noise, not real risk — the same over-broad-check trap already
documented and avoided once in section 2's Levenshtein tiering.

**A separate, load-bearing consideration**: the shipped model
(`gauravgandhi2411/hinglish-relatedness-sbert`) is **already public** on
HF Hub. A benchmark word's raw embedding-rank proximity to a live secret,
with no string overlap, discloses nothing a player couldn't already compute
themselves in 30 seconds by querying the public model directly. This is a
materially different risk than the string scrub protects against (which
prevents literally handing someone a live secret's answer). This
consideration doesn't make the check pointless, but it does mean "a hit
exists" is not automatically "a leak."

**What I actually fixed, versus what remains open:**
- `physician` (yogurt's far-tier substitute from section 2's fix table)
  turned out to be rank=3 (near-synonym) against the live EN secret
  `doctor`. Fixed regardless of the leak-philosophy question above, on
  simple hygiene grounds: a far-tier filler shouldn't be a strong
  near-synonym of ANY common word if a clean alternative exists.
  Replaced with `tribunal` (rank 52,017 vs `yogurt`, zero string or
  semantic hits against any live secret). Regression test added:
  `tests/test_semantic_scrub_public_benchmark.py::test_known_fixed_collision_no_longer_blocking`.
- **44 remaining pairs at rank≤10** (the tightest, least chance-explicable
  band) were NOT unilaterally fixed — several read as genuine, not
  coincidental (e.g. `border`↔`boundary` rank 4, `storage`↔`memory` rank 6,
  `cooking`↔`kitchen` rank 9), and per the public-model reasoning above
  they may not constitute a real leak even so. This is a judgment call
  about what counts as disclosure-worthy given the model's public status —
  not mine to resolve unilaterally for a citable public artifact. Full
  list left for GG's review below.
- The script's current BLOCKING/ADVISORY split (bands 0/1/2 vs band 3) is
  **not yet re-calibrated** to the chance-baseline finding above — as
  coded it still fails on the hot-band noise. Recalibrating it (e.g. to
  bands 0/1 only, or to a statistical-significance test per secret) is a
  follow-up **pending GG's call on the interpretation question**, not done
  unilaterally here.

`tests/test_semantic_scrub_public_benchmark.py` (5 tests) — all pass.

### 2c. GG's targeted pass: 20 words swapped, resolving 20 of the 44 rank≤10 hits

GG's call: the "public model already discloses this" reasoning is sound —
leave chance-level associations alone — but swap the OBVIOUS one-hop
associates (near-synonym or immediately-obvious functional pairing, the
`border→boundary`/`storage→memory` class) for the optics of a citable
public artifact. Went through all 44 by hand against that bar.

**2 of the 44 turned out to be unswappable by construction**, not left by
choice: `border` (rank 4, en+hi-en) and `sunlight` (rank 9, en) are the
secrets' own ground-truth EN *translations* — `sarhad` literally means
"border," `dhoop` literally means "sunlight." These aren't fillable
associate words; they're what the secret IS, used by the translation-
tagged near-word check and the dim2 cross-lingual pair specifically to
test correct-translation ranking. Swapping them would break the
measurement, not fix a defect. Their coincidental closeness to live
secrets `boundary` (a cricket term) and `sunrise` is an inherent property
of English having common words with overlapping senses — not a chosen
associate word failing a bar, and not fixable short of dropping the
secret entirely (not done — 34/34 secrets preserved).

**20 genuine associate-word swaps applied** (verified in-vocab,
string-clean, and — using the SAME rank≤10 bar that flagged the
originals, not the much stricter "zero hot-band hits anywhere" bar,
which chance-baseline analysis in 2b showed is nearly unachievable in a
10.5k-word vocab against 110 live secrets):

| Lang | Secret | Tier | Old word | New word |
|---|---|---|---|---|
| en | trunk | mid | storage | generator |
| en | neighborhood | far | military | binder |
| en | auntie | far | amnesia | carpenter |
| en | gram | mid | cooking | mattress |
| en | justice | mid | verdict | envelope |
| en | justice | mid | judge | adjudicator |
| en | freedom | far | spending | tablecloth |
| en | yogurt | far | lights | thermostat |
| en | auntie/nephew/niece/twin | mid | household | bracket (×4, shared word by original design) |
| hi-en | dahi | mid | breakfast | cabinet |
| hi-en | bhanja/bhanji/judwaa/mausi | mid | household | bracket (×4, mirrors EN) |
| hi-en | bhanja | far | affection | municipal |
| hi-en | thaali | far | beloved | satellite |
| hi-en | insaaf | far | textbook | printer |
| hi-en | tokri | far | prestigious | tribunal |
| hi-en | basti | far | commenced | vacuum |
| hi-en | sawaal | far | initial | archive |
| hi-en | judwaa | far | travelled | toaster |

`household`→`bracket` was applied identically across all 4 kinship
secrets in BOTH language files, preserving the original design's EN/hi-en
mid-tier mirroring (`_build_hien_curated()`'s "mid = EN's mid list
verbatim" rule in `gen_dim1_benchmark_supplement.py`).

**Remaining 24 of 44, left unchanged** — reviewed individually, not just
threshold-filtered: mostly phonetic-clustering artifacts between short
Hindi/Hinglish words with no semantic link (`chaabi`/`chaand`,
`khichdi`/`khidki`, `mohalla`/`mahal`), a few coincidental self-
referential secret-vs-secret proximities (`sarhad`/`pahad`,
`mazaa`/`razaai`), loose same-domain-but-not-synonymous associations
(`twig`/`titli`, `foliage`/`phool`, `outcome`/`finalist`), plus `border`/
`sunlight` (unswappable, above) and `batter`/`bat` (a coincidental
substring artifact — `batter` contains `bat`, already in the string
scrub's advisory list at the sub-4-character floor; semantically cooking
batter and a cricket bat are unrelated, this is a token-overlap artifact
not a real association).

Re-ran both scrubs after the swaps: string scrub still 0 blocking (547
advisory, up from 540 as an incidental side effect of new words entering
the checked set). Semantic scrub rank≤10 count: 44 → 24, every targeted
word confirmed gone, zero new hits introduced by the replacements.
`tests/test_scrub_public_benchmark.py` and
`tests/test_semantic_scrub_public_benchmark.py` both pass.

**Accuracy check on the headline numbers**: the swaps changed actual WORD
content in `dim1_hien.json`, but section 3/4's dev↔test correlation and
bootstrap CIs below were originally computed from the bake-off
checkpoints (`bakeoff_raw/*.json`), which reflect the PRE-swap production
scenario files, not the published staging content. Built
`evals/finetune/public_benchmark_reverify.py` to recompute both against
the actual final staging file (reusing each of the 8 models' already-
cached full-vocab embeddings — no re-inference) rather than assume the
20-word swap (out of ~600 total words) didn't matter. It didn't, within
noise: dev↔test Pearson r = **0.894** (was 0.885 pre-swap, both are within
each other's expected sampling variation for n=8); shipped model full-34
dim1 Spearman = **0.656** (was 0.657). **The numbers reported below (section
3/4) are the reverify (post-swap, actually-published) numbers.**

---

## 3. Dev/test split and dev↔test correlation

**Script**: `evals/finetune/public_benchmark_split.py` →
`data/public_benchmark_split.json`. Stratified by domain, seed=42,
deterministic (`tests/test_public_benchmark_split.py`, 4 tests, all pass).

| Domain | dev | test | total |
|---|---|---|---|
| abstract | 3 | 2 | 5 |
| emotion | 2 | 3 | 5 |
| food | 3 | 2 | 5 |
| kinship | 2 | 2 | 4 |
| nature | 2 | 3 | 5 |
| object | 3 | 2 | 5 |
| place | 2 | 3 | 5 |
| **total** | **17** | **17** | **34** |

`dev_secrets` (17): basti, bhanji, chaabi, chattan, dahi, insaaf, judwaa,
kanoon, khichdi, mazaa, mithai, patta, sandook, sarhad, sawaal, sharm,
thaali
`test_secrets` (17): azaadi, besan, bhanja, chimni, chinta, dehat, dhoop,
jheel, junoon, mausi, mohalla, paneer, registan, sadak, tokri, udaasi,
waqt

### Measured dev↔test correlation

**Script**: `evals/finetune/public_benchmark_analysis.py` →
`data/public_benchmark_analysis.json`. Method: for each of the 8 bake-off
`CANDIDATE_MODELS`, slice its already-computed `dim1_records` (from
`bakeoff_raw/*.json`, no re-embedding) down to just these 34 secrets, split
into dev/test halves, compute each half's dim1 Spearman via
`bootstrap_ci.py`'s existing `_dim1_by_secret`/`_dim1_spearman_for_secrets`
helpers (reused, not reimplemented) — giving one (dev_score, test_score)
pair per model. Reported correlation is the **Pearson** r across those
pairs (explicitly Pearson, not Spearman — the question is whether a
model's raw dev-half score predicts its raw test-half score, a linear
relationship across models, not a rank relationship within one model's
items).

**N models used: 8 of 8.** `Qwen/Qwen3-Embedding-0.6B` and
`gauravgandhi2411/hinglish-relatedness-sbert` (the shipped model) had no
valid checkpoint on disk when this section was first drafted (a background
regeneration of those two, following the P0 `embeddings.py` cache-key
bugfix, had not finished yet) — that partial run (n=6/8, Pearson r=0.767)
was reported honestly at the time. Both checkpoints finished and landed on
disk before this task's session ended; `public_benchmark_analysis.py` was
re-run and this section reflects the **completed n=8/8** result below —
the analysis script is idempotent and required zero code changes to pick
up the 2 additional checkpoints.

| Model | dev score | test score |
|---|---|---|
| paraphrase-multilingual-MiniLM-L12-v2 | 0.005 | 0.144 |
| l3cube-pune/indic-sentence-bert-nli | 0.561 | 0.438 |
| google/muril-base-cased | 0.230 | 0.088 |
| BAAI/bge-m3 | 0.122 | 0.065 |
| intfloat/multilingual-e5-large | 0.221 | 0.165 |
| ibm-granite/granite-embedding-311m-multilingual-r2 | 0.207 | 0.040 |
| Qwen/Qwen3-Embedding-0.6B | 0.263 | 0.103 |
| gauravgandhi2411/hinglish-relatedness-sbert (shipped) | 0.671 | 0.641 |

**Dev↔test Pearson r = 0.894 (n=8 models).** *(Recomputed by
`public_benchmark_reverify.py` against the FINAL published word content
post-scrub — see section 2c. The originally-measured value against the
pre-swap production scenario words was 0.885; both numbers, and the
n=6/8 interim read of 0.767 before that, are kept below rather than
overwritten — see the caveats.)*

### Interpretation

This **materially beats the old n=16 problem's ~0.12 correlation** — 0.894
vs 0.12 is a +0.774 improvement. The stratified 17/17 split with 7-domain
coverage in both halves produces a benchmark whose dev half is a strongly
predictive proxy for its test half — a model that looks good on dev also
looks good on test, which was NOT true of the old, much smaller held-out
set. Notably, the shipped model has both the highest dev score (0.671) and
the highest test score (0.641) of all 8 candidates — consistent with
`phase1_benchmark_report.md`'s full-set finding that it leads every
alternative — so the dev/test split doesn't just correlate well in the
aggregate, it preserves the same leadership ranking on each half
independently.

**Honest caveats, not smoothed over:**
- n=8 model-pairs is still a small sample for a correlation estimate; the
  true population correlation could differ from 0.894 by a real margin (a
  bootstrap CI on this specific correlation was out of this task's
  explicit scope, which asked for the point estimate — flagging as a
  natural Phase 2 follow-up).
- This correlation was **not** used to retroactively adjust the split —
  the split was built first (`public_benchmark_split.py`, seed=42,
  domain-stratified), then the correlation was measured against it as-is,
  at three points in this same session as more data became available (n=6/8
  read of 0.767 → n=8/8 pre-scrub read of 0.885 → n=8/8 post-scrub,
  actually-published read of 0.894). No post-hoc reshuffling was performed
  to improve this number at any point; all three are disclosed here rather
  than silently overwritten by the latest.

---

## 4. Bootstrap CIs — shipped model, full/dev/test

The shipped model's bake-off checkpoint
(`bakeoff_raw/gauravgandhi2411__hinglish-relatedness-sbert.json`) was not
present on disk when this task began (a background regeneration following
the P0 `embeddings.py` cache-key bugfix was still in flight, per the task
brief), but landed before this session ended. `evals/finetune/
public_benchmark_analysis.py`'s `shipped_model_bootstrap_cis()` was run
against it (cluster-by-secret bootstrap, `n_boot=10,000`, `seed=42`,
mirroring `bootstrap_ci.py`'s own methodology exactly) with no re-embedding.

**dim1 Spearman below is the reverify (post-scrub, actually-published-word)
number** from `public_benchmark_reverify.py` (section 2c) — the pre-scrub
figures were 0.657 / 0.688 / 0.628, all within noise of the numbers below.
**dim2 pass-rate is unchanged from the original run** — dim2 pairs are
(en_secret, hien_secret) NAME tuples, and no secret name was ever swapped,
only near/mid/far associate words, so dim2 is unaffected by construction
(see section 2c) and was not recomputed.

| Slice | dim1 Spearman [95% CI] | n secrets / scenarios | dim2 pass-rate [95% CI] | n pairs |
|---|---|---|---|---|
| full 34-secret benchmark | 0.656 [0.569, 0.735] | 34 / 303 | 0.706 [0.559, 0.853] | 34 |
| dev_bench only | 0.671 [0.574, 0.759] | 17 / 151 | 0.882 [0.706, 1.000] | 17 |
| test_bench only | 0.641 [0.493, 0.766] | 17 / 152 | 0.529 [0.294, 0.765] | 17 |

**Observations:**
- dim1 Spearman is stable and CI-overlapping across all three slices
  (full/dev/test all land in the 0.57–0.77 range) — the shipped model's
  dim1 ranking quality doesn't swing wildly between the two halves,
  consistent with the strong dev↔test correlation measured in section 3.
- dim2 pass-rate is noticeably less stable (0.882 dev vs 0.529 test, CIs
  overlap but are wide at n=17 pairs each) — dim2 is a binary
  consistent/inconsistent metric per pair with only 17 items per half, so
  its CI width (±0.2–0.3) is expected to be much wider than dim1's
  cluster-of-303-scenarios CI at the same n=17 secret-cluster count. This
  is a real, reportable finding, not swept under the rug: dim2 numbers on
  either 17-item half individually should be treated with more caution
  than the pooled 34-pair number, exactly the kind of thing this
  dev/test-split exercise exists to surface.

---

## 5. Licensing / sourcing — honest statement

This benchmark is **majority expert-tiered, project-authored content**,
**not externally-sourced commercial data**, and specifically **not
human-annotated by an independent linguist or crowd-sourced annotators**.
Precise authorship, by component:

- **Near/mid tier word associations** (the curated, semantically-load-
  bearing part): hand-authored as literal Python data
  (`EN_CURATED_SUPPLEMENT` in `evals/gen_dim1_benchmark_supplement.py`) by
  the AI coding assistant (Claude, Anthropic) during this project's
  development, across earlier sessions implementing
  `spec-hinglish-benchmark.md` Phase 1a. Not generated by a separate/
  runtime LLM call, not sourced from any external dataset — static,
  version-controlled curation choices, spot-checked by GG at specific
  project gates (e.g. the original 25-secret set's homograph-collision
  review) but not independently re-annotated word-by-word by a human.
- **Far-tier filler words**: mechanically sampled via a hash-seeded RNG
  over the project's own vocabulary (`build_scenarios()`,
  `evals/gen_dim1_scenarios.py`) — not curated at all, by design; their
  only property is "not near/mid," verified after the fact.
- **The 17 collision-driven substitution words** (section 2/2b): chosen by
  an AI coding-assistant subagent (Claude/Sonnet) during this session,
  verified in-vocab and scrub-clean before being kept, same authorship
  category as the near/mid tiers above — not independently sourced.

This is stated explicitly and is not to be presented otherwise: prior
research already on record in this project's `PLAN.md` found no
commercially-licensed Hindi word-relatedness dataset exists (WordSim-353
Hindi unavailable, Multi-SimLex excludes Hindi, IndoWordNet is research-
only) — this benchmark does not change that fact, it is a new, small,
AI-assistant-authored-and-verified, methodologically-rigorous dataset
built to fill that gap, and must be labeled as such (not as "human-
annotated" or "expert-annotated" in the sense of an independent linguist)
wherever it is described publicly.

Proposed license (unchanged from the Phase 1 proposal in
`phase1_benchmark_report.md` section 1c): **CC-BY-4.0**, matching the
shipped model's license, with attribution to this project. Not yet
applied to any published artifact — no publish has happened.

---

## Acceptance criteria checklist

1. Reconcile 3 missing secrets (junoon/insaaf/udaasi) into all 3 staging
   files, matching schema/tiering discipline, vocab-verified: **done** —
   34/34 secrets now present in `dim1_en.json`, `dim1_hien.json`,
   `dim2_pairs.json`, sourced verbatim from the already-verified
   production supplement scenarios, one word (`udaasi`'s far-tier filler)
   swapped for a vocab-resolvable replacement.
2. Automated scrub check built and RUN, real hits fixed, not
   silently-passing: **done for string/morphological collisions** —
   `scrub_public_benchmark.py`, 0 blocking collisions after **17** real
   fixes (corrected from an initial undercount of 16, see section 2's
   correction note); 540 advisory (non-blocking, Levenshtein-only
   coincidental) hits fully disclosed, not hidden.
   `tests/test_scrub_public_benchmark.py` 9/9 pass. **Semantic-proximity
   scrub (section 2b, addendum): built, run, one real fix applied
   (`physician`→`tribunal`); 44 rank≤10 hits remain OPEN pending GG's
   read on the public-model-disclosure question — not silently passed,
   not silently blocked either.**
3. Dev/test split built, seed=42, domain-stratified, written to
   `public_benchmark_split.json`: **done** — 17/17, every domain covered
   in both halves. `tests/test_public_benchmark_split.py` 4/4 pass.
4. Dev↔test correlation measured (not estimated) from existing bake-off
   data: **done, n=8/8 models** — Pearson r = 0.885, materially above the
   old 0.12 baseline (an interim n=6/8 read of 0.767 was taken and
   reported honestly earlier in this same session, before the 2 remaining
   checkpoints finished; both are disclosed in section 3, neither
   discarded).
5. Bootstrap CIs for shipped model, full/dev/test: **done** — shipped
   model's checkpoint landed before session end; full/dev/test dim1
   Spearman + dim2 pass-rate 95% CIs computed and reported in section 4.
6. Report written with honest sourcing/licensing statement: **done** —
   this document.

---

## STOP — awaiting GG review before this benchmark is used as the ruler for anything downstream or published

Per this project's established stop-gate convention (see
`phase1_benchmark_report.md`'s closing section for the precedent): this
benchmark is now internally complete and safety-scrubbed (34/34 secrets,
0 blocking collisions), and all 5 deliverables in this task's scope are
done, including the full n=8/8 dev↔test correlation and shipped-model
bootstrap CIs. **Still, it is NOT yet published anywhere.** Do NOT treat
this benchmark as validated for any downstream use — publishing to HF
Datasets, using it as a Phase 2 accuracy-push ruler, or citing its numbers
publicly — until:

1. GG has reviewed and confirmed the 16 scrub-driven word substitutions
   (section 2 table) don't materially change any secret's intended
   near/mid/far semantic structure.
2. GG has reviewed the dim2 stability finding in section 4 (dev 0.882 vs
   test 0.529 pass-rate, wide CIs at n=17 pairs/half) and decided whether
   that's an acceptable characteristic of this benchmark size or needs
   more secrets before being trusted as a dim2 ruler.
3. GG confirms the CC-BY-4.0 license and "expert-tiered, not
   externally-sourced" honesty statement (section 5) before any public
   HF Datasets push, per the spec's mandatory publish gate.

---

## Addendum (Phase 2 kickoff): a methodology artifact found while diagnosing the
soft cluster, corrected on the published card

While diagnosing why food/nature/emotion score weaker on dim2 (per GG's Phase 2
direction), found that 2 of the 5 reported food-domain "failures"
(`paneer`, `khichdi`) are not real: `_GOOD_BANDS = {1, 2}` in `eval_model.py`
deliberately excludes band 0 ("win", rank==1) from "consistent," to stop a
literal duplicate string from trivially gaming the metric — but `paneer` and
`khichdi` are loanwords spelled identically in EN and hi-en, so their EN gloss
IS their hi-en secret, and they trivially self-match at rank 1. Excluding band
0 in the general case is correct; scoring these two specific degenerate,
self-identical pairs as failures is not — a lookup table would "fail" them too.
Excluded from the informative fail-rate: food corrects from 3/5 (60%) to 1/3
(33%, n reduced since 2 of 5 are degenerate). Corrected table (32 informative
pairs): emotion 2/5 (40%), nature 2/5 (40%), food 1/3 (33%), kinship 1/4 (25%),
place 1/5 (20%), object 1/5 (20%), abstract 0/5 (0%). **The uncorrected 60%
figure WAS live on the published HF Dataset card briefly** (published, then
this artifact found during the very next diagnostic pass) — fixed and
republished the same session; `public_benchmark_card.md` now carries the
corrected table.
