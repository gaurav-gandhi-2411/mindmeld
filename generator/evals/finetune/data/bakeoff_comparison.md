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
