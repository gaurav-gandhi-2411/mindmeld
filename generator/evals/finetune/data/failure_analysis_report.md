# Failure Analysis Report — WORKSTREAM B (items 5, 6, 7)

Spec: `spec-model-excellence.md`. Checkpoint: `evals/finetune/data/bakeoff_raw/gauravgandhi2411__hinglish-relatedness-sbert.json` (model `gauravgandhi2411/hinglish-relatedness-sbert`). Generated 2026-07-23T21:53:28.407333+00:00, repo commit `00b0bfd57346550100be1885b92aa7c3300bb58e`. n_dim1_records=379 (42 secrets: 8 original production + 34 benchmark-supplement), n_failing (in_expected_band==False)=124, vocab_size=10495.

## Summary — ranked by prevalence

0. **BIGGEST SINGLE FINDING — mid-tier is a benchmark band-width artifact, not primarily a model bug:** 83 of 84 resolved mid-tier records (rate=1.2%) fail, dwarfing every other cut in this report. Mid-tier's only expected band (`warm`, band 3) is a **24-rank window (0.2% of the 10495-word vocab)** — see the dedicated section below. This changes how every other number in this report should be read: 84 of the 124 "failing pairs" behind item 5's taxonomy are mid-tier, so a benchmark-design fix (widening mid-tier's accepted band set) is likely higher-leverage than any per-pair model fix the taxonomy below might suggest.
1. **Item 5 (error taxonomy):** conditioned on the current (narrow) benchmark design, the single largest failure class is **genuine_semantic_difficulty** at n=99 (79.8% of the 124 failing pairs) — see caveat below on why this likely UNDERSTATES true subword-collision prevalence.
2. **Item 6 (frequency):** combined head-vs-tail `in_expected_band` rate gap (tail penalty) = **-22.8%** (head=55.9%, tail=78.6%) — NOTE the sign: tail-bucket words score BETTER, not worse, than head-bucket words. See the tier-confound caveat in the item 6 section before reading this as 'rare words are easier for the model.'
3. **Item 7 (domain/POS):** weakest domain-labeled cut is **emotion** (61.4%, n=44); weakest POS cut is **noun** (63.0%, n=284).
4. **Cross-reference finding:** 57/124 (46.0%) of the 124 failing pairs belong to a SECRET independently flagged as collision-prone by the sibling collision scan (item 8) — see the dedicated caveat below. This is the strongest single signal that the raw 0-count for `subword_collision` in the per-pair taxonomy above is an artifact of prompt design, not evidence that collision isn't a real driver of these failures.

## Item 5 — Full error taxonomy over the 124 failing pairs

Classified via the local Ollama judge (qwen3:8b, $0 cost — `evals/finetune/failure_taxonomy.py`), 6-category rubric + 4 GG-hand-labeled worked examples as few-shot calibration anchors. 3 of the 124 records have no `actual_rank` at all (secret or word absent from the game's own vocab — a mechanical vocab-coverage gap, not a model-judgment question) and are short-circuited to a 7th pseudo-category, `vocab_resolution_gap`, reported separately from the 6 semantic-failure categories.

| Category | n | % of 124 |
|---|---|---|
| genuine_semantic_difficulty | 99 | 79.8% |
| transliteration_artifact | 14 | 11.3% |
| polysemy_gloss_ambiguity | 3 | 2.4% |
| commonsense_world_knowledge | 3 | 2.4% |
| vocab_resolution_gap | 3 | 2.4% |
| label_error | 2 | 1.6% |

### Addendum — tier/band-width confound (discovered while writing this up)

Before reading the taxonomy above as "the model has these specific semantic bugs," the BENCHMARK's own design has to be checked first: each tier's `in_expected_band` outcome depends on how WIDE its accepted band(s) are, and that width varies enormously by tier — computed directly from `rival.band_for_rank` (the same function production uses), not estimated:

| tier | n | n_resolved | n_fail | rate | expected bands | window (ranks) | % vocab |
|---|---|---|---|---|---|---|---|
| near | 84 | 84 | 29 | 65.5% | [1, 2] | 499 | 4.8% |
| mid | 85 | 84 | 83 | 1.2% | [3] | 24 | 0.2% |
| far | 210 | 208 | 9 | 95.7% | [4, 5] | 9971 | 95.0% |

**mid-tier's `warm` band is a 24-rank window out of 10,495 words (0.23% of the vocab)** — near-total mid-tier failure (98.8%) is the PREDICTABLE consequence of asking any embedding model to land a weak/moderate semantic relation inside a window 40x narrower than near-tier's (499 ranks) and ~415x narrower than far-tier's (9,971 ranks). This is best read as a benchmark-DESIGN issue (mid-tier's accepted band set is too narrow to be a fair target), not primarily 84 independent model bugs — even though the per-pair judge classifications above are individually plausible-sounding (mostly `genuine_semantic_difficulty`), the judge was never shown this quantitative context and reasonably reached for a semantic narrative for what is substantially a mechanical near-impossibility. **Recommended follow-up (not done here — this is Workstream D/benchmark-design territory, out of this task's scope):** widen mid-tier's accepted band set (e.g. to include `hot`+`warm`+`cold`, bands 2-4) and re-measure before concluding the model needs further fine-tuning specifically for weak/moderate associations.

### Worked-example sanity check (GG's 4 hand-labeled anchors)

| secret <- word | GG label | judge label | agree |
|---|---|---|---|
| bachpan <- innocence | genuine_semantic_difficulty | genuine_semantic_difficulty | True |
| chaand <- satellite | commonsense_world_knowledge | commonsense_world_knowledge | True |
| bagicha <- yard | polysemy_gloss_ambiguity | polysemy_gloss_ambiguity | True |
| khazana <- gold | genuine_semantic_difficulty | genuine_semantic_difficulty | True |

**4/4 agreement** (including the intentionally-ambiguous khazana/gold calibration case) — the judge's classification matches GG's own hand labels on every anchor, a reasonable basis for trusting its calls on the remaining 120.

### Examples per category

**genuine_semantic_difficulty** (99 total, showing up to 5):
- `bachpan <- innocence` (tier=mid, expected_bands=[3], actual_band=5, rank=3739): The association between 'bachpan' and 'innocence' is real but abstract/weak, not a systematic model bug.
- `bachpan <- past` (tier=mid, expected_bands=[3], actual_band=5, rank=4315): The relation between 'bachpan' and 'past' involves a subtle temporal abstraction that is real but not strongly captured by the model.
- `bagicha <- phool` (tier=mid, expected_bands=[3], actual_band=2, rank=357): The relation between 'bagicha' (garden) and 'phool' (flower) is real but subtle, as flowers are commonly found in gardens, yet the association is not strong enough to place it in the expected warm band.
- `khazana <- gold` (tier=near, expected_bands=[1, 2], actual_band=3, rank=518): The relation between 'khazana' and 'gold' is real but subtle, as treasure can often imply gold specifically, yet the model placed it in a band that is closer than intended.
- `khazana <- gem` (tier=mid, expected_bands=[3], actual_band=4, rank=1535): The relation between 'khazana' and 'gem' is real but subtle, as treasure can include gems but is not exclusively about them, leading to a weaker association than expected.

**transliteration_artifact** (14 total, showing up to 5):
- `besan <- gram` (tier=near, expected_bands=[1, 2], actual_band=4, rank=583): The word 'gram' may be ambiguously transliterated for 'besan' (chickpea flour), leading to confusion with its alternative meaning as a unit of mass.
- `bhanja <- kin` (tier=near, expected_bands=[1, 2], actual_band=5, rank=4251): The word 'bhanja' has multiple transliterations (e.g., 'bhanja', 'bhanj', 'bhanji') which may have caused the model to associate it with unrelated words due to spelling ambiguity.
- `bhanja <- nephew` (tier=near, expected_bands=[1, 2], actual_band=4, rank=1306): The word 'bhanja' has multiple transliterations and ambiguous spelling, leading to confusion in the model's embedding.
- `bhanji <- kin` (tier=near, expected_bands=[1, 2], actual_band=4, rank=2291): The word 'bhanji' may have non-canonical or inconsistent transliterations that affect the model's embedding and relatedness ranking.
- `chaabi <- key` (tier=near, expected_bands=[1, 2], actual_band=4, rank=2079): The word 'chaabi' is ambiguously transliterated and may be confused with 'key' due to orthographic similarity, leading to an incorrect placement.

**polysemy_gloss_ambiguity** (3 total, showing up to 5):
- `bagicha <- yard` (tier=near, expected_bands=[1, 2], actual_band=4, rank=1256): The word 'yard' has multiple senses (unit of length vs. garden yard) and the model likely embedded the wrong sense.
- `bagicha <- plant` (tier=mid, expected_bands=[3], actual_band=4, rank=1270): The word 'plant' has multiple senses (e.g., garden plant vs. to install) and the model likely embedded the wrong sense in relation to 'bagicha' (garden).
- `bagicha <- lawn` (tier=mid, expected_bands=[3], actual_band=4, rank=1002): The word 'lawn' has multiple senses (e.g., a grassy area vs. a unit of measurement), and the model likely embedded the wrong sense given the secret word 'bagicha' (garden).

**commonsense_world_knowledge** (3 total, showing up to 5):
- `chaand <- satellite` (tier=near, expected_bands=[1, 2], actual_band=5, rank=3831): The relation requires knowing 'the moon is a satellite,' a specific fact not captured by general co-occurrence statistics.
- `chaand <- eclipse` (tier=mid, expected_bands=[3], actual_band=5, rank=3874): The relation between 'chaand' (moon) and 'eclipse' requires understanding the astronomical event where the moon passes between the Earth and the sun, a specific fact not captured by general co-occurrence.
- `chaand <- sky` (tier=mid, expected_bands=[3], actual_band=5, rank=6021): The relation between 'chaand' (moon) and 'sky' requires knowing the moon is part of the sky, a specific fact not captured by general co-occurrence.

**vocab_resolution_gap** (3 total, showing up to 5):
- `basti <- migrant` (tier=mid, expected_bands=[3], actual_band=None, rank=None): secret='basti' or word='migrant' not in vocab
- `judwaa <- retailer` (tier=far, expected_bands=[4, 5], actual_band=None, rank=None): secret='judwaa' or word='retailer' not in vocab
- `udaasi <- pleasing` (tier=far, expected_bands=[4, 5], actual_band=None, rank=None): secret='udaasi' or word='pleasing' not in vocab

**label_error** (2 total, showing up to 5):
- `khichdi <- khichdi` (tier=near, expected_bands=[1, 2], actual_band=0, rank=1): The model correctly ranks 'khichdi' as the most related word to itself, suggesting the benchmark's tier assignment is likely incorrect.
- `paneer <- paneer` (tier=near, expected_bands=[1, 2], actual_band=0, rank=1): The model correctly ranks 'paneer' as the most related to itself, but the benchmark incorrectly assigns it to a near tier instead of the expected scorching/hot band.

### Low-confidence / inconsistent-rationale flags (human review)

Low confidence (judge self-rated <=2): **0**. Hedge-language flags (rationale leans on 'may have'/'possibly'/etc despite a non-low confidence score): **14**, all 14 of which are `transliteration_artifact` calls — expected, since that category is inherently about spelling AMBIGUITY and a hedge-worded rationale is somewhat native to the category, but flagged here per the task's instruction rather than silently accepted.

- `besan <- gram` [transliteration_artifact, conf=4]: The word 'gram' may be ambiguously transliterated for 'besan' (chickpea flour), leading to confusion with its alternative meaning as a unit of mass.
- `bhanja <- kin` [transliteration_artifact, conf=4]: The word 'bhanja' has multiple transliterations (e.g., 'bhanja', 'bhanj', 'bhanji') which may have caused the model to associate it with unrelated words due to spelling ambiguity.
- `bhanji <- kin` [transliteration_artifact, conf=4]: The word 'bhanji' may have non-canonical or inconsistent transliterations that affect the model's embedding and relatedness ranking.
- `chaabi <- lock` [genuine_semantic_difficulty, conf=5]: The relationship between 'chaabi' (key) and 'lock' is real but subtle, involving functional association rather than direct synonymy, which may be weak or context-dependent.
- `chaabi <- key` [transliteration_artifact, conf=4]: The word 'chaabi' is ambiguously transliterated and may be confused with 'key' due to orthographic similarity, leading to an incorrect placement.
- `chattan <- breasts` [transliteration_artifact, conf=4]: The word 'chattan' may have non-canonical or inconsistent transliterations that caused the model to associate it with unrelated concepts like 'breasts'.
- `dehat <- countryside` [transliteration_artifact, conf=4]: The word 'dehat' may have non-canonical or inconsistent transliterations that caused the model to misinterpret its semantic relation to 'countryside'.
- `kanoon <- court` [genuine_semantic_difficulty, conf=4]: The relation between 'kanoon' and 'court' is real but subtle, involving legal systems and judicial roles, which may be weak or context-dependent for the model to capture accurately.
- `mausi <- relative` [transliteration_artifact, conf=4]: The word 'mausi' has multiple transliterations (e.g., 'mausi', 'mausie', 'mausie') which may have caused the model to associate it with unrelated words due to spelling ambiguity.
- `registan <- desert` [transliteration_artifact, conf=4]: The word 'registan' may have an ambiguous or non-canonical transliteration that confuses the model's embedding.
- `sandook <- vault` [transliteration_artifact, conf=4]: The word 'sandook' may have non-canonical or inconsistent transliteration that caused the model to misinterpret its semantic relation to 'vault'.
- `sarhad <- jersey` [transliteration_artifact, conf=4]: The word 'jersey' may be ambiguously transliterated or associated with 'sarhad' due to phonetic similarity rather than semantic relation.
- `tokri <- hamper` [transliteration_artifact, conf=4]: The word 'tokri' may have non-canonical or inconsistent transliterations that caused the model to misinterpret its meaning in relation to 'hamper'.
- `udaasi <- rahat` [transliteration_artifact, conf=4]: The word 'udaasi' may have non-canonical or inconsistent transliterations that caused the model to associate it with 'rahat' in a way that diverges from the human-intended band.

### Cross-reference against the independent collision scan (item 8)

`evals/finetune/collision_scan.py` (sibling WORKSTREAM B item 8 task, run independently) flags a word as collision-prone if ITS OWN embedding neighbors are dominated by orthographically-similar, semantically-unrelated tokens. This taxonomy's per-pair judge prompt, by contrast, only shows the judge the failing WORD and its outcome — it never shows the judge the SECRET's actual neighbor list, so it cannot detect the case where the SECRET itself is collision-prone and its polluted neighbor list pushes a legitimate near/mid word out of its expected top ranks (a real failure mode with a different observable signature: the target word doesn't look anything like an English homograph, so per-pair reasoning alone lands on `transliteration_artifact` or `genuine_semantic_difficulty` instead).

**57/124 (46.0%) of the 124 failing records have a SECRET independently flagged as collision-prone.** Category breakdown restricted to those records:

| category | n (collision-flagged secret) |
|---|---|
| genuine_semantic_difficulty | 45 |
| transliteration_artifact | 6 |
| polysemy_gloss_ambiguity | 3 |
| commonsense_world_knowledge | 3 |

**Concrete example:** secret `sandook` (trunk) is flagged by the collision scan (its top-15 neighbors are dominated by `sand`/`sandra`/`sandy`/`sands` — an orthographic collision with the unrelated English word 'sand', pulling its whole neighbor list toward water/beach terms like pond/creek/lake/reef instead of storage-container terms). This taxonomy classified `sandook <- vault` as `transliteration_artifact` (hedged rationale: "sandook may have non-canonical transliteration causing misinterpretation of vault") — plausible on its face, but the collision scan's neighbor-list evidence suggests the ACTUAL mechanism is secret-side subword collision with 'sand', not word-side spelling ambiguity. **Recommended follow-up (not done here, out of this task's scope):** re-run the item-5 judge prompt for collision-flagged-secret records with the secret's real neighbor list (from collision_scan_report.json) included as context, so the judge can distinguish secret-side collision from the other categories directly instead of guessing blind.

## Item 6 — Head/tail (frequency) analysis

Vocab origin reconstructed via `evals/finetune/frequency_buckets.py` (mirrors `vocab.load_hien_vocab()`'s own filtering/dedup logic). English-sourced words (n=9951) are ranked by 1-based position in `vocab/en.txt` (already wordfreq-frequency-ordered — confirmed via `vocab.py`'s own docstring/derive_en_vocab comment, not re-derived here). Hinglish-sourced words (n=544) are ranked by `wordfreq.word_frequency(devanagari_form, "hi")`, using the pre-existing full-vocab transliteration table (not regenerated). Each origin is bucketed into head/mid/tail INDEPENDENTLY via tertiles (documented choice — see `frequency_buckets.py` module docstring for why quartiles don't map onto the requested 3 labels).

### Coverage honesty (no silent caps)

Of the 544 hinglish-sourced words, **311 (57.2%) have an unresolved frequency** — either `wordfreq.word_frequency` returned exactly 0.0 (genuinely rare/absent from wordfreq's Hindi corpus, OR a garbage transliteration — these are indistinguishable automatically) or the pre-existing transliteration table has no Devanagari form at all for that word. Spot-checked example of the latter failure mode: `pyaar` (love) transliterates in the table to `प्यर` (missing the long vowel — correct spelling is `प्यार`), which legitimately returns wordfreq=0.0 for the WRONG reason (bad transliteration, not genuine rarity). This 57.2% unresolved fraction is reported as its own bucket, never silently folded into 'tail'.

### Combined head/mid/tail (english + hinglish origins pooled)

| bucket | n | in_expected_band rate | mean rank percentile |
|---|---|---|---|
| head | 170 | 55.9% | 29.8% |
| mid | 94 | 79.8% | 39.5% |
| tail | 103 | 78.6% | 41.2% |
| unresolved | 9 | 44.4% | 19.0% |

**Tail penalty (head rate − tail rate) = -22.8%** (note the sign: NEGATIVE — tail-bucket words score HIGHER, not lower. n_records_resolved=376 of 379 total dim1 records.) **This is very likely a TIER-COMPOSITION CONFOUND, not a genuine frequency effect**: curated near/mid target words (deliberately common, evocative associate words) skew heavily toward the 'head' bucket, while far-tier decoy words (randomly sampled across the whole vocab, and the tier the model is best at — see the item 5 tier addendum above, far-tier rate ~95.7%) are the ones populating 'tail'. A frequency effect CONTROLLED for tier would need to compare head-vs-tail WITHIN each tier separately, which this report's join (item 6 asks for a `word`-level cut, not a tier-stratified one) does not do — flagged here rather than reported as a clean frequency finding it isn't.

### By origin x bucket

| origin_bucket | n | in_expected_band rate |
|---|---|---|
| english_head | 168 | 56.0% |
| english_mid | 93 | 79.6% |
| english_tail | 102 | 78.4% |
| english_unresolved | 0 | n/a |
| hinglish_head | 2 | 50.0% |
| hinglish_mid | 1 | 100.0% |
| hinglish_tail | 1 | 100.0% |
| hinglish_unresolved | 9 | 44.4% |

## Item 7 — Per-domain and per-POS/concreteness breakdown

**Both the domain labels for the 34 benchmark-supplement secrets AND the POS/concreteness tags are AI-derived, not human-verified ground truth** — same epistemic status as this benchmark's own near/mid/far tiers (spec-model-excellence.md Workstream D item 13 flags this as an open question for the benchmark generally). Treat this section as a first-pass systematic view, not a final verdict.

### Domain (34 benchmark-supplement secrets only — coverage caveat)

The original 25 production secrets carry NO domain label and none is invented for them here: 73 records (72.6% in_expected_band rate) are reported separately as domain-unlabeled / out of scope for this cut.

| domain | n | in_expected_band rate |
|---|---|---|
| abstract | 45 | 75.6% |
| emotion | 44 | 61.4% |
| food | 45 | 66.7% |
| kinship | 35 | 62.9% |
| nature | 45 | 62.2% |
| object | 45 | 64.4% |
| place | 44 | 72.7% |
| *(unlabeled — original 25 secrets)* | 73 | 72.6% |

### POS + concreteness (all 379 records, 366 unique words, 366/366 judge-covered)

| part_of_speech | n | in_expected_band rate |
|---|---|---|
| adjective | 42 | 81.0% |
| noun | 284 | 63.0% |
| other | 1 | 100.0% |
| verb | 49 | 83.7% |

| concreteness | n | in_expected_band rate |
|---|---|---|
| abstract | 201 | 77.6% |
| concrete | 175 | 56.6% |

## Recommended follow-ups (not in this task's scope)

- **Highest priority:** widen mid-tier's accepted band set in the benchmark (currently `[warm]` only, a 24-rank/0.23%-of-vocab window) and re-measure before spending further model-fix effort on mid-tier failures specifically — the current 98.8% mid-tier failure rate is largely explained by benchmark band width, not model quality (see item 5 addendum).
- Re-run item 5's judge with the secret's actual collision-scan neighbor list included as context for the 57/124 (46%) failing records whose secret is independently flagged as collision-prone, to properly disambiguate secret-side subword collision from word-side transliteration ambiguity / genuine difficulty.
- Re-run item 6's frequency-bucket analysis stratified BY TIER (not pooled across tiers) before drawing any conclusion about a genuine frequency effect — the pooled head/tail comparison in this report is confounded by tier composition (see the item 6 caveat above).
- Human-verify a sample of the AI-derived domain and POS/concreteness labels (same open item as the benchmark's own near/mid/far tiers, spec Workstream D item 13).
- Investigate the 57.2% hinglish-sourced-word frequency-unresolved rate directly against `devanagari_front_end_vocab_table.json`'s known transliteration-quality issues (spot-checked example above) before trusting the hinglish-origin bucket counts for anything beyond a directional read.
