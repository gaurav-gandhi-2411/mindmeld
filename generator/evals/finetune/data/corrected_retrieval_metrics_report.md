# Corrected retrieval metrics -- WORKSTREAM 1

Source: spec-metrics-ceiling-calibration.md WORKSTREAM 1. All numbers below are recomputed from the existing `evals/finetune/data/bakeoff_raw/*.json` checkpoints' `dim1_records` -- **zero model re-inference or re-embedding was performed**. Commit: the checkpoints predate this workstream; only the metric computation changed.

## Methodology: what was wrong, what changed

**1. NDCG was already graded, not binary.** `evals/harness/topheavy.py`'s `compute_topheavy_metrics` feeds `ndcg_from_judged` a `(actual_rank, _RELEVANCE_GRADE[tier])` pair per record, where `_RELEVANCE_GRADE = {near: 2.0, mid: 1.0, far: 0.0}` -- graded relevance, not the binary near/mid=relevant set (`_RELEVANT_TIERS`) that Precision/Recall use. `ndcg_from_judged` (`evals/harness/metrics.py`) computes standard `DCG = sum(2^rel-1 / log2(rank+1))` and `IDCG` from the ideal ordering of ALL judged items in the group (near > mid > far), exactly the graded-gain formula the task asked for. **No code change was needed for action 2** -- this section documents the finding, not a fix.

**2. |R| (the near+mid relevance-set size per secret) is 3-5, mean 4.0, across all 42 test secrets -- identical for all 8 models (it is a property of the fixture's tier labels, not of any model's embeddings; verified: True). This CONTRADICTS the task brief's working hypothesis that |R| ~ 59-60. The literal `k/|R|` identity (precision@k==1 forces recall@k <= k/|R|) does NOT reproduce here: with |R| in [3,5] and k=10, `min(k,|R|)/|R| = 1.0` for every secret -- the classical cap does not bind. **The real mechanism is different**: this benchmark judges only ~9 words per secret out of a 10,495-word vocabulary (sparse judgment). At k=10, only 18/42 secrets have ANY judged word land in the model's global top-10 at all (see `precision[10].n=18` in the superseded table below); the rest contribute nothing to Precision@10's numerator or denominator (excluded, not zero-filled). Of the secrets that DO get a hit, the hit is overwhelmingly near/mid because 'far'-tier words are deliberately authored as semantically distant decoys -- they almost never crack a global top-10 out of 10,495 candidates. That produces a near-tautological Precision@10 close to 1.000 (it mostly measures 'did a decoy leak into the top 10', which is rare by design) while Recall@10 stays low because most secrets simply have zero judged hits in a 10-wide window. **Verdict: the underlying complaint -- Precision@k is saturated/uninformative and Recall@k alone doesn't discriminate models -- is confirmed by the real data, but via a sparse-judgment mechanism, not the classical |R|>>k identity.** The fix (R-precision/MAP/|R|-scaled recall) is unaffected by which exact mechanism explains the saturation.

**3. New non-saturating metrics** (`evals/harness/topheavy.compute_nonsaturating_metrics`): **R-precision** (== recall@|R|, since precision and recall are numerically identical when the cutoff equals |R| -- standard IR fact) and **MAP** (`AP = (1/|R|) * sum_i (i / rank_i)` over relevant records sorted by rank, the standard formula) scale the cutoff to each secret's own |R| instead of a fixed k, so the metric cannot trivially saturate the way Precision@10 does. Also added: recall at FIXED k in {3,4,5,6} (`recall_at_fixed_k_near_r`), the observed |R| range, reported alongside R-precision's per-secret-adaptive cutoff so the choice of comparison k is transparent.

**4. Every new metric is bootstrap-CI'd** (`evals/finetune/bootstrap_ci.bootstrap_nonsaturating_ci`, cluster-by-secret, same resample pattern as the existing `bootstrap_topheavy_ci`) and every model-vs-shipped comparison uses a PAIRED bootstrap (`paired_bootstrap_nonsaturating_delta` / the pre-existing `paired_bootstrap_topheavy_delta`), resampling secrets once per draw and applying the same resample to both models.

