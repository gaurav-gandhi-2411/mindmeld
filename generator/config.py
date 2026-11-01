from __future__ import annotations

"""
Central configuration constants for the Mindmeld puzzle generator.

All paths, model names, size targets, and tuning knobs live here
so nothing is hard-coded across modules.
"""

import hashlib
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

GENERATOR_DIR = Path(__file__).parent
REPO_ROOT = GENERATOR_DIR.parent
VOCAB_DIR = GENERATOR_DIR / "vocab"
CACHE_DIR = GENERATOR_DIR / ".model-cache"
EVALS_DIR = GENERATOR_DIR / "evals"
EVALS_FIXTURES_DIR = EVALS_DIR / "fixtures"
EVALS_KNOWN_FAILURES_DIR = EVALS_DIR / "fixtures_known_failures"

# Loads the repo-root .env (HF_TOKEN, etc.) into os.environ for local runs.
# No-op if the file doesn't exist (e.g. CI, which sets env vars/secrets
# directly) -- production Cloud Run/Vercel never import this module at all,
# since the fine-tuned hi-en model is only ever loaded at generator/build
# time (see embeddings.embed_vocab), never in the deployed app.
load_dotenv(REPO_ROOT / ".env")

# ---------------------------------------------------------------------------
# Model names per language
# ---------------------------------------------------------------------------

# all-MiniLM-L6-v2 is the fastest SBERT model with strong English performance.
# 384-dim embeddings, ~22 MB on disk.
MODELS: dict[str, str] = {
    "en": "sentence-transformers/all-MiniLM-L6-v2",
    # paraphrase-multilingual-MiniLM-L12-v2 was tried first but scored ~random
    # on hi-en (Spearman -0.003, cross-language pass 5%): it was trained on
    # Hindi in Devanagari script, not Latin-script romanized Hindi, so it embeds
    # romanized tokens by surface form rather than meaning (see
    # spec-hinglish-fix.md / evals/reports/baseline_report.md for the bake-off).
    # l3cube-pune/indic-sentence-bert-nli (CC-BY-4.0) won a 9-candidate
    # bake-off (Spearman 0.639, cross-language pass 54.2%) and shipped as-is
    # for a full season. Two data-only fine-tune retries (v1/v2) both
    # regressed held-out performance -- a diagnostic sweep then found the
    # TRAINING METHOD (unconstrained full-parameter fine-tuning) was the
    # fault, not data volume: LoRA r=8 + mined hard negatives fixed it.
    # gauravgandhi2411/hinglish-relatedness-sbert (CC-BY-4.0, public,
    # portfolio model card) is that fine-tune -- held-out dim1 Spearman
    # 0.4350 -> 0.7044, dim2 cross-language pass-rate 0.375 -> 0.8125, both
    # paired-CI-significant, zero net regression (spec-hinglish-diagnostic-
    # sweep.md / ship_decision_report_v3.md). No auth needed to load (public).
    "hi-en": "gauravgandhi2411/hinglish-relatedness-sbert",
}

# Pinned HF commit SHAs for the production models above. Without a pin, a
# silent upstream re-upload would change embeddings (and therefore every
# rank) while the cache key stayed the same. The revision is part of
# embeddings._cache_key, so bumping a pin invalidates cached matrices.
MODEL_REVISIONS: dict[str, str] = {
    # HF main as of 2026-11-01 (last modified 2026-06-01).
    "en": "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
    # Last commit 2026-07-23 was card-only; weights unchanged since 138f4f5dde31
    # (2026-07-18).
    "hi-en": "4b06ad914005cf93ad6a99878566c00a5a0af47b",
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


def derive_salt_for_key(key: str, lang: str) -> str:
    """
    Return a 16-char hex salt for an opaque key (e.g. a pack puzzle key).

    Same recipe as derive_salt, but takes an arbitrary opaque string in place
    of a calendar date — used for themed-pack puzzles, which are keyed by
    "{packId}-{NNN}" rather than an ISO date. derive_salt itself is left
    untouched so daily payloads remain byte-identical.
    """
    raw = f"{key}{lang}{SALT_SUFFIX}"
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
# Onboarding puzzle (first-session hook, spec-first-session-hook.md)
# ---------------------------------------------------------------------------

# Generous, fixed budget so a first-session win is near-guaranteed (spec:
# "near-impossible to lose"). Deliberately NOT par-derived like daily/pack
# budgets (rival.max_guesses_for_par) — this puzzle's job is to teach the
# mechanic, not to be a fair daily challenge, so it gets a flat generous cap
# instead of scaling with the rival-path par.
ONBOARDING_MAX_GUESSES = 20

# ---------------------------------------------------------------------------
# Payload version
# ---------------------------------------------------------------------------

PAYLOAD_VERSION = 3
MANIFEST_VERSION = 1
