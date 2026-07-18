from __future__ import annotations

"""
Catastrophic-forgetting check (spec-hinglish-diagnostic-sweep.md Step 1c).

Compares base vs fine-tuned embeddings for the SAME word across three
buckets of the hi-en vocab:
  - trained:      words that appear anywhere in the assembled training data
                   (train_mnrl_pairs.jsonl / train_graded_pairs.jsonl).
  - broad_sample: a seeded-random sample of vocab words that were NEVER
                   trained on and are NOT held-out secrets/translations --
                   general Hinglish vocabulary the model should have no
                   special reason to move for.
  - held_out:     the frozen dev+test secrets and their EN translations.

drift(w) = 1 - cosine(base_embedding[w], finetuned_embedding[w]).

Diagnostic: if `broad_sample` drift is comparable in magnitude to `trained`
drift, the fine-tune is moving the WHOLE embedding space, not just the
region it was actually supervised on -- the diffuse-drift signature of
catastrophic forgetting (heavy, broad movement uncorrelated with what was
actually trained). If `broad_sample` drift is small relative to `trained`
drift, the fine-tune is behaving as a targeted local update instead, and the
capacity-control sweep (Step 1a) is the primary lever, not forgetting.

Run: uv run python -m evals.finetune.forgetting_check <checkpoint_path> [--name NAME]
"""

import json
import random
import sys
from pathlib import Path

import numpy as np

from embeddings import embed_vocab
from evals.finetune.eval_model import OFF_THE_SHELF_MODEL, _model_override
from evals.finetune.split import load_split
from vocab import load_hien_vocab

DATA_DIR = Path(__file__).parent / "data"
BROAD_SAMPLE_SIZE = 500
SAMPLE_SEED = 42


def _training_vocab() -> set[str]:
    words: set[str] = set()
    for fname, fields in (
        ("train_mnrl_pairs.jsonl", ("anchor", "positive")),
        ("train_graded_pairs.jsonl", ("sentence1", "sentence2")),
    ):
        path = DATA_DIR / fname
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            for f in fields:
                words.add(rec[f].lower())
    return words


def _cosine_row(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a_norm = a / np.linalg.norm(a, axis=1, keepdims=True)
    b_norm = b / np.linalg.norm(b, axis=1, keepdims=True)
    return np.sum(a_norm * b_norm, axis=1)


def _drift_stats(drifts: list[float]) -> dict:
    if not drifts:
        return {"n": 0, "mean": None, "median": None, "p90": None}
    arr = np.array(drifts)
    return {
        "n": len(arr),
        "mean": float(arr.mean()),
        "median": float(np.median(arr)),
        "p90": float(np.percentile(arr, 90)),
        "std": float(arr.std()),
    }


def embedding_drift_report(candidate_model_path: str) -> dict:
    split = load_split()
    held_out = {w.lower() for w in split["held_out_secrets"]} | {
        w.lower() for w in split["held_out_en_translations"]
    }
    trained = _training_vocab() - held_out  # trained words are never held-out by construction

    vocab = load_hien_vocab()
    vocab_lower = [w.lower() for w in vocab]
    non_trained_non_heldout = [
        w
        for w, wl in zip(vocab, vocab_lower, strict=True)
        if wl not in trained and wl not in held_out
    ]
    rng = random.Random(SAMPLE_SEED)
    broad_sample = rng.sample(
        non_trained_non_heldout, min(BROAD_SAMPLE_SIZE, len(non_trained_non_heldout))
    )

    trained_present = sorted(w for w in vocab if w.lower() in trained)
    held_out_present = sorted(w for w in vocab if w.lower() in held_out)

    base_matrix = embed_vocab(vocab, "hi-en")  # off-the-shelf is config.MODELS default
    with _model_override(candidate_model_path):
        ft_matrix = embed_vocab(vocab, "hi-en")

    word_to_idx = {w: i for i, w in enumerate(vocab)}

    def drifts_for(words: list[str]) -> list[float]:
        idx = [word_to_idx[w] for w in words if w in word_to_idx]
        if not idx:
            return []
        sims = _cosine_row(base_matrix[idx], ft_matrix[idx])
        return (1.0 - sims).tolist()

    report = {
        "candidate_model": candidate_model_path,
        "baseline_model": OFF_THE_SHELF_MODEL,
        "trained_vocab_drift": _drift_stats(drifts_for(trained_present)),
        "broad_sample_drift": _drift_stats(drifts_for(broad_sample)),
        "held_out_drift": _drift_stats(drifts_for(held_out_present)),
        "n_trained_words_in_vocab": len(trained_present),
        "n_held_out_words_in_vocab": len(held_out_present),
        "broad_sample_size": len(broad_sample),
    }
    trained_mean = report["trained_vocab_drift"]["mean"]
    broad_mean = report["broad_sample_drift"]["mean"]
    if trained_mean and broad_mean is not None:
        report["broad_to_trained_drift_ratio"] = broad_mean / trained_mean if trained_mean else None
        report["diffuse_drift_signature"] = (
            (broad_mean / trained_mean) > 0.5 if trained_mean else None
        )
    return report


if __name__ == "__main__":
    model_path = sys.argv[1]
    name = None
    if "--name" in sys.argv:
        name = sys.argv[sys.argv.index("--name") + 1]
    report = embedding_drift_report(model_path)
    out_name = name or Path(model_path).parent.name
    out_path = DATA_DIR / "runs" / f"{out_name}.forgetting_check.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
