from __future__ import annotations

"""
Ranks in a payload must be a permutation of 1..n (unique, contiguous). The L5
commonsense override (hi-en) forces one word to the scorching cutoff rank; it must
shift the words in between rather than leave a duplicate rank and a hole.
"""

from datetime import date

import numpy as np
import pytest

from payload import build_payload
from rival import scorching_cutoff
from vocab import load_commonsense_overrides, load_hien_vocab

_DATE = date(2026, 11, 1)


def _random_unit_matrix(n: int, dim: int = 16) -> np.ndarray:
    rng = np.random.default_rng(42)
    m = rng.standard_normal((n, dim)).astype(np.float32)
    return (m / np.linalg.norm(m, axis=1, keepdims=True)).astype(np.float32)


@pytest.fixture(scope="module")
def hien_vocab() -> list[str]:
    return load_hien_vocab()


@pytest.mark.parametrize("secret", sorted(load_commonsense_overrides()))
def test_override_keeps_ranks_a_permutation(secret: str, hien_vocab: list[str]) -> None:
    related = load_commonsense_overrides()[secret]
    assert secret in hien_vocab and related in hien_vocab
    payload = build_payload(
        hien_vocab, _random_unit_matrix(len(hien_vocab)), secret, "hi-en", _DATE
    )
    ranks = sorted(rank for rank, _qsim in payload["words"].values())
    assert ranks == list(range(1, len(hien_vocab) + 1))


def test_override_word_lands_at_forced_rank_and_neighbours_shift(hien_vocab: list[str]) -> None:
    secret = "tarbooz"
    related = load_commonsense_overrides()[secret]
    matrix = _random_unit_matrix(len(hien_vocab))
    cutoff = scorching_cutoff(len(hien_vocab))
    payload = build_payload(hien_vocab, matrix, secret, "hi-en", _DATE)
    hint_by_rank = {rank: word for rank, word in payload["hints"]}
    # Rank-50 hint is a HINT_RANKS entry; with the override it must be the related word.
    assert cutoff == 50
    assert hint_by_rank[cutoff] == related


@pytest.mark.parametrize("secret", ["tarbooz", "til"])
def test_override_keeps_qsim_non_increasing_in_rank(secret: str, hien_vocab: list[str]) -> None:
    """The displayed similarity must never rise as rank worsens (ties allowed)."""
    payload = build_payload(
        hien_vocab, _random_unit_matrix(len(hien_vocab)), secret, "hi-en", _DATE
    )
    by_rank = sorted(payload["words"].values())
    qsims = [q for _r, q in by_rank]
    assert all(a >= b for a, b in zip(qsims, qsims[1:], strict=False))
