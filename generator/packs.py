from __future__ import annotations

"""
Themed pack manifest + content loading for Mindmeld Phase 6c.

Pack content lives under packs/{packId}/:
  secrets_{lang}.txt  — same format as vocab/secrets_{lang}.txt
  clues_{lang}.txt    — same format as vocab/clues-{lang}.txt

(# comments and blank lines skipped in both; line N in secrets pairs with
line N in clues, same convention as the daily schedule/clue files.)

packs.json describes each pack's metadata (title, tagline, branding, status).
Content files may be comment-only (0 secrets) for packs not yet authored —
that is a valid state, not an error; it simply yields a 0-count build.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from config import GENERATOR_DIR
from profanity import load_en_profanity, load_hi_profanity

PACKS_DIR = GENERATOR_DIR / "packs"
PACKS_MANIFEST_PATH = PACKS_DIR / "packs.json"

_REQUIRED_FIELDS = (
    "id",
    "title",
    "tagline",
    "free",
    "status",
    "accent",
    "accentDark",
    "icon",
    "langs",
)
_VALID_STATUSES = ("live", "coming_soon")


@dataclass(frozen=True)
class PackMeta:
    """Metadata for one themed pack, as declared in packs.json."""

    id: str
    title: dict[str, str]
    tagline: dict[str, str]
    free: bool
    status: str
    accent: str
    accent_dark: str
    icon: str
    langs: list[str]
    # Directory containing this pack's content files (secrets_{lang}.txt etc).
    # Defaults to the pack's own subdirectory under whichever manifest it was
    # loaded from (see load_packs_meta) — this makes a pack loaded from a
    # synthetic tmp manifest resolve its content under that same tmp tree,
    # with no monkeypatching required in tests.
    base_dir: Path = PACKS_DIR

    @property
    def dir(self) -> Path:
        """Return the content directory for this pack (base_dir/{id}/)."""
        return self.base_dir / self.id


def _pack_meta_from_dict(entry: dict, index: int, base_dir: Path) -> PackMeta:
    """
    Validate one packs.json entry and return a PackMeta.

    Raises ValueError with a clear message identifying the offending entry
    on any missing or malformed field.
    """
    missing = [f for f in _REQUIRED_FIELDS if f not in entry]
    if missing:
        label = entry.get("id", f"entry #{index}")
        raise ValueError(f"packs.json[{label}]: missing required field(s): {missing}")

    pack_id = entry["id"]
    if not isinstance(pack_id, str) or not pack_id:
        raise ValueError(f"packs.json entry #{index}: 'id' must be a non-empty string")

    status = entry["status"]
    if status not in _VALID_STATUSES:
        raise ValueError(
            f"packs.json[{pack_id}]: invalid status {status!r}; must be one of {_VALID_STATUSES}"
        )

    langs = entry["langs"]
    if not isinstance(langs, list) or not langs:
        raise ValueError(f"packs.json[{pack_id}]: 'langs' must be a non-empty list")

    for field_name in ("title", "tagline"):
        value = entry[field_name]
        if not isinstance(value, dict):
            raise ValueError(f"packs.json[{pack_id}]: '{field_name}' must be an object")
        missing_langs = [lang for lang in langs if lang not in value]
        if missing_langs:
            raise ValueError(
                f"packs.json[{pack_id}]: '{field_name}' missing lang key(s): {missing_langs}"
            )

    if not isinstance(entry["free"], bool):
        raise ValueError(f"packs.json[{pack_id}]: 'free' must be a boolean")

    return PackMeta(
        id=pack_id,
        title=entry["title"],
        tagline=entry["tagline"],
        free=entry["free"],
        status=status,
        accent=entry["accent"],
        accent_dark=entry["accentDark"],
        icon=entry["icon"],
        langs=list(langs),
        base_dir=base_dir,
    )


def load_packs_meta(path: Path | None = None) -> list[PackMeta]:
    """
    Load and validate packs.json, returning a list of PackMeta.

    Each pack's content directory is resolved relative to `path`'s parent
    directory (i.e. packs/{id}/ next to packs/packs.json for the real
    manifest, or {tmp}/{id}/ next to a synthetic {tmp}/packs.json in tests).

    Raises ValueError on any malformed entry (missing/invalid field).
    """
    fp = path or PACKS_MANIFEST_PATH
    raw = json.loads(fp.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{fp}: top-level JSON must be a list of pack entries")
    base_dir = fp.parent
    return [_pack_meta_from_dict(entry, i, base_dir) for i, entry in enumerate(raw)]


def _load_lines(path: Path, lowercase: bool) -> list[str]:
    """
    Parse a pack content file: skip comments/blanks, optionally lowercase.

    Mirrors the parsing convention shared by schedule.load_schedule and
    clues.load_clues (# comments, blank lines skipped). Pack content lives in
    a separate directory tree, so this is duplicated inline rather than
    imported — it is a five-line rule, not worth coupling the daily code
    path to a new shared module for.
    """
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            lines.append(stripped.lower() if lowercase else stripped)
    return lines


def load_pack_secrets(pack: PackMeta, lang: str) -> list[str]:
    """Load the secret-word list for one pack/lang from secrets_{lang}.txt."""
    fp = pack.dir / f"secrets_{lang}.txt"
    return _load_lines(fp, lowercase=True)


def load_pack_clues(pack: PackMeta, lang: str) -> list[str]:
    """Load the clue list for one pack/lang from clues_{lang}.txt."""
    fp = pack.dir / f"clues_{lang}.txt"
    return _load_lines(fp, lowercase=False)


def validate_pack_content(
    pack: PackMeta,
    vocab_by_lang: dict[str, list[str]],
) -> dict[str, tuple[list[str], list[str]]]:
    """
    Load and validate a pack's secrets + clues across its available langs.

    Only langs present in both `pack.langs` and `vocab_by_lang` are processed
    (this lets callers validate a subset of languages without needing every
    lang's vocab loaded).

    Validation (raises ValueError with a clear message on failure):
      - len(secrets) == len(clues) per lang
      - every secret is present in that lang's vocab
      - no secret is in the profanity blocklist
      - secret count matches across all processed langs

    Returns {lang: (secrets, clues)}. A pack whose content files are
    comment-only (0 secrets in every lang) is valid — it simply produces
    a result with empty lists, which build_packs.py turns into a count-0
    build.
    """
    profanity_en = load_en_profanity()
    profanity_hi = load_hi_profanity()

    langs_to_check = [lang for lang in pack.langs if lang in vocab_by_lang]

    result: dict[str, tuple[list[str], list[str]]] = {}
    counts: dict[str, int] = {}
    errors: list[str] = []

    for lang in langs_to_check:
        secrets = load_pack_secrets(pack, lang)
        clues = load_pack_clues(pack, lang)
        counts[lang] = len(secrets)

        if len(secrets) != len(clues):
            errors.append(
                f"[{pack.id}/{lang}] secret/clue count mismatch: "
                f"{len(secrets)} secrets vs {len(clues)} clues"
            )

        vocab_set = set(vocab_by_lang[lang])
        profanity = profanity_en | profanity_hi if lang == "hi-en" else profanity_en

        for i, word in enumerate(secrets):
            if word not in vocab_set:
                errors.append(f"[{pack.id}/{lang}] line {i + 1}: secret {word!r} not in vocab")
            if word in profanity:
                errors.append(
                    f"[{pack.id}/{lang}] line {i + 1}: secret {word!r} is in profanity blocklist"
                )

        result[lang] = (secrets, clues)

    if len(set(counts.values())) > 1:
        errors.append(f"[{pack.id}] secret count mismatch across langs: {counts}")

    if errors:
        raise ValueError(f"Pack validation failed for {pack.id!r}:\n" + "\n".join(errors))

    return result
