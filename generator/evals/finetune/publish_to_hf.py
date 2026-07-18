from __future__ import annotations

"""
Push the winning v3 checkpoint (obj_hard_neg -- LoRA r=8/lr=2e-4/4 epochs +
mined hard negatives, ship_decision_report_v3.md) to a PUBLIC Hugging Face
Hub model repo (portfolio asset), so the generator's build/publish flow can
reference it by repo ID (`config.MODELS["hi-en"]`) exactly like the
off-the-shelf model, instead of vendoring a ~full-BERT-base checkpoint into
git. Public: once pushed, no HF_TOKEN is needed to LOAD it (only to push).

SCRUB (mandatory): `SentenceTransformer.save()` auto-generates a README.md
that embeds literal training-sample word pairs as "widget examples" and a
training-data preview table -- caught in this session containing actual
daily-schedule game secrets (`aag`, `baarish`) and their trained
relatedness pairs. That auto-generated file is NEVER uploaded. This module
uploads every OTHER checkpoint file (weights, tokenizer, architecture
config -- inherited byte-identical from the base model's public
pretraining, no word-level training data) plus a hand-written model card
(data/hf_model_card.md) with zero game-vocabulary examples, and
additionally runs an automated scan for the auto-README's actual leak
signature (2+ distinct game secrets co-occurring on one line) as a
belt-and-suspenders check against this exact failure mode recurring.

Requires HF_TOKEN in the environment with write access (the repo is created
public if it doesn't exist -- write access is still required to push).

Run: uv run python -m evals.finetune.publish_to_hf [--repo-id OWNER/NAME]
"""

import argparse
import sys
from pathlib import Path

from evals.finetune.split import load_split

CHECKPOINT_DIR = Path(__file__).parent / "checkpoints" / "obj_hard_neg" / "model"
MODEL_CARD_PATH = Path(__file__).parent / "data" / "hf_model_card.md"
DEFAULT_REPO_ID = "gauravgandhi2411/hinglish-relatedness-sbert"

# The auto-generated README embeds literal training-sample word pairs
# (widget examples + a training-data preview table) -- never upload it.
EXCLUDED_FILENAMES = frozenset({"README.md"})


def _all_60_secrets() -> set[str]:
    split = load_split()
    all_secrets = split["train_secrets"] + split["dev_secrets"] + split["test_secrets"]
    return {s.lower() for s in all_secrets}


def _scrub_scan(extra_files: list[Path]) -> None:
    """Belt-and-suspenders scrub check, scoped to the actual risk.

    Checkpoint architecture/vocab files (config.json, tokenizer.json,
    modules.json, ...) are inherited byte-identical from the base model's
    public pretraining -- a subword vocab of ~197k pieces will trivially
    contain isolated common words (many game secrets are literally ordinary
    English words used as-is: "school", "doctor", "train"). A lone token's
    presence there reveals nothing about OUR training pairs and is not
    scanned; only hand-authored .md content (the model card -- the one file
    type that could plausibly repeat the auto-generated README's mistake)
    is checked.

    The real leak signature demonstrated by the auto-generated README
    wasn't a single secret word appearing in prose -- it was TWO OR MORE
    DISTINCT secrets co-occurring on the same line (a widget-example row,
    a training-sample table row), which reveals a trained relatedness pair.
    That's what this checks for; a lone secret mentioned in ordinary prose
    (e.g. "train" in "training data") does not trip it.
    """
    secrets = _all_60_secrets()

    hits: dict[str, list[str]] = {}
    for f in extra_files:
        if f.suffix != ".md":
            continue
        for lineno, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            words_on_line = {w.strip(".,()[]{}:;\"'`|-").lower() for w in line.split()}
            secrets_on_line = sorted(words_on_line & secrets)
            if len(secrets_on_line) >= 2:
                hits[f"{f}:{lineno}"] = secrets_on_line

    if hits:
        raise SystemExit(f"SCRUB FAILED -- 2+ game secrets co-occur on the same line: {hits}")
    print(f"scrub scan OK: {len(extra_files)} authored file(s) checked, 0 relational leaks")


def publish(repo_id: str, checkpoint_dir: Path, model_card_path: Path) -> str:
    import os

    token = os.environ.get("HF_TOKEN")
    if not token:
        raise SystemExit(
            "HF_TOKEN not set in the environment. See ship_decision_report_v3.md "
            "'Production hosting' section for how to generate one."
        )
    if not checkpoint_dir.exists():
        raise SystemExit(
            f"{checkpoint_dir} not found -- rerun the Step 1a/1b sweep "
            "(evals.finetune.step1a_capacity_sweep / step1b_objective_sweep) first."
        )

    _scrub_scan(extra_files=[model_card_path])

    from huggingface_hub import HfApi

    api = HfApi(token=token)
    api.create_repo(repo_id=repo_id, repo_type="model", private=False, exist_ok=True)
    commit_info = api.upload_folder(
        repo_id=repo_id,
        repo_type="model",
        folder_path=str(checkpoint_dir),
        ignore_patterns=list(EXCLUDED_FILENAMES),
        commit_message=(
            "obj_hard_neg: LoRA r=8/lr=2e-4/4ep + mined hard negatives -- "
            "held-out dim1_test 0.7044, dim2_test 0.8125 vs baseline 0.4350/0.375 "
            "(ship_decision_report_v3.md)"
        ),
    )
    api.upload_file(
        repo_id=repo_id,
        repo_type="model",
        path_or_fileobj=str(model_card_path),
        path_in_repo="README.md",
        commit_message="model card",
    )
    print(f"pushed {checkpoint_dir} -> https://huggingface.co/{repo_id} ({commit_info.oid[:8]})")
    return commit_info.oid


def verify_loadable(repo_id: str) -> None:
    """Load the just-pushed PUBLIC repo exactly as embeddings.py will (no
    token needed once public) to confirm it actually resolves before
    config.py is changed to point at it."""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(repo_id)
    vec = model.encode(["namaste"])
    print(f"verify OK: loaded {repo_id} with NO auth token, encoded probe -> shape {vec.shape}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID)
    parser.add_argument("--skip-verify", action="store_true")
    args = parser.parse_args()

    publish(args.repo_id, CHECKPOINT_DIR, MODEL_CARD_PATH)
    if not args.skip_verify:
        verify_loadable(args.repo_id)
    sys.exit(0)
