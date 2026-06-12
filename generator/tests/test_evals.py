from __future__ import annotations

"""
Pytest gate for the Hinglish eval fixture set.

Loads all fixtures from evals/fixtures/ and fails if ANY active fixture fails
the semantic ordering assertion. This ensures model/vocab changes that break
expected behavior are caught in CI.

The multilingual model (~470 MB) is downloaded on first run.
Subsequent runs use the HuggingFace cache.
"""

import json

import numpy as np
import pytest

from config import EVALS_FIXTURES_DIR, MODELS

_MODEL_CACHE: dict[str, object] = {}


def _get_model(lang: str = "hi-en") -> object:
    if lang not in _MODEL_CACHE:
        from sentence_transformers import SentenceTransformer

        _MODEL_CACHE[lang] = SentenceTransformer(MODELS[lang])
    return _MODEL_CACHE[lang]


def _load_all_fixtures() -> list[dict]:
    """Load all *.json files from the active fixtures directory."""
    if not EVALS_FIXTURES_DIR.exists():
        return []
    return [
        json.loads(fp.read_text(encoding="utf-8"))
        for fp in sorted(EVALS_FIXTURES_DIR.glob("*.json"))
    ]


def _embed_words(words: list[str], lang: str = "hi-en") -> dict[str, np.ndarray]:
    """Embed a list of words and return a word→vector dict."""
    model = _get_model(lang)
    vecs = model.encode(  # type: ignore[union-attr]
        words,
        batch_size=len(words),
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    return {w: vecs[i].astype(np.float32) for i, w in enumerate(words)}


# ---------------------------------------------------------------------------
# Collect fixtures as parametrize inputs at module load time
# ---------------------------------------------------------------------------

_FIXTURES = _load_all_fixtures()


@pytest.mark.parametrize(
    "fixture",
    _FIXTURES,
    ids=[f.get("id", "?") for f in _FIXTURES],
)
def test_eval_fixture(fixture: dict) -> None:
    """
    Assert cos(anchor, closer) > cos(anchor, farther) for one fixture.

    If this test fails, it means either:
    1. The model changed and broke a previously-valid ordering, or
    2. A fixture was incorrectly authored.

    In case 2, move the fixture to fixtures_known_failures/ with a "reason" field.
    """
    anchor: str = fixture["anchor"]
    closer: str = fixture["closer"]
    farther: str = fixture["farther"]
    lang: str = fixture.get("lang", "hi-en")

    word_vec = _embed_words([anchor, closer, farther], lang)
    v_anchor = word_vec[anchor]
    v_closer = word_vec[closer]
    v_farther = word_vec[farther]

    sim_closer = float(np.dot(v_anchor, v_closer))
    sim_farther = float(np.dot(v_anchor, v_farther))

    assert sim_closer > sim_farther, (
        f"Fixture {fixture.get('id')}: "
        f"cos({anchor},{closer})={sim_closer:.4f} NOT > "
        f"cos({anchor},{farther})={sim_farther:.4f} — "
        f"note: {fixture.get('note', '')}"
    )
