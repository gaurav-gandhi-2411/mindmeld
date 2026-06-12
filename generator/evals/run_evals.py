from __future__ import annotations

"""
Hinglish semantic ordering eval runner.

Loads all fixture JSON files from evals/fixtures/, embeds the three words
(anchor, closer, farther) using the hi-en multilingual model, and asserts:

    cos(anchor, closer) > cos(anchor, farther)

Prints per-fixture pass/fail and an overall pass rate.
Known-failure fixtures (in fixtures_known_failures/) are NOT run here —
they document model limitations without blocking the build.

Usage:
    python evals/run_evals.py
"""

import json
import sys
from pathlib import Path

# Script-mode sys.path: needed when run directly (not via pytest + conftest).
# noqa: E402 suppressed because this must come before local imports.
_GENERATOR_DIR = Path(__file__).parent.parent
if str(_GENERATOR_DIR) not in sys.path:
    sys.path.insert(0, str(_GENERATOR_DIR))  # noqa: E402

import numpy as np  # noqa: E402

from config import EVALS_FIXTURES_DIR, EVALS_KNOWN_FAILURES_DIR, MODELS  # noqa: E402

_MODEL_CACHE: dict[str, object] = {}


def _get_model(lang: str = "hi-en") -> object:
    if lang not in _MODEL_CACHE:
        from sentence_transformers import SentenceTransformer

        _MODEL_CACHE[lang] = SentenceTransformer(MODELS[lang])
    return _MODEL_CACHE[lang]


def embed_words(words: list[str], lang: str = "hi-en") -> np.ndarray:
    """
    Embed a list of words with the given language model.

    Returns L2-normalised float32 matrix, shape (len(words), D).
    Batches all words in one call to minimize model overhead.
    """
    model = _get_model(lang)
    vecs = model.encode(  # type: ignore[union-attr]
        words,
        batch_size=len(words),
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    return vecs.astype(np.float32)


def load_fixtures(fixtures_dir: Path) -> list[dict]:
    """Load all *.json fixture files from the given directory."""
    fixtures = []
    for fp in sorted(fixtures_dir.glob("*.json")):
        with fp.open(encoding="utf-8") as fh:
            fixtures.append(json.load(fh))
    return fixtures


def run_fixtures(fixtures: list[dict], verbose: bool = True) -> tuple[int, int]:
    """
    Run all fixtures and return (passed, total).

    Each fixture asserts cos(anchor, closer) > cos(anchor, farther).
    Words are embedded in a single batch per fixture for efficiency.
    """
    passed = 0
    total = len(fixtures)

    for fix in fixtures:
        fid = fix.get("id", "?")
        anchor = fix["anchor"]
        closer = fix["closer"]
        farther = fix["farther"]
        lang = fix.get("lang", "hi-en")

        words = [anchor, closer, farther]
        vecs = embed_words(words, lang)
        v_anchor, v_closer, v_farther = vecs[0], vecs[1], vecs[2]

        sim_closer = float(np.dot(v_anchor, v_closer))
        sim_farther = float(np.dot(v_anchor, v_farther))

        ok = sim_closer > sim_farther
        if ok:
            passed += 1

        if verbose:
            status = "PASS" if ok else "FAIL"
            note = fix.get("note", "")
            print(
                f"  [{status}] {fid}: cos({anchor},{closer})={sim_closer:.4f} "
                f"> cos({anchor},{farther})={sim_farther:.4f}  ({note})"
            )

    return passed, total


def main() -> None:
    if not EVALS_FIXTURES_DIR.exists():
        print(f"No fixtures directory found at {EVALS_FIXTURES_DIR}")
        sys.exit(1)

    fixtures = load_fixtures(EVALS_FIXTURES_DIR)
    if not fixtures:
        print("No fixture files found.")
        sys.exit(1)

    print(f"Running {len(fixtures)} eval fixtures (lang=hi-en multilingual model)...\n")
    passed, total = run_fixtures(fixtures, verbose=True)

    rate = passed / total * 100 if total else 0
    print(f"\nResult: {passed}/{total} passed ({rate:.1f}%)")

    known_failures_dir = EVALS_KNOWN_FAILURES_DIR
    if known_failures_dir.exists():
        kf = list(known_failures_dir.glob("*.json"))
        if kf:
            print(f"Known failures (documented, not blocking): {len(kf)} fixture(s)")

    if passed < total:
        print("FAIL: some fixtures did not pass.")
        sys.exit(1)
    else:
        print("All fixtures passed.")


if __name__ == "__main__":
    main()