## |R| (relevance-set size) distribution

| model | min |R| | max |R| | mean |R| | n secrets |
|---|---|---|---|---|
| sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 | 3 | 5 | 4.00 | 42 |
| l3cube-pune/indic-sentence-bert-nli | 3 | 5 | 4.00 | 42 |
| google/muril-base-cased | 3 | 5 | 4.00 | 42 |
| BAAI/bge-m3 | 3 | 5 | 4.00 | 42 |
| intfloat/multilingual-e5-large | 3 | 5 | 4.00 | 42 |
| ibm-granite/granite-embedding-311m-multilingual-r2 | 3 | 5 | 4.00 | 42 |
| Qwen/Qwen3-Embedding-0.6B | 3 | 5 | 4.00 | 42 |
| gauravgandhi2411/hinglish-relatedness-sbert | 3 | 5 | 4.00 | 42 |

All 8 rows are identical (True) -- |R| is a fixture property, not a model output. With mean |R|=4.0 and k=10, the classical ceiling `min(k,|R|)/|R|` would be `min(10,4)/4 = 1.000` -- i.e. 1.0, not 0.169. See Methodology point 2 for the actual mechanism.

## Corrected 8-model comparison (macro-avg over 42 secrets)

| model | NDCG@10 (graded) | Recall@10 | Precision@10 | R-precision | MAP | recall@4 (near mean |R|) |
|---|---|---|---|---|---|---|
| sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 | 0.0245 [0.0000, 0.0613] (n=42) | 0.0119 [0.0000, 0.0298] (n=42) | 1.0000 [1.0000, 1.0000] (n=2) | 0.0119 [0.0000, 0.0298] (n=42) | 0.0126 [0.0006, 0.0305] (n=42) | 0.0119 [0.0000, 0.0298] (n=42) |
| l3cube-pune/indic-sentence-bert-nli | 0.1316 [0.0688, 0.2028] (n=42) | 0.1369 [0.0655, 0.2143] (n=42) | 1.0000 [1.0000, 1.0000] (n=12) | 0.0833 [0.0417, 0.1310] (n=42) | 0.0688 [0.0370, 0.1052] (n=42) | 0.0833 [0.0417, 0.1310] (n=42) |
| google/muril-base-cased | 0.0795 [0.0391, 0.1251] (n=42) | 0.0714 [0.0417, 0.1071] (n=42) | 1.0000 [1.0000, 1.0000] (n=12) | 0.0417 [0.0179, 0.0714] (n=42) | 0.0342 [0.0170, 0.0547] (n=42) | 0.0417 [0.0179, 0.0714] (n=42) |
| BAAI/bge-m3 | 0.0323 [0.0000, 0.0736] (n=42) | 0.0179 [0.0000, 0.0417] (n=42) | 1.0000 [1.0000, 1.0000] (n=3) | 0.0179 [0.0000, 0.0417] (n=42) | 0.0162 [0.0014, 0.0352] (n=42) | 0.0179 [0.0000, 0.0417] (n=42) |
| intfloat/multilingual-e5-large | 0.0323 [0.0000, 0.0736] (n=42) | 0.0179 [0.0000, 0.0417] (n=42) | 1.0000 [1.0000, 1.0000] (n=3) | 0.0179 [0.0000, 0.0417] (n=42) | 0.0179 [0.0024, 0.0383] (n=42) | 0.0179 [0.0000, 0.0417] (n=42) |
| ibm-granite/granite-embedding-311m-multilingual-r2 | 0.0307 [0.0000, 0.0675] (n=42) | 0.0179 [0.0000, 0.0417] (n=42) | 1.0000 [1.0000, 1.0000] (n=3) | 0.0179 [0.0000, 0.0417] (n=42) | 0.0148 [0.0009, 0.0328] (n=42) | 0.0179 [0.0000, 0.0417] (n=42) |
| Qwen/Qwen3-Embedding-0.6B | 0.0441 [0.0053, 0.0914] (n=42) | 0.0357 [0.0060, 0.0833] (n=42) | 1.0000 [1.0000, 1.0000] (n=4) | 0.0298 [0.0060, 0.0655] (n=42) | 0.0239 [0.0045, 0.0478] (n=42) | 0.0298 [0.0060, 0.0655] (n=42) |
| gauravgandhi2411/hinglish-relatedness-sbert | 0.1646 [0.1015, 0.2336] (n=42) | 0.1687 [0.1051, 0.2381] (n=42) | 1.0000 [1.0000, 1.0000] (n=18) | 0.1012 [0.0595, 0.1488] (n=42) | 0.0942 [0.0591, 0.1317] (n=42) | 0.1091 [0.0655, 0.1567] (n=42) |

