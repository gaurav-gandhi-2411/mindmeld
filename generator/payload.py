from __future__ import annotations

"""
Payload emission for daily Mindmeld puzzles.

Anti-cheat design:
  - The secret word NEVER appears as a plaintext JSON key.
  - Every word is keyed by sha1((word + salt).encode())[:12] hex.
  - The secret is XOR-obfuscated in the "s" field; only the app reveal
    flow decodes it (on win or give-up), so a casual JSON inspection
    cannot read the secret.
  - Rank 1 == secret word; no other word can be rank 1.

Quantization:
  qsim = round((cosine_sim + 1) * QSIM_SCALE)
  cosine_sim ≈ (qsim / QSIM_SCALE) - QSIM_OFFSET
  Round-trip error < 1e-4 by construction (step size ≈ 3e-5).
"""

import base64
import gzip
import hashlib
import io
import json
from datetime import date
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from config import (
    HINT_RANKS,
    MODELS,
    PAYLOAD_VERSION,
    QSIM_OFFSET,
    QSIM_SCALE,
    derive_obfuscate_key,
    derive_salt,
    derive_salt_for_key,
)
from embeddings import cosine_similarities
from normalize import load_alias_map, normalize
from rival import generate_rival_data


def levenshtein(a: str, b: str) -> int:
    """
    Compute the Levenshtein edit distance between two strings.

    Pure-Python implementation; no external dependencies.
    Uses the standard two-row DP formulation for O(min(|a|,|b|)) space.
    """
    if len(a) < len(b):
        a, b = b, a
    # len(a) >= len(b) now
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for ch_a in a:
        curr = [prev[0] + 1]
        for j, ch_b in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (0 if ch_a == ch_b else 1)))
        prev = curr
    return prev[-1]


def _is_morphological_variant(candidate: str, secret: str) -> bool:
    """
    Return True if `candidate` is too similar to `secret` to be a safe hint.

    Excludes candidates that:
    - Are a prefix of the secret (e.g. "ocean" is prefix of "oceanic")
    - Have the secret as a prefix (e.g. "oceans" starts with "ocean")
    - Contain the secret as a substring (e.g. "gunfire" contains "fire" — leaks the secret
      when the hint appears in plaintext JSON)
    - Have the secret contain the candidate as a substring (symmetry)
    - Are within Levenshtein distance 2 of the secret (catches plurals, -ed, -ing variants)
    """
    return (
        candidate.startswith(secret)
        or secret.startswith(candidate)
        or secret in candidate
        or candidate in secret
        or levenshtein(candidate, secret) <= 2
    )


def quantize(sim: float) -> int:
    """
    Map cosine similarity ∈ [-1, 1] → integer ∈ [0, 65535].

    Step size ≈ 3.05e-5; max round-trip error < 1e-4.
    """
    return int(round((sim + QSIM_OFFSET) * QSIM_SCALE))


def dequantize(qsim: int) -> float:
    """Inverse of quantize; recovers cosine similarity from stored integer."""
    return (qsim / QSIM_SCALE) - QSIM_OFFSET


def _word_hash(word: str, salt: str) -> str:
    """
    Return 12-char hex hash keying a word in the payload.

    Using the salt prevents precomputed rainbow tables from mapping
    hash → word before the puzzle day starts.
    """
    raw = f"{word.lower()}{salt}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]  # noqa: S324


def _obfuscate_secret(secret: str, salt: str) -> str:
    """
    XOR the UTF-8 bytes of `secret` with a repeating key derived from `salt`.

    Returns a base64-encoded string safe for JSON. This is obfuscation, not
    encryption — the key is derivable from the public payload, but a simple
    text search of the JSON will not reveal the secret word.
    """
    encoded = secret.lower().encode("utf-8")
    key = derive_obfuscate_key(salt, len(encoded))
    xored = bytes(a ^ b for a, b in zip(encoded, key, strict=True))
    return base64.b64encode(xored).decode("ascii")


def decode_secret(payload: dict) -> str:
    """
    Decode the obfuscated secret from a payload dict.

    Public API used by tests and the app's reveal flow.
    """
    salt: str = payload["salt"]
    s_b64: str = payload["s"]
    xored = base64.b64decode(s_b64)
    key = derive_obfuscate_key(salt, len(xored))
    plain = bytes(a ^ b for a, b in zip(xored, key, strict=True))
    return plain.decode("utf-8")


