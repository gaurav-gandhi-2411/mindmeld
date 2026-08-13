# Embedding cluster-separation report

Mean silhouette over the 419-term production eval vocabulary, in each model's **raw normalized embedding space** (not the t-SNE projection). k=7, seed=42.

## Headline: both models scored on the fine-tuned model's partition

| metric | base | fine-tuned | ratio |
|---|---|---|---|
| cosine | 0.0017 | 0.0421 | 24.29x |
| euclidean | 0.0026 | 0.0247 | 9.32x |

## Control: each model scored on its own partition

| metric | base | fine-tuned | ratio |
|---|---|---|---|
| cosine | 0.0606 | 0.0421 | 0.69x |
| euclidean | 0.0370 | 0.0247 | 0.67x |

## How to read this

The headline table scores both models against KMeans labels fitted on the **fine-tuned** embeddings, so the fine-tuned model is graded on its own clustering and is favoured by construction. The control table fits KMeans separately per model and is the fairer comparison.

Silhouette ranges -1..1. Every value here is **near zero**: both spaces are weakly clustered at k=7, and a ratio between two near-zero numbers is not evidence of strong clustering. Do not quote a ratio without the absolute values beside it.

**The two tables disagree, and the disagreement is the finding.** On the fine-tuned model's own partition the fine-tune looks 9-24x better, depending on metric. On each model's own partition the BASE model scores higher. So the headline ratio does not show that fine-tuning created cluster structure -- it shows that the base space does not organise around the fine-tuned model's clusters. The base space has its own structure at k=7, and slightly more of it; fine-tuning reorganised the space rather than sharpening it.

Note also that metric choice alone moves the headline ratio from 9.3x to 24.3x, which is why both are reported and neither is chosen after the fact.

This does not weaken the fine-tune's actual result. The task metric it was trained for -- Spearman correlation on the Hinglish relatedness eval, -0.003 -> 0.813 (see reports/baseline_report.md) -- is a direct measurement of the thing that matters and is unaffected by any of the above. What this report rules out is the separate, weaker claim that the fine-tune is visible as cluster separation.
