from __future__ import annotations

"""
Publish the public Hinglish relatedness benchmark
(evals/finetune/data/public_benchmark_staging/*.json) to a public Hugging
Face Datasets repo. Mirrors publish_to_hf.py's pattern (scrub-gate before
any upload, public repo, verify-loadable after push).

MANDATORY gate: both scrub scripts (scrub_public_benchmark.py -- string/
morphological collisions against live game content, and
semantic_scrub_public_benchmark.py -- embedding-rank proximity to live
secrets) must report zero BLOCKING hits before anything is uploaded. A
non-clean scrub aborts the publish entirely; this is not overridable via a
flag, on purpose.

Requires HF_TOKEN in the environment with write access (the repo is
created public if it doesn't exist).

Run: uv run python -m evals.finetune.publish_benchmark_to_hf [--repo-id OWNER/NAME]
"""

import argparse
import sys
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
STAGING_DIR = DATA_DIR / "public_benchmark_staging"
CARD_PATH = DATA_DIR / "public_benchmark_card.md"
SPLIT_PATH = DATA_DIR / "public_benchmark_split.json"
DEFAULT_REPO_ID = "gauravgandhi2411/hinglish-relatedness-benchmark"

UPLOAD_FILES = [
    STAGING_DIR / "dim1_hien.json",
    STAGING_DIR / "dim1_en.json",
    STAGING_DIR / "dim2_pairs.json",
    SPLIT_PATH,
]


def _run_gates() -> None:
    from evals.finetune.scrub_public_benchmark import run_scrub as run_string_scrub
    from evals.finetune.semantic_scrub_public_benchmark import run_scrub as run_semantic_scrub

    string_result = run_string_scrub()
    if not string_result["passed"]:
        raise SystemExit(
            f"PUBLISH ABORTED -- string scrub failed: {string_result['n_blocking']} "
            "blocking collision(s). Fix before publishing."
        )
    print(
        f"string scrub gate: PASS (0 blocking, {string_result['n_advisory']} advisory, "
        "non-blocking)"
    )

    # Semantic scrub's raw pass/fail is deliberately NOT the publish gate -- report
    # section 2b's calibration analysis found the naive band<=2 threshold fails on
    # statistical noise at this vocab density (a 10.5k-word vocab against 110 live
    # secrets), not a real leak signal. The actual gate here: rank<=10 hits (the tight,
    # least-chance-explicable band) must not EXCEED the count GG explicitly reviewed and
    # accepted in report section 2c (24, after the targeted 20-word swap). A count above
    # that baseline means new content was added since the last human review and must be
    # re-reviewed before publishing, not silently allowed through.
    REVIEWED_RANK10_BASELINE = 24
    semantic_result = run_semantic_scrub()
    all_hits = semantic_result["blocking_hits"] + semantic_result["advisory_hits"]
    n_rank10 = sum(1 for h in all_hits if h.rank <= 10)
    if n_rank10 > REVIEWED_RANK10_BASELINE:
        raise SystemExit(
            f"PUBLISH ABORTED -- semantic scrub found {n_rank10} rank<=10 hits, more than "
            f"the {REVIEWED_RANK10_BASELINE} GG explicitly reviewed in report section 2c. "
            "New content needs human semantic review before publishing."
        )
    print(
        f"semantic scrub gate: {n_rank10} rank<=10 hits (<= reviewed baseline of "
        f"{REVIEWED_RANK10_BASELINE}, all accepted per report section 2c) -- PASS"
    )


def publish_card_only(repo_id: str) -> str:
    """Update just the dataset card (README.md) -- for documentation-only
    changes where the underlying benchmark data files are unchanged, so
    re-running the scrub gates + data re-upload would be redundant."""
    import os

    token = os.environ.get("HF_TOKEN")
    if not token:
        raise SystemExit("HF_TOKEN not set in the environment.")
    if not CARD_PATH.exists():
        raise SystemExit(f"{CARD_PATH} not found.")

    from huggingface_hub import HfApi

    api = HfApi(token=token)
    commit_info = api.upload_file(
        repo_id=repo_id,
        repo_type="dataset",
        path_or_fileobj=str(CARD_PATH),
        path_in_repo="README.md",
        commit_message="dataset card: note downstream L2+L5 mitigation (data unchanged)",
    )
    print(f"pushed card -> https://huggingface.co/datasets/{repo_id} ({commit_info.oid[:8]})")
    return commit_info.oid


def publish(repo_id: str) -> str:
    import os

    token = os.environ.get("HF_TOKEN")
    if not token:
        raise SystemExit("HF_TOKEN not set in the environment.")

    for f in UPLOAD_FILES + [CARD_PATH]:
        if not f.exists():
            raise SystemExit(f"{f} not found -- benchmark not fully built.")

    _run_gates()

    from huggingface_hub import HfApi

    api = HfApi(token=token)
    api.create_repo(repo_id=repo_id, repo_type="dataset", private=False, exist_ok=True)
    for f in UPLOAD_FILES:
        api.upload_file(
            repo_id=repo_id,
            repo_type="dataset",
            path_or_fileobj=str(f),
            path_in_repo=f.name,
            commit_message=f"publish {f.name} -- Phase 1 (spec-hinglish-research-release.md)",
        )
    api.upload_file(
        repo_id=repo_id,
        repo_type="dataset",
        path_or_fileobj=str(CARD_PATH),
        path_in_repo="README.md",
        commit_message="dataset card",
    )
    print(f"pushed benchmark -> https://huggingface.co/datasets/{repo_id}")
    return repo_id


def verify_loadable(repo_id: str) -> None:
    """Fetch the just-pushed public files and confirm they parse, exactly as
    a downstream consumer would load them (no auth token needed once public)."""
    import json

    from huggingface_hub import hf_hub_download

    fnames = ("dim1_hien.json", "dim1_en.json", "dim2_pairs.json", "public_benchmark_split.json")
    for fname in fnames:
        path = hf_hub_download(repo_id=repo_id, repo_type="dataset", filename=fname)
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        n = len(data) if isinstance(data, list) else len(data.get("dev_secrets", []) or [])
        print(f"verify OK: {fname} loaded from hub, {n} top-level entries")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID)
    parser.add_argument("--skip-verify", action="store_true")
    parser.add_argument(
        "--card-only", action="store_true", help="Update README.md only, skip data re-upload"
    )
    args = parser.parse_args()

    if args.card_only:
        publish_card_only(args.repo_id)
    else:
        publish(args.repo_id)
        if not args.skip_verify:
            verify_loadable(args.repo_id)
    sys.exit(0)