def _build_payload_core(
    vocab: list[str],
    matrix: NDArray[np.float32],
    secret: str,
    lang: str,
    salt: str,
    key_str: str,
    clue: str,
) -> dict:
    """
    Build the full payload dict shared by daily and pack puzzles.

    Parameters
    ----------
    vocab:
        Ordered word list; matrix[i] is the embedding for vocab[i].
    matrix:
        L2-normalised embedding matrix, shape (len(vocab), D).
    secret:
        The secret word for this puzzle. Must be in vocab.
    lang:
        Language key ("en" or "hi-en").
    salt:
        Pre-derived anti-cheat salt for this puzzle (see derive_salt /
        derive_salt_for_key in config.py).
    key_str:
        The value stored in the "date" field and used to seed the rival
        paths — an ISO date for daily puzzles, or an opaque "{packId}-{NNN}"
        key for pack puzzles.
    clue:
        Plaintext clue string for this puzzle.

    Returns
    -------
    dict
        Payload ready for json.dumps + gzip.
    """
    secret_lower = secret.lower()
    if secret_lower not in vocab:
        raise ValueError(f"Secret word {secret_lower!r} is not in vocab")

    secret_idx = vocab.index(secret_lower)
    secret_vec = matrix[secret_idx]

    # Cosine similarities: shape (N,)
    sims = cosine_similarities(matrix, secret_vec)

    # Ranks: argsort descending, then map index → rank (1-based, rank 1 = secret)
    order = np.argsort(-sims)  # descending by similarity
    ranks = np.empty(len(vocab), dtype=np.int32)
    for rank_minus1, idx in enumerate(order):
        ranks[idx] = rank_minus1 + 1

    # Build words dict: {hash12: [rank, qsim]}
    words_map: dict[str, list[int]] = {}
    seen_hashes: set[str] = set()
    for i, word in enumerate(vocab):
        h = _word_hash(word, salt)
        if h in seen_hashes:
            raise AssertionError(f"Hash collision at word index {i}: word={word!r}, hash={h!r}")
        seen_hashes.add(h)
        words_map[h] = [int(ranks[i]), quantize(float(sims[i]))]

    # Alt map: hi-en only — variant spellings that hash to canonical word's [rank, qsim].
    # For every vocab word w where normalize(w) != w, and for every alias from the alias
    # file, emit hash12(variant+salt) → [rank, qsim] of the canonical word.
    # Rules:
    #   - Never overwrite a hash that already exists in words (canonical entries win).
    #   - If two canonicals collide on the same variant, keep the lower (better) rank.
    alt_map: dict[str, list[int]] = {}
    if lang == "hi-en":
        alias_map = load_alias_map()
        # Build reverse map: canonical → [rank, qsim] from words_map
        canonical_to_rv: dict[str, list[int]] = {}
        for i, word in enumerate(vocab):
            canonical_to_rv[word] = [int(ranks[i]), quantize(float(sims[i]))]

        # Gather variants per canonical word
        for _i, word in enumerate(vocab):
            rv = canonical_to_rv[word]

            # Variant 1: normalize(word) if it differs from word
            norm = normalize(word)
            # Use a set to deduplicate: the normalize path and alias path may both
            # produce the same variant string (e.g. alias "barish"→"baarish" and
            # normalize("baarish")="barish" are the same variant).
            candidate_set: set[str] = set()
            if norm != word:
                candidate_set.add(norm)

            # Variant 2+: all aliases from the alias file whose canonical resolves to this word
            for alias_norm, alias_canonical in alias_map.items():
                if alias_canonical == word:
                    candidate_set.add(alias_norm)
            candidates = list(candidate_set)

            for variant in candidates:
                variant_hash = _word_hash(variant, salt)
                if variant_hash in seen_hashes:
                    # Canonical entry already exists at this hash — canonical wins
                    continue
                if variant_hash in alt_map:
                    # Another canonical already claimed this variant hash — keep lower rank
                    existing_rank = alt_map[variant_hash][0]
                    if rv[0] < existing_rank:
                        print(
                            f"[alt] collision on variant={variant!r} hash={variant_hash!r}: "
                            f"replacing rank {existing_rank} with rank {rv[0]} (word={word!r})"
                        )
                        alt_map[variant_hash] = rv
                    else:
                        print(
                            f"[alt] collision on variant={variant!r} hash={variant_hash!r}: "
                            f"keeping rank {existing_rank} over rank {rv[0]} (word={word!r})"
                        )
                else:
                    alt_map[variant_hash] = rv

    # Hints: plaintext words at specified ranks (never rank 1)
    n = len(vocab)
    hints: list[list] = []
    # Build rank → word mapping for hints
    rank_to_word: dict[int, str] = {}
    for i, word in enumerate(vocab):
        rank_to_word[int(ranks[i])] = word

    for target_rank in HINT_RANKS:
        actual_rank = min(target_rank, n)
        if actual_rank == 1:
            # Never expose the secret in hints
            actual_rank = 2
        # Walk outward from target rank to find a candidate that is not a
        # morphological variant of the secret (e.g. skip "oceans" when secret is "ocean").
        word_at_rank: str | None = None
        search_rank = actual_rank
        while search_rank <= n:
            candidate = rank_to_word.get(search_rank)
            if candidate is not None and not _is_morphological_variant(candidate, secret_lower):
                word_at_rank = candidate
                actual_rank = search_rank
                break
            search_rank += 1
        if word_at_rank is not None:
            hints.append([actual_rank, word_at_rank])

    # Obfuscated secret reveal field
    s_field = _obfuscate_secret(secret_lower, salt)

    # Generate rival paths (three tiers) and par guess count.
    # Paths contain only rank+band integers — no word strings.
    rival_data, par_guesses = generate_rival_data(n, secret_lower, key_str)

    result: dict = {
        "v": PAYLOAD_VERSION,
        "lang": lang,
        "date": key_str,
        "model": MODELS[lang],
        "n": n,
        "salt": salt,
        "words": words_map,
        "hints": hints,
        "parGuesses": par_guesses,
        "maxGuesses": par_guesses + 6,
        "clue": clue,
        "rival": rival_data,
        "s": s_field,
    }
    if alt_map:
        result["alt"] = alt_map
    return result


