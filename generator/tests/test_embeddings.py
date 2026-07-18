from __future__ import annotations

"""
Regression tests for embeddings.py's cache key (P0 fix, 2026-07-18).

Root cause (see embeddings.py module docstring and commit 78df6f2): the
cache key used to be a SHA-1 of the SORTED vocab list, but the cached
.npy matrix's rows are laid out in the vocab's ACTUAL order at embedding
time. Two callers passing the same word SET in a different ORDER produced
an identical (sorted) cache key but the second caller silently received
the first caller's row alignment -- a same-index-different-word
corruption with no error raised. This already happened once in
production history (a same-set reorder of vocab/en.txt collided with a
stale cache entry and corrupted EN-mode rank computation, dim1_en
Spearman 0.837 -> 0.165) before being caught and hand-fixed.

These tests pin the fixed behavior: the cache key must be order-sensitive,
and embed_vocab must never serve a stale/misaligned matrix for a reordered
vocab.
"""

import sys
import types
from pathlib import Path

import numpy as np
import pytest

import config
from embeddings import _cache_key, embed_vocab


def test_cache_key_differs_for_reordered_vocab_same_set():
    """Same word SET, different ORDER -> different cache keys.

    This is the exact defect: the old implementation sorted before
    hashing, so this assertion used to FAIL (both orderings hashed to the
    same key) despite the cached rows being order-dependent.
    """
    vocab_a = ["dog", "cat", "bird"]
    vocab_b = ["bird", "dog", "cat"]
    assert _cache_key(vocab_a, "some-model") != _cache_key(vocab_b, "some-model")


def test_cache_key_stable_for_same_order():
    vocab = ["dog", "cat", "bird"]
    assert _cache_key(list(vocab), "some-model") == _cache_key(list(vocab), "some-model")


def test_cache_key_differs_by_model_name():
    vocab = ["dog", "cat", "bird"]
    assert _cache_key(vocab, "model-a") != _cache_key(vocab, "model-b")


class _FakeSentenceTransformer:
    """Deterministic stand-in for SentenceTransformer: encodes each word as
    a unit vector whose direction is keyed to the WORD, not its position,
    so a correct implementation returns the same vector for a word
    regardless of where it sits in the batch -- but a row/index mix-up
    (the bug this guards against) would return a DIFFERENT word's vector
    at a given row, which the test below detects.
    """

    def __init__(self, model_name: str, token: str | None = None) -> None:
        del model_name, token

    def encode(
        self,
        vocab: list[str],
        batch_size: int = 512,
        show_progress_bar: bool = True,
        convert_to_numpy: bool = True,
        normalize_embeddings: bool = True,
    ) -> np.ndarray:
        del batch_size, show_progress_bar, convert_to_numpy, normalize_embeddings
        # 2D embedding: [hash-derived x, hash-derived y], L2-normalised.
        # Purely a function of the WORD so the "correct" matrix is the same
        # regardless of what order the word appears in.
        vecs = np.zeros((len(vocab), 2), dtype=np.float32)
        for i, word in enumerate(vocab):
            h = hash(word) % 1000
            vecs[i] = [np.cos(h), np.sin(h)]
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return (vecs / norms).astype(np.float32)


@pytest.fixture
def _fake_sentence_transformers(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = types.ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = _FakeSentenceTransformer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)


def _word_vector(word: str) -> np.ndarray:
    h = hash(word) % 1000
    v = np.array([np.cos(h), np.sin(h)], dtype=np.float32)
    return v / np.linalg.norm(v)


def test_embed_vocab_reordered_vocab_never_returns_misaligned_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _fake_sentence_transformers: None
) -> None:
    """
    The regression scenario: embed vocab in order A (populates the cache),
    then embed the SAME word set in order B. Every row returned for order B
    must correspond to the word at that row's position in B -- never a
    stale row copied from A's layout.
    """
    monkeypatch.setattr("embeddings.CACHE_DIR", tmp_path)
    monkeypatch.setitem(config.MODELS, "en", "fake-model")

    vocab_a = ["dog", "cat", "bird", "fish"]
    vocab_b = ["fish", "bird", "dog", "cat"]  # same set, different order

    matrix_a = embed_vocab(vocab_a, "en", show_progress=False)
    matrix_b = embed_vocab(vocab_b, "en", show_progress=False)

    # Two distinct cache files must exist -- no key collision.
    cache_files = list(tmp_path.glob("en-*.npy"))
    assert len(cache_files) == 2

    for i, word in enumerate(vocab_b):
        expected = _word_vector(word)
        actual = matrix_b[i]
        cos_sim = float(np.dot(expected, actual))
        assert cos_sim > 0.999, (
            f"row {i} of matrix_b ({word!r}) does not match its own embedding "
            f"(cos_sim={cos_sim:.4f}) -- stale/misaligned cache row"
        )

    for i, word in enumerate(vocab_a):
        expected = _word_vector(word)
        actual = matrix_a[i]
        cos_sim = float(np.dot(expected, actual))
        assert cos_sim > 0.999, f"row {i} of matrix_a ({word!r}) misaligned"
