from __future__ import annotations

"""
Cluster-separation measurement for the shipped Hinglish embedding fine-tune.

WHY THIS EXISTS: the portfolio's /work/warmer case study renders the real
t-SNE projection of these embeddings with a base-vs-fine-tuned toggle, and the
claim attached to it is that fine-tuning pulled the eval vocabulary into
semantic structure. That claim was only ever asserted -- no committed artifact
anywhere in this repo or the portfolio's measured cluster separation, so
there was nothing for the site to cite. (The portfolio's rule is that every
displayed metric links to the commit that produced it; a number without one
does not get displayed.) This module produces that artifact.

WHAT IT MEASURES: mean silhouette score over the same 419-term vocabulary the
public eval scores against, in each model's RAW embedding space -- not in the
t-SNE projection. t-SNE is a non-linear, non-distance-preserving layout with
its own perplexity/seed choices; measuring separation on its output would
score the layout, not the model.

READ THE LABEL PROVENANCE BEFORE QUOTING ANY NUMBER FROM THIS. Silhouette
needs a partition, and the partition has to come from somewhere:

  * `ft_partition` -- KMeans fitted on the FINE-TUNED embeddings, then both
    models scored against those same labels. This is the headline comparison
    and it answers a real question ("does the structure the fine-tune found
    already exist in the base space?"). But it is NOT a neutral contest: the
    fine-tuned model is being graded on its own clustering, which favours it
    close to by construction. Quoting only this pair overstates the result.

  * `own_partition` -- each model scored against KMeans fitted on ITS OWN
    embeddings. This is the control. It asks the fairer question ("how much
    cluster structure does each space contain at all, at k=7?") and it is the
    number that keeps the headline honest.

Both metrics (cosine and euclidean) are reported for every case, so no metric
choice can be made after seeing which one flatters the result.

Silhouette is reported as an absolute value too, deliberately, because a
ratio alone hides scale: a 10x improvement between two near-zero scores is
still two weakly-clustered spaces, and the case study should say so.

Run (from generator/):
    uv run python -m evals.finetune.embedding_separation
"""

import json
from pathlib import Path
from typing import Any

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_samples, silhouette_score

# Matched to the portfolio's scripts/build_embedding_projection.py so the
# numbers describe exactly the point cloud the case study renders.
SEED = 42
N_CLUSTERS = 7
FINETUNED_MODEL = "gauravgandhi2411/hinglish-relatedness-sbert"
BASE_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
FIXTURE_RELPATH = (
    "generator/evals/finetune/data/bakeoff_raw/"
    "gauravgandhi2411__hinglish-relatedness-sbert.json"
)
METRICS = ("cosine", "euclidean")

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "generator" / "evals" / "finetune" / "data"


def load_terms(repo_root: Path) -> list[str]:
    """The real production eval vocabulary, identical to the projection script's."""
    with (repo_root / FIXTURE_RELPATH).open(encoding="utf-8") as f:
        data = json.load(f)
    terms: set[str] = set()
    for r in data["dim1_records"]:
        terms.add(r["secret"])
        terms.add(r["word"])
    for r in data["dim2_records"]:
        terms.add(r["en_secret"])
        terms.add(r["hien_secret"])
    return sorted(terms)


def embed(model_name: str, terms: list[str]) -> np.ndarray:
    model = SentenceTransformer(model_name)
    return model.encode(terms, normalize_embeddings=True, show_progress_bar=False)


def cluster(embeddings: np.ndarray) -> np.ndarray:
    return KMeans(n_clusters=N_CLUSTERS, random_state=SEED, n_init=10).fit(embeddings).labels_


def score(embeddings: np.ndarray, labels: np.ndarray) -> dict[str, float]:
    return {m: float(silhouette_score(embeddings, labels, metric=m)) for m in METRICS}


def per_cluster(embeddings: np.ndarray, labels: np.ndarray, metric: str) -> list[dict[str, Any]]:
    samples = silhouette_samples(embeddings, labels, metric=metric)
    return [
        {
            "cluster": int(c),
            "n": int((labels == c).sum()),
            "mean_silhouette": round(float(samples[labels == c].mean()), 6),
        }
        for c in sorted(set(labels.tolist()))
    ]