def build_payload(
    vocab: list[str],
    matrix: NDArray[np.float32],
    secret: str,
    lang: str,
    puzzle_date: date,
    clue: str = "",
) -> dict:
    """
    Build the full payload dict for one day's puzzle.

    Parameters
    ----------
    vocab:
        Ordered word list; matrix[i] is the embedding for vocab[i].
    matrix:
        L2-normalised embedding matrix, shape (len(vocab), D).
    secret:
        The secret word for this puzzle. Must be in vocab.
    lang:
        Language key ("en" or "hi-en").
    puzzle_date:
        Date of the puzzle (determines salt).

    Returns
    -------
    dict
        Payload ready for json.dumps + gzip.
    """
    salt = derive_salt(puzzle_date, lang)
    return _build_payload_core(vocab, matrix, secret, lang, salt, puzzle_date.isoformat(), clue)


def build_pack_payload(
    vocab: list[str],
    matrix: NDArray[np.float32],
    secret: str,
    lang: str,
    key: str,
    pack_id: str,
    idx: int,
    clue: str = "",
) -> dict:
    """
    Build the full payload dict for one themed-pack puzzle.

    Identical schema to build_payload's daily output, plus two extra fields:
    "pack" (the pack id) and "idx" (1-based puzzle index within the pack).
    The opaque `key` (e.g. "bollywood-001") is stored in the "date" field and
    used to seed the rival paths, exactly mirroring how daily puzzles use the
    ISO date string in both roles.

    Parameters
    ----------
    vocab, matrix, secret, lang, clue:
        Same meaning as build_payload.
    key:
        Opaque puzzle key, e.g. "{packId}-{NNN}".
    pack_id:
        The pack this puzzle belongs to.
    idx:
        1-based index of this puzzle within the pack.

    Returns
    -------
    dict
        Payload ready for json.dumps + gzip.
    """
    salt = derive_salt_for_key(key, lang)
    result = _build_payload_core(vocab, matrix, secret, lang, salt, key, clue)
    result["pack"] = pack_id
    result["idx"] = idx
    return result


def write_payload(
    payload: dict,
    out_dir: Path,
    lang: str,
    puzzle_date: date,
) -> Path:
    """
    Gzip-compress and write `payload` to out_dir/{lang}/{date}.json.gz.

    Returns the written file path.
    """
    lang_dir = out_dir / lang
    lang_dir.mkdir(parents=True, exist_ok=True)
    out_path = lang_dir / f"{puzzle_date.isoformat()}.json.gz"
    out_path.write_bytes(_gzip_json(payload))
    return out_path


def write_pack_payload(
    payload: dict,
    out_dir: Path,
    pack_id: str,
    lang: str,
    idx: int,
) -> Path:
    """
    Gzip-compress and write `payload` to out_dir/packs/{pack_id}/{lang}/{NNN}.json.gz.

    NNN is `idx` zero-padded to 3 digits (1-based). Returns the written file path.
    """
    lang_dir = out_dir / "packs" / pack_id / lang
    lang_dir.mkdir(parents=True, exist_ok=True)
    out_path = lang_dir / f"{idx:03d}.json.gz"
    out_path.write_bytes(_gzip_json(payload))
    return out_path


def _gzip_json(payload: dict) -> bytes:
    """
    Serialize `payload` as compact JSON and gzip-compress it deterministically.

    Uses mtime=0 so identical content produces identical bytes across runs —
    gzip.compress() embeds the current timestamp by default, which would
    otherwise break reproducibility.
    """
    json_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0) as gz:
        gz.write(json_bytes)
    return buf.getvalue()
