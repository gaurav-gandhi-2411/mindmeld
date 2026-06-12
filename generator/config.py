from __future__ import annotations

"""
Central configuration constants for the Mindmeld puzzle generator.

All paths, model names, size targets, and tuning knobs live here
so nothing is hard-coded across modules.
"""

import hashlib
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

GENERATOR_DIR = Path(__file__).parent
VOCAB_DIR = GENERATOR_DIR / "vocab"
CACHE_DIR = GENERATOR_DIR / ".model-cache"
EVALS_DIR = GENERATOR_DIR / "evals"
EVALS_FIXTURES_DIR = EVALS_DIR / "fixtures"
EVALS_KNOWN_FAILURES_DIR = EVALS_DIR / "fixtures_known_failures"

# ---------------------------------------------------------------------------
# Model names per language
# ---------------------------------------------------------------------------

# all-MiniLM-L6-v2 is the fastest SBERT model with strong English performance.
# 384-dim embeddings, ~22 MB on disk.
MODELS: dict[str, str] = {
    "en": "sentence-transformers/all-MiniLM-L6-v2",
    # paraphrase-multilingual covers 50+ languages including Hindi romanization;
    # this allows khushi ≈ happiness cross-lingually.
    "hi-en": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
}

# ---------------------------------------------------------------------------
# Vocab size targets
# ---------------------------------------------------------------------------

EN_TOP_N = 80_000  # wordfreq pool size before filtering
EN_MIN_FREQ_RANK = 80_000  # keep words ranked up to this in English
EN_MIN_LEN = 3
EN_MAX_LEN = 15
# Spec requires ~40–60k words in the final English vocab. We cap at 55k to stay
# within range while keeping common words. wordfreq returns words in frequency
# order (most common first), so truncating keeps the most useful words.
EN_VOCAB_MAX = 55_000

HIEN_EN_TOP_N = 10_000  # top English words included in hi-en vocab

# ---------------------------------------------------------------------------
# Payload size targets (gzipped bytes)
# ---------------------------------------------------------------------------

EN_MAX_GZIP_BYTES = 1_500_000  # 1.5 MB
HIEN_MAX_GZIP_BYTES = 400_000  # 400 KB

# ---------------------------------------------------------------------------
# Quantization
# ---------------------------------------------------------------------------

# qsim = round((cosine_sim + 1) * 32767.5)
# Maps [-1, 1] → [0, 65535] (uint16 range).
# This gives ~3e-5 resolution, comfortably below the 1e-4 round-trip budget.
QSIM_SCALE = 32767.5
QSIM_OFFSET = 1.0

# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------

START_DATE = date(2026, 6, 12)

# ---------------------------------------------------------------------------
# Anti-cheat salt derivation
# Salt is deterministic per (date, lang) but not guessable without knowing the scheme.
# ---------------------------------------------------------------------------

SALT_SUFFIX = "mindmeld-v1"


def derive_salt(puzzle_date: date, lang: str) -> str:
    """Return a 16-char hex salt for a given puzzle date and language."""
    raw = f"{puzzle_date.isoformat()}{lang}{SALT_SUFFIX}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]  # noqa: S324


# ---------------------------------------------------------------------------
# Obfuscation key for the secret reveal field "s"
# ---------------------------------------------------------------------------

OBFUSCATE_SUFFIX = "mindmeld-secret-v1"


def derive_obfuscate_key(salt: str, length: int) -> bytes:
    """
    Derive a repeating XOR key of `length` bytes from the salt.

    Uses SHA-1 of the salt as a 20-byte seed, tiled to required length.
    This is obfuscation (not encryption) — the goal is to prevent a regex
    scan of the JSON from revealing the secret word.
    """
    seed = hashlib.sha1(f"{salt}{OBFUSCATE_SUFFIX}".encode()).digest()  # noqa: S324
    key = (seed * (length // len(seed) + 1))[:length]
    return key


# ---------------------------------------------------------------------------
# Hint ranks (revealed plaintext words in the payload for the hint flow)
# ---------------------------------------------------------------------------

# These are the ranks at which hint words are revealed (rank 1 = secret).
# Rank 1 is intentionally excluded from hints to prevent direct spoiling.
HINT_RANKS = [1000, 750, 500, 300, 200, 100, 50, 25, 10, 5, 2]

# ---------------------------------------------------------------------------
# Payload version
# ---------------------------------------------------------------------------

PAYLOAD_VERSION = 1
MANIFEST_VERSION = 1