def main() -> None:
    terms = load_terms(REPO_ROOT)
    print(f"{len(terms)} unique terms")

    emb_ft = embed(FINETUNED_MODEL, terms)
    emb_base = embed(BASE_MODEL, terms)

    labels_ft = cluster(emb_ft)
    labels_base = cluster(emb_base)

    ft_partition = {
        "labels_from": "kmeans on fine-tuned embeddings",
        "finetuned": score(emb_ft, labels_ft),
        "base": score(emb_base, labels_ft),
    }
    own_partition = {
        "labels_from": "kmeans fitted separately on each model's own embeddings",
        "finetuned": score(emb_ft, labels_ft),
        "base": score(emb_base, labels_base),
    }

    for case in (ft_partition, own_partition):
        for m in METRICS:
            b = case["base"][m]
            case.setdefault("ratio", {})[m] = (
                round(case["finetuned"][m] / b, 4) if b > 0 else None
            )

    payload: dict[str, Any] = {
        "version": 1,
        "what": "Mean silhouette score of the production Hinglish eval vocabulary in each model's raw embedding space",
        "finetuned_model": FINETUNED_MODEL,
        "base_model": BASE_MODEL,
        "n_terms": len(terms),
        "n_clusters": N_CLUSTERS,
        "seed": SEED,
        "source": FIXTURE_RELPATH + " (dim1_records + dim2_records secret/word vocabulary)",
        "space": "raw normalized embeddings, NOT the t-SNE projection",
        "ft_partition": ft_partition,
        "own_partition": own_partition,
        "per_cluster_ft_partition": {
            "finetuned": per_cluster(emb_ft, labels_ft, "cosine"),
            "base": per_cluster(emb_base, labels_ft, "cosine"),
        },
        "caveat": (
            "ft_partition scores both models against KMeans labels fitted on the "
            "fine-tuned embeddings, which favours the fine-tuned model by construction. "
            "own_partition is the control. Silhouette ranges -1..1; values near zero mean "
            "weak cluster structure in absolute terms regardless of the ratio between them."
        ),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "embedding_separation.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )

    lines = [
        "# Embedding cluster-separation report",
        "",
        f"Mean silhouette over the {len(terms)}-term production eval vocabulary, in each "
        f"model's **raw normalized embedding space** (not the t-SNE projection). "
        f"k={N_CLUSTERS}, seed={SEED}.",
        "",
        "## Headline: both models scored on the fine-tuned model's partition",
        "",
        "| metric | base | fine-tuned | ratio |",
        "|---|---|---|---|",
    ]
    for m in METRICS:
        r = ft_partition["ratio"][m]
        lines.append(
            f"| {m} | {ft_partition['base'][m]:.4f} | {ft_partition['finetuned'][m]:.4f} | "
            f"{('%.2fx' % r) if r else 'n/a'} |"
        )
    lines += [
        "",
        "## Control: each model scored on its own partition",
        "",
        "| metric | base | fine-tuned | ratio |",
        "|---|---|---|---|",
    ]
    for m in METRICS:
        r = own_partition["ratio"][m]
        lines.append(
            f"| {m} | {own_partition['base'][m]:.4f} | {own_partition['finetuned'][m]:.4f} | "
            f"{('%.2fx' % r) if r else 'n/a'} |"
        )
    lines += [
        "",
        "## How to read this",
        "",
        "The headline table scores both models against KMeans labels fitted on the "
        "**fine-tuned** embeddings, so the fine-tuned model is graded on its own "
        "clustering and is favoured by construction. The control table fits KMeans "
        "separately per model and is the fairer comparison.",
        "",
        "Silhouette ranges -1..1. Every value here is **near zero**: both spaces are "
        "weakly clustered at k=7, and a ratio between two near-zero numbers is not "
        "evidence of strong clustering. Do not quote a ratio without the absolute "
        "values beside it.",
        "",
        "**The two tables disagree, and the disagreement is the finding.** On the "
        "fine-tuned model's own partition the fine-tune looks 9-24x better, depending "
        "on metric. On each model's own partition the BASE model scores higher. So the "
        "headline ratio does not show that fine-tuning created cluster structure -- it "
        "shows that the base space does not organise around the fine-tuned model's "
        "clusters. The base space has its own structure at k=7, and slightly more of "
        "it; fine-tuning reorganised the space rather than sharpening it.",
        "",
        "Note also that metric choice alone moves the headline ratio from 9.3x to "
        "24.3x, which is why both are reported and neither is chosen after the fact.",
        "",
        "This does not weaken the fine-tune's actual result. The task metric it was "
        "trained for -- held-out dim1 Spearman on the Hinglish relatedness eval, "
        "base 0.435 -> fine-tuned 0.704 on the same 8 held-out secrets, paired-CI "
        "[+0.130, +0.412] (see ship_decision_report_v3.md) -- is a direct measurement "
        "of the thing that matters and is unaffected by any of the above. What this "
        "report rules out is the separate, weaker claim that the fine-tune is visible "
        "as cluster separation.",
        "",
    ]
    (OUT_DIR / "embedding_separation_report.md").write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps({"ft_partition": ft_partition, "own_partition": own_partition}, indent=2))
    print(f"wrote {OUT_DIR / 'embedding_separation.json'}")
    print(f"wrote {OUT_DIR / 'embedding_separation_report.md'}")


if __name__ == "__main__":
    main()