### Paired bootstrap deltas vs shipped model (shipped - other)

| model | NDCG@10 delta | Recall@10 delta | Precision@10 delta | R-precision delta | MAP delta |
|---|---|---|---|---|---|
| sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 | +0.1401 [+0.0825, +0.2030] (sig. improve) | +0.1567 [+0.0952, +0.2223] (sig. improve) | +0.0000 [+0.0000, +0.0000] (not sig.) | +0.0893 [+0.0476, +0.1369] (sig. improve) | +0.0816 [+0.0493, +0.1166] (sig. improve) |
| l3cube-pune/indic-sentence-bert-nli | +0.0330 [-0.0076, +0.0761] (not sig.) | +0.0317 [-0.0179, +0.0833] (not sig.) | +0.0000 [+0.0000, +0.0000] (not sig.) | +0.0179 [-0.0298, +0.0595] (not sig.) | +0.0254 [+0.0044, +0.0460] (sig. improve) |
| google/muril-base-cased | +0.0852 [+0.0415, +0.1321] (sig. improve) | +0.0972 [+0.0437, +0.1548] (sig. improve) | +0.0000 [+0.0000, +0.0000] (not sig.) | +0.0595 [+0.0238, +0.1012] (sig. improve) | +0.0600 [+0.0342, +0.0879] (sig. improve) |
| BAAI/bge-m3 | +0.1324 [+0.0759, +0.1946] (sig. improve) | +0.1508 [+0.0893, +0.2183] (sig. improve) | +0.0000 [+0.0000, +0.0000] (not sig.) | +0.0833 [+0.0417, +0.1310] (sig. improve) | +0.0780 [+0.0459, +0.1135] (sig. improve) |
| intfloat/multilingual-e5-large | +0.1324 [+0.0759, +0.1946] (sig. improve) | +0.1508 [+0.0893, +0.2183] (sig. improve) | +0.0000 [+0.0000, +0.0000] (not sig.) | +0.0833 [+0.0417, +0.1310] (sig. improve) | +0.0763 [+0.0438, +0.1119] (sig. improve) |
| ibm-granite/granite-embedding-311m-multilingual-r2 | +0.1340 [+0.0777, +0.1957] (sig. improve) | +0.1508 [+0.0893, +0.2183] (sig. improve) | +0.0000 [+0.0000, +0.0000] (not sig.) | +0.0833 [+0.0417, +0.1310] (sig. improve) | +0.0794 [+0.0473, +0.1147] (sig. improve) |
| Qwen/Qwen3-Embedding-0.6B | +0.1206 [+0.0683, +0.1785] (sig. improve) | +0.1329 [+0.0714, +0.1984] (sig. improve) | +0.0000 [+0.0000, +0.0000] (not sig.) | +0.0714 [+0.0298, +0.1190] (sig. improve) | +0.0703 [+0.0409, +0.1033] (sig. improve) |

## The l3cube NDCG@10 / Recall@10 "tie" -- does it survive?

- **NDCG@10** (already graded -- see Methodology point 1): shipped 0.1646 vs l3cube 0.1316, delta +0.0330, CI [-0.0076105334203358565, 0.07610202091021336] -> tie (CI includes 0). This was never a binary-relevance artifact (NDCG was already graded); the tie is a genuine statistical-power limit (n=42 secrets, sparse judged items per secret), not a metric-specification bug.

