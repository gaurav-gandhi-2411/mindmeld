from __future__ import annotations

"""
Embedding computation with persistent file-based cache.

Cache key = SHA-1 of (model name, sorted vocab list), stored as:
  .model-cache/{lang}-{cache_key}.npy   (float32 matrix, shape [N, D])

The model name is part of the key so that swapping MODELS[lang] to a
different checkpoint can never silently reuse a previous model's cached
vectors for the same vocab.

On cache hit the model is never loaded, so repeated builds are fast.
On cache miss the model is loaded once, vocab is embedded in batches,
vectors are L2-normalised, and the matrix is persisted.
"""

import hashlib
import logging

import numpy as np
from numpy.typing import NDArray

from config import CACHE_DIR, MODELS

logger = logging.getLogger(__name__)


def _cache_key(vocab: list[str], model_name: str) -> str:
    """Stable SHA-1 of (model name, sorted vocab list) for cache keying."""
    # Sort before hashing so insertion-order changes don't bust the cache.
    joined = model_name + "\n" + "\n".join(sorted(vocab))
    return hashlib.sha1(joined.encode()).hexdigest()  # noqa: S324


def embed_vocab(
    vocab: list[str],
    lang: str,
    batch_size: int = 512,
    show_progress: bool = True,
) -> NDArray[np.float32]:
    """
    Embed `vocab` with the model for `lang`, return L2-normalised float32 matrix.

    Shape: (len(vocab), embedding_dim)

    Results are cached to CACHE_DIR under a content-hash key so subsequent
    calls with the same vocab skip model loading entirely.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    model_name = MODELS[lang]
    key = _cache_key(vocab, model_name)
    cache_path = CACHE_DIR / f"{lang}-{key}.npy"

    if cache_path.exists():
        logger.info("embedding cache hit: %s", cache_path.name)
        matrix: NDArray[np.float32] = np.load(str(cache_path))
        return matrix

    logger.info("loading model %s for lang=%s", model_name, lang)

    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)

    logger.info("embedding %d words (batch_size=%d)", len(vocab), batch_size)
    raw: NDArray[np.float32] = model.encode(
        vocab,
        batch_size=batch_size,
        show_progress_bar=show_progress,
        convert_to_numpy=True,
        normalize_embeddings=True,  # L2-normalize within sentence-transformers
    )

    matrix = raw.astype(np.float32)

    # Belt-and-suspenders: re-normalise in case the model doesn't guarantee unit norm
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    # Avoid division by zero for zero vectors (shouldn't happen with SBERT)
    norms = np.where(norms == 0, 1.0, norms)
    matrix = (matrix / norms).astype(np.float32)

    np.save(str(cache_path), matrix)
    logger.info("saved embedding cache: %s", cache_path.name)
    return matrix


def cosine_similarities(
    matrix: NDArray[np.float32],
    query_vec: NDArray[np.float32],
) -> NDArray[np.float32]:
    """
    Compute cosine similarities between every row in `matrix` and `query_vec`.

    Both inputs are assumed to be L2-normalised (unit vectors), so cosine sim
    reduces to the dot product — O(N·D) with no sqrt overhead.

    Returns shape (N,) float32.
    """
    # query_vec shape: (D,) — reshape to (D, 1) for matrix multiplication
    return matrix @ query_vec.astype(np.float32)
