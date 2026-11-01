from __future__ import annotations

"""
The expanded blocklist (profanity_*.txt + vendored LDNOOBW + curated supplements) must
be applied when vocab is LOADED, so guessable vocab, hints and secret validation -- which
all derive from the loaded vocab -- can never contain a blocklisted word.

Uses the real committed vocab files and a seeded random embedding matrix (no model load,
no network).
"""

import numpy as np
import pytest

from payload import build_payload
from profanity import load_en_profanity, load_hi_profanity
from schedule import load_schedule, validate_schedule
from vocab import load_en_vocab, load_hien_vocab

# Words a prior audit found in en.txt that the original blocklist missed.
_AUDIT_WORDS = ["nazi", "nazis", "hitler", "negro", "negroes", "pedophile", "molester", "fetish"]
_AUDIT_WORDS += ["hooker", "naked", "boobs", "cum", "anal"]


@pytest.fixture(scope="module")
def en_vocab() -> list[str]:
    return load_en_vocab()


@pytest.fixture(scope="module")
def hien_vocab() -> list[str]:
    return load_hien_vocab()


def test_union_blocklists_include_all_sources() -> None:
    en, hi = load_en_profanity(), load_hi_profanity()
    assert {"nazi", "hitler", "ass"} <= en  # supplement + original/LDNOOBW
    assert {"gandu", "chamar", "bhangi", "randi"} <= hi
    assert "sexual" in en  # LDNOOBW-only entry


@pytest.mark.parametrize("word", _AUDIT_WORDS)
def test_audit_words_absent_from_both_vocabs(
    word: str, en_vocab: list[str], hien_vocab: list[str]
) -> None:
    assert word not in en_vocab
    assert word not in hien_vocab


def test_no_blocklisted_word_in_en_vocab(en_vocab: list[str]) -> None:
    assert not set(en_vocab) & load_en_profanity()


def test_no_blocklisted_word_in_hien_vocab(hien_vocab: list[str]) -> None:
    assert not set(hien_vocab) & (load_en_profanity() | load_hi_profanity())


@pytest.mark.parametrize("lang", ["en", "hi-en"])
def test_committed_schedule_still_validates(
    lang: str, en_vocab: list[str], hien_vocab: list[str]
) -> None:
    vocab = en_vocab if lang == "en" else hien_vocab
    assert validate_schedule(lang, vocab, load_schedule(lang))


@pytest.mark.parametrize("lang", ["en", "hi-en"])
def test_hints_come_only_from_loaded_vocab(
    lang: str, en_vocab: list[str], hien_vocab: list[str]
) -> None:
    from datetime import date

    vocab = en_vocab if lang == "en" else hien_vocab
    secret = load_schedule(lang)[0]
    rng = np.random.default_rng(42)
    matrix = rng.standard_normal((len(vocab), 16)).astype(np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    payload = build_payload(vocab, matrix, secret, lang, date(2026, 11, 1))
    blocklist = load_en_profanity() | (load_hi_profanity() if lang == "hi-en" else frozenset())
    hint_words = [w for _rank, w in payload["hints"]]
    assert hint_words
    assert set(hint_words) <= set(vocab)
    assert not set(hint_words) & blocklist


def test_en_vocab_applies_union_en_hi_blocklist(en_vocab: list[str]) -> None:
    # India-first audience: EN vocab must also exclude HI-only entries (lauda, randi, ...).
    assert not set(en_vocab) & (load_en_profanity() | load_hi_profanity())


@pytest.mark.parametrize("lang", ["en", "hi-en"])
def test_no_guess_acceptance_key_hashes_a_blocklisted_word(
    lang: str, en_vocab: list[str], hien_vocab: list[str]
) -> None:
    """Neither `words` nor `alt` (fold/alias-derived) may accept a blocklisted string."""
    from datetime import date

    from config import derive_salt
    from payload import _word_hash

    vocab = en_vocab if lang == "en" else hien_vocab
    day = date(2026, 11, 1)
    rng = np.random.default_rng(42)
    matrix = rng.standard_normal((len(vocab), 16)).astype(np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    payload = build_payload(vocab, matrix, load_schedule(lang)[0], lang, day)
    salt = derive_salt(day, lang)
    accepted = set(payload["words"]) | set(payload.get("alt", {}))
    blocked = {w: _word_hash(w, salt) for w in load_en_profanity() | load_hi_profanity()}
    leaked = sorted(w for w, h in blocked.items() if h in accepted)
    assert not leaked
