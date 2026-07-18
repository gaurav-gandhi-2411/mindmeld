| model | dim1 Spearman [95% CI] | dim2 pass-rate [95% CI] | band-acc (overall/near/mid/far) | near/far separation | delta vs shipped |
|---|---|---|---|---|---|
| sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 | -0.0558 [-0.1774, 0.0713] | 0.0000 [0.0000, 0.0000] | 0.538 / 0.012 / 0.000 / 0.967 | 0.0160 | dim1 +0.7122 (sig. improve); dim2 +0.7111 (sig. improve) |
| l3cube-pune/indic-sentence-bert-nli | 0.4364 [0.3049, 0.5528] | 0.4222 [0.2889, 0.5778] | 0.594 / 0.298 / 0.000 / 0.952 | 0.3356 | dim1 +0.2201 (sig. improve); dim2 +0.2889 (sig. improve) |
| google/muril-base-cased | 0.3363 [0.2263, 0.4418] | 0.5111 [0.3556, 0.6667] | 0.586 / 0.274 / 0.012 / 0.943 | 0.2904 | dim1 +0.3202 (sig. improve); dim2 +0.2000 (sig. improve) |
| BAAI/bge-m3 | 0.1541 [0.0541, 0.2536] | 0.0889 [0.0222, 0.1778] | 0.554 / 0.083 / 0.000 / 0.967 | 0.1249 | dim1 +0.5024 (sig. improve); dim2 +0.6222 (sig. improve) |
| intfloat/multilingual-e5-large | 0.1871 [0.0548, 0.3135] | 0.0889 [0.0222, 0.1778] | 0.562 / 0.071 / 0.000 / 0.986 | 0.1140 | dim1 +0.4694 (sig. improve); dim2 +0.6222 (sig. improve) |
| ibm-granite/granite-embedding-311m-multilingual-r2 | 0.1938 [0.0731, 0.3107] | 0.0222 [0.0000, 0.0667] | 0.554 / 0.048 / 0.000 / 0.981 | 0.1293 | dim1 +0.4627 (sig. improve); dim2 +0.6889 (sig. improve) |
| Qwen/Qwen3-Embedding-0.6B | 0.1833 [0.0679, 0.2969] | 0.1333 [0.0444, 0.2444] | 0.557 / 0.119 / 0.000 / 0.957 | 0.1483 | dim1 +0.4731 (sig. improve); dim2 +0.5778 (sig. improve) |
| gauravgandhi2411/hinglish-relatedness-sbert | 0.6565 [0.5730, 0.7289] | 0.7111 [0.5778, 0.8444] | 0.631 / 0.464 / 0.012 / 0.948 | 0.4531 | — |