- **Recall@10**: shipped 0.1687 vs l3cube 0.1369, delta +0.0317, CI [-0.017857142857142863, 0.08333333333333331] -> tie (CI includes 0). Same verdict: not a saturation artifact (neither model is at a hard ceiling given real |R| in [3,5]), a genuine close call under a metric with a small effective sample size.

- **Precision@10**: shipped 1.0000 vs l3cube 1.0000, delta +0.0000 exactly 0 across ALL 10000 bootstrap draws -- this one IS a hard, uninformative saturation tie (both models pinned at 1.0000), consistent with the sparse-judgment mechanism in Methodology point 2, and the reason it is being superseded, not because either model is actually equal in retrieval quality.

- **R-precision** (non-saturating, scales cutoff to |R|): shipped 0.1012 vs l3cube 0.0833, delta +0.0179, CI [-0.029761904761904753, 0.059523809523809534] -> tie (CI includes 0).

- **MAP** (non-saturating): shipped 0.0942 vs l3cube 0.0688, delta +0.0254, CI [0.0044293670336156225, 0.046038033969300673] -> shipped leads (significant).

**Overall verdict:** the Precision@10 tie was a pure saturation artifact (both models pinned at the metric's ceiling, zero discriminating power) and is retired in favor of R-precision/MAP. The NDCG@10/Recall@10 ties were NOT binary-relevance or saturation artifacts -- NDCG was already graded and neither metric is at a hard per-secret ceiling given the real |R| distribution -- they reflect genuine statistical uncertainty at n=42 secrets. Whether the corrected non-saturating metrics (R-precision, MAP) resolve the tie one way or the other is reported above with real numbers, not asserted.

## SUPERSEDED numbers (binary-relevance-framed Precision@k/Recall@k)

Kept for continuity/audit trail per spec-metrics-ceiling-calibration.md WORKSTREAM 1 action 5 -- **do not use these to compare models**; Precision@10/@50 saturate to ~1.000 for every model (see Methodology point 2) and carry near-zero discriminating power. Reproduced verbatim from `evals/finetune/data/bakeoff_comparison.md`.

| model | dim1 Spearman [95% CI] | dim2 pass-rate [95% CI] | band-acc (overall/near/mid/far) | near/far separation | delta vs shipped |
|---|---|---|---|---|---|
| sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 | -0.0240 [-0.1404, 0.0951] | 0.0000 [0.0000, 0.0000] | 0.533 / 0.012 / 0.000 / 0.957 | 0.0222 | dim1 +0.6989 (sig. improve); dim2 +0.7400 (sig. improve) |
| l3cube-pune/indic-sentence-bert-nli | 0.4714 [0.3601, 0.5714] | 0.4200 [0.2800, 0.5600] | 0.609 / 0.393 / 0.000 / 0.943 | 0.3324 | dim1 +0.2035 (sig. improve); dim2 +0.3200 (sig. improve) |
| google/muril-base-cased | 0.2018 [0.0888, 0.3105] | 0.5000 [0.3600, 0.6400] | 0.591 / 0.321 / 0.012 / 0.933 | 0.1781 | dim1 +0.4731 (sig. improve); dim2 +0.2400 (sig. improve) |
| BAAI/bge-m3 | 0.1140 [0.0144, 0.2150] | 0.1000 [0.0200, 0.2000] | 0.554 / 0.095 / 0.012 / 0.957 | 0.0789 | dim1 +0.5609 (sig. improve); dim2 +0.6400 (sig. improve) |
| intfloat/multilingual-e5-large | 0.1790 [0.0528, 0.3029] | 0.1000 [0.0200, 0.2000] | 0.570 / 0.131 / 0.000 / 0.976 | 0.1294 | dim1 +0.4959 (sig. improve); dim2 +0.6400 (sig. improve) |
| ibm-granite/granite-embedding-311m-multilingual-r2 | 0.1604 [0.0453, 0.2702] | 0.0800 [0.0200, 0.1600] | 0.559 / 0.095 / 0.000 / 0.971 | 0.1016 | dim1 +0.5145 (sig. improve); dim2 +0.6600 (sig. improve) |
| Qwen/Qwen3-Embedding-0.6B | 0.1770 [0.0654, 0.2911] | 0.1400 [0.0600, 0.2400] | 0.562 / 0.167 / 0.000 / 0.948 | 0.1421 | dim1 +0.4979 (sig. improve); dim2 +0.6000 (sig. improve) |
| gauravgandhi2411/hinglish-relatedness-sbert | 0.6749 [0.6008, 0.7413] | 0.7400 [0.6200, 0.8600] | 0.673 / 0.655 / 0.012 / 0.948 | 0.4476 | — |

| model | NDCG@10 | NDCG@50 | NDCG@100 | MRR | Recall@10 | Recall@50 | Recall@100 | Precision@10 | Precision@50 | Precision@100 | top-weighted corr | band ECE |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 | 0.0245 [0.0000, 0.0613] (n=42) | 0.0245 [0.0000, 0.0613] (n=42) | 0.0252 [0.0000, 0.0620] (n=42) | 0.0482 [0.0004, 0.1196] (n=42) | 0.0119 [0.0000, 0.0298] (n=42) | 0.0119 [0.0000, 0.0298] (n=42) | 0.0179 [0.0000, 0.0417] (n=42) | 1.0000 [1.0000, 1.0000] (n=2) | 1.0000 [1.0000, 1.0000] (n=2) | 1.0000 [1.0000, 1.0000] (n=3) | 0.1011 [-0.0964, 0.2763] (n=42) | 0.2967 [0.2447, 0.3523] (n=42) |
| l3cube-pune/indic-sentence-bert-nli | 0.1316 [0.0688, 0.2028] (n=42) | 0.1400 [0.0757, 0.2129] (n=42) | 0.1512 [0.0855, 0.2252] (n=42) | 0.1476 [0.0743, 0.2331] (n=42) | 0.1369 [0.0655, 0.2143] (n=42) | 0.1786 [0.0952, 0.2738] (n=42) | 0.2202 [0.1250, 0.3274] (n=42) | 1.0000 [1.0000, 1.0000] (n=12) | 0.9762 [0.9231, 1.0000] (n=14) | 0.9804 [0.9333, 1.0000] (n=17) | 0.6329 [0.5279, 0.7134] (n=42) | 0.2133 [0.1817, 0.2567] (n=42) |
| google/muril-base-cased | 0.0795 [0.0391, 0.1251] (n=42) | 0.0978 [0.0552, 0.1444] (n=42) | 0.1063 [0.0631, 0.1525] (n=42) | 0.1185 [0.0524, 0.1985] (n=42) | 0.0714 [0.0417, 0.1071] (n=42) | 0.1429 [0.0893, 0.2083] (n=42) | 0.1726 [0.1071, 0.2440] (n=42) | 1.0000 [1.0000, 1.0000] (n=12) | 1.0000 [1.0000, 1.0000] (n=18) | 0.8750 [0.7368, 0.9868] (n=22) | 0.4128 [0.2908, 0.5139] (n=42) | 0.2386 [0.1954, 0.2918] (n=42) |
| BAAI/bge-m3 | 0.0323 [0.0000, 0.0736] (n=42) | 0.0323 [0.0000, 0.0736] (n=42) | 0.0349 [0.0027, 0.0755] (n=42) | 0.0607 [0.0013, 0.1328] (n=42) | 0.0179 [0.0000, 0.0417] (n=42) | 0.0179 [0.0000, 0.0417] (n=42) | 0.0298 [0.0060, 0.0595] (n=42) | 1.0000 [1.0000, 1.0000] (n=3) | 1.0000 [1.0000, 1.0000] (n=3) | 0.8000 [0.3333, 1.0000] (n=5) | 0.2460 [0.0909, 0.3789] (n=42) | 0.2281 [0.1880, 0.2883] (n=42) |
| intfloat/multilingual-e5-large | 0.0323 [0.0000, 0.0736] (n=42) | 0.0391 [0.0042, 0.0839] (n=42) | 0.0416 [0.0068, 0.0877] (n=42) | 0.0630 [0.0036, 0.1390] (n=42) | 0.0179 [0.0000, 0.0417] (n=42) | 0.0357 [0.0119, 0.0714] (n=42) | 0.0476 [0.0119, 0.0952] (n=42) | 1.0000 [1.0000, 1.0000] (n=3) | 1.0000 [1.0000, 1.0000] (n=5) | 1.0000 [1.0000, 1.0000] (n=6) | 0.3281 [0.1516, 0.4720] (n=42) | 0.2460 [0.2094, 0.3015] (n=42) |
| ibm-granite/granite-embedding-311m-multilingual-r2 | 0.0307 [0.0000, 0.0675] (n=42) | 0.0307 [0.0000, 0.0675] (n=42) | 0.0307 [0.0000, 0.0675] (n=42) | 0.0565 [0.0010, 0.1280] (n=42) | 0.0179 [0.0000, 0.0417] (n=42) | 0.0179 [0.0000, 0.0417] (n=42) | 0.0179 [0.0000, 0.0417] (n=42) | 1.0000 [1.0000, 1.0000] (n=3) | 1.0000 [1.0000, 1.0000] (n=3) | 1.0000 [1.0000, 1.0000] (n=3) | 0.2812 [0.1203, 0.4098] (n=42) | 0.1947 [0.1603, 0.2534] (n=42) |
| Qwen/Qwen3-Embedding-0.6B | 0.0441 [0.0053, 0.0914] (n=42) | 0.0490 [0.0123, 0.0967] (n=42) | 0.0549 [0.0168, 0.1020] (n=42) | 0.0687 [0.0105, 0.1455] (n=42) | 0.0357 [0.0060, 0.0833] (n=42) | 0.0536 [0.0119, 0.1071] (n=42) | 0.0714 [0.0238, 0.1250] (n=42) | 1.0000 [1.0000, 1.0000] (n=4) | 1.0000 [1.0000, 1.0000] (n=6) | 0.8889 [0.6250, 1.0000] (n=9) | 0.3303 [0.1524, 0.4728] (n=42) | 0.2137 [0.1746, 0.2703] (n=42) |
| gauravgandhi2411/hinglish-relatedness-sbert | 0.1646 [0.1015, 0.2336] (n=42) | 0.2115 [0.1405, 0.2869] (n=42) | 0.2211 [0.1511, 0.2948] (n=42) | 0.1963 [0.1205, 0.2816] (n=42) | 0.1687 [0.1051, 0.2381] (n=42) | 0.3214 [0.2143, 0.4345] (n=42) | 0.3571 [0.2500, 0.4702] (n=42) | 1.0000 [1.0000, 1.0000] (n=18) | 1.0000 [1.0000, 1.0000] (n=23) | 0.9643 [0.8846, 1.0000] (n=28) | 0.7740 [0.7101, 0.8237] (n=42) | 0.2020 [0.1700, 0.2344] (n=42) |

### Band calibration -- shipped model (gauravgandhi2411/hinglish-relatedness-sbert) only

Band-confusion matrix (rows = human-authored tier, cols = model-predicted band, cell = record count):

| tier | win | scorching | hot | warm | cold | freezing |
|---|---|---|---|---|---|---|
| near | 2 | 35 | 20 | 1 | 16 | 10 |
| mid | 0 | 16 | 15 | 1 | 25 | 27 |
| far | 0 | 0 | 9 | 0 | 41 | 158 |

Per-band precision/recall (does the model say Warm when a human meant Warm?):

| band | precision | recall | n_predicted | n_expected |
|---|---|---|---|---|
| win | 0.000 | n/a | 2 | 0 |
| scorching | 0.686 | 0.417 | 51 | 84 |
| hot | 0.455 | 0.238 | 44 | 84 |
| warm | 0.500 | 0.012 | 2 | 84 |
| cold | 0.500 | 0.197 | 82 | 208 |
| freezing | 0.810 | 0.760 | 195 | 208 |

