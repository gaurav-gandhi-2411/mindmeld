from __future__ import annotations

"""
Mindmeld themed-pack builder CLI.

Usage:
    python build_packs.py --packs all --langs en,hi-en [--out ../payloads] [--strict-sizes]
    python build_packs.py --packs bollywood,cricket

For each selected pack:
  - status != "live": no content is loaded or validated; count is 0 in the manifest
    (coming-soon packs are advertised in the store but not yet playable).
  - status == "live": secrets + clues are loaded and validated (packs.validate_pack_content
    — the same checks schedule.validate_schedule applies to the daily schedule), the clue
    is spoiler-gated against its own secret/alias/morphological variants, and one payload
    is built + written per (lang, index). A live pack with comment-only content files
    (0 secrets) builds gracefully to count 0 — this is the current state of "bollywood"
    pending content authorship.

Output:
    {out}/packs/{packId}/{lang}/{NNN}.json.gz   (NNN = 1-based, zero-padded to 3 digits)
    {out}/packs/manifest.json                   ({"v": 1, "packs": [...]})

Payload schema matches the daily v3 payload (see payload.build_pack_payload) plus
"pack" and "idx" fields. The "date" field carries the opaque key "{packId}-{NNN}",
which also seeds the rival paths (see config.derive_salt_for_key).

Note on --packs subsets: packs/manifest.json is written fresh each run, scoped to
whatever --packs selected (default "all"). Run with --packs all for the production
manifest that covers every pack; a subset run is for targeted local rebuilds/testing
and intentionally does not merge with a previous manifest.
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Script-mode path setup: ensures local modules are importable when run as
# `python build_packs.py` from any working directory (not just from generator/).
# This must run before the local imports below.
sys.path.insert(0, str(Path(__file__).parent))

import numpy as np  # noqa: E402
from numpy.typing import NDArray  # noqa: E402

from config import EN_MAX_GZIP_BYTES, HIEN_MAX_GZIP_BYTES  # noqa: E402
from embeddings import embed_vocab  # noqa: E402
from normalize import load_alias_map  # noqa: E402
from packs import (  # noqa: E402
    PACKS_MANIFEST_PATH,
    PackMeta,
    load_packs_meta,
    validate_pack_content,
)
from payload import _is_morphological_variant, build_pack_payload, write_pack_payload  # noqa: E402
from vocab import apply_devanagari_patch, load_en_vocab, load_hien_vocab  # noqa: E402

LANG_LOADERS = {
    "en": load_en_vocab,
    "hi-en": load_hien_vocab,
}

SIZE_TARGETS = {
    "en": EN_MAX_GZIP_BYTES,
    "hi-en": HIEN_MAX_GZIP_BYTES,
}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mindmeld themed-pack builder")
    parser.add_argument(
        "--packs",
        type=str,
        default="all",
        help="Comma-separated pack ids to build, or 'all' (default: all)",
    )
    parser.add_argument(
        "--langs",
        type=str,
        default="en,hi-en",
        help="Comma-separated list of languages to build (default: en,hi-en)",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="../payloads",
        help="Output directory for pack payloads and manifest",
    )
    parser.add_argument(
        "--strict-sizes",
        action="store_true",
        default=False,
        help="Fail the build if any payload exceeds its size target",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Inline spoiler gate — shared predicate, also reused by
# tests/test_clue_spoiler_gate.py (parametrized over daily + pack content).
# ---------------------------------------------------------------------------


def extract_clue_tokens(text: str) -> list[str]:
    """Return lowercase alpha tokens longer than 2 characters from text."""
    return [t for t in re.findall(r"[a-z]+", text.lower()) if len(t) > 2]


def aliases_for_secret(secret: str, lang: str) -> list[str]:
    """Return all known aliases for `secret` in `lang` (hi-en only; [] for en)."""
    if lang != "hi-en":
        return []
    alias_map = load_alias_map()
    return [alias for alias, canonical in alias_map.items() if canonical == secret]


def clue_leak_reason(clue: str, secret: str, aliases: list[str]) -> str | None:
    """
    Return a description of why `clue` leaks `secret`, or None if it's safe.

    Checks (in order):
    1. Secret (or alias) appears as a substring anywhere in the lowercased clue.
    2. Any token in the clue is a morphological variant of the secret or alias
       (reuses payload._is_morphological_variant — same logic that filters hints).
    """
    clue_lower = clue.lower()
    targets = [secret, *aliases]

    for target in targets:
        if target in clue_lower:
            return f"direct substring '{target}'"
        for token in extract_clue_tokens(clue_lower):
            if _is_morphological_variant(token, target):
                return f"token '{token}' is morphological variant of '{target}'"

    return None


# ---------------------------------------------------------------------------
# Build logic
# ---------------------------------------------------------------------------


def _resolve_packs(packs_arg: str, all_packs: list[PackMeta]) -> list[PackMeta]:
    """Resolve the --packs argument ('all' or a comma-separated id list) to PackMeta list."""
    if packs_arg.strip().lower() == "all":
        return all_packs

    requested = [p.strip() for p in packs_arg.split(",") if p.strip()]
    by_id = {p.id: p for p in all_packs}
    unknown = [pid for pid in requested if pid not in by_id]
    if unknown:
        raise ValueError(f"Unknown pack id(s): {unknown}. Known: {sorted(by_id)}")
    return [by_id[pid] for pid in requested]


def build_one_pack(
    pack: PackMeta,
    langs: list[str],
    vocab_by_lang: dict[str, list[str]],
    matrix_by_lang: dict[str, NDArray[np.float32]],
    out_dir: Path,
    strict_sizes: bool,
) -> tuple[int, bool]:
    """
    Build all puzzles for one pack across the requested langs.

    Returns (count, any_size_violation). count is the number of puzzles built
    per lang (identical across langs by construction — validate_pack_content
    enforces this invariant). count is 0 for non-live packs or packs whose
    content files are empty (comment-only).
    """
    if pack.status != "live":
        print(f"[{pack.id}] status={pack.status!r} — skipping build (count 0)")
        return 0, False

    vocab_subset = {lang: vocab_by_lang[lang] for lang in langs if lang in vocab_by_lang}
    content = validate_pack_content(pack, vocab_subset)

    langs_with_content = [lang for lang in pack.langs if lang in content]
    if not langs_with_content:
        print(f"[{pack.id}] no lang overlap with requested --langs — count 0")
        return 0, False

    count = len(content[langs_with_content[0]][0])
    if count == 0:
        print(f"[{pack.id}] WARNING: content files are empty — building count 0")
        return 0, False

    any_size_violation = False
    for lang in langs_with_content:
        secrets, clues = content[lang]
        matrix = matrix_by_lang[lang]
        vocab = vocab_by_lang[lang]

        for i, (secret, clue) in enumerate(zip(secrets, clues, strict=True)):
            idx = i + 1
            key = f"{pack.id}-{idx:03d}"

            aliases = aliases_for_secret(secret, lang)
            leak = clue_leak_reason(clue, secret, aliases)
            if leak is not None:
                raise ValueError(
                    f"[{pack.id}/{lang}] clue for {key!r} leaks secret {secret!r}: {leak}\n"
                    f"Clue: {clue!r}"
                )

            payload = build_pack_payload(vocab, matrix, secret, lang, key, pack.id, idx, clue=clue)
            out_path = write_pack_payload(payload, out_dir, pack.id, lang, idx)
            file_bytes = out_path.stat().st_size

            target = SIZE_TARGETS[lang]
            if file_bytes > target:
                any_size_violation = True
                status = "FAIL" if strict_sizes else "WARN: exceeds target"
                print(
                    f"  [{pack.id}/{lang}/{idx:03d}] {file_bytes:,}B - {status} "
                    f"(target {target:,}B)"
                )
            else:
                print(f"  [{pack.id}/{lang}/{idx:03d}] {file_bytes:,}B - OK")

    return count, any_size_violation


def _write_packs_manifest(
    all_packs: list[PackMeta],
    processed: dict[str, int],
    out_dir: Path,
    manifest_source: Path = PACKS_MANIFEST_PATH,
) -> Path:
    """
    Write packs/manifest.json: each processed pack's packs.json entry + a "count" field.

    Only packs present in `processed` are included, in packs.json order — a
    partial build (--packs subset) produces a manifest scoped to that subset.

    `manifest_source` is the raw packs.json to pull each entry's fields from;
    it defaults to the real generator/packs/packs.json but can be overridden
    (e.g. in tests, to match a synthetic manifest passed to load_packs_meta).
    """
    raw_entries: list[dict] = json.loads(manifest_source.read_text(encoding="utf-8"))
    by_id = {e["id"]: e for e in raw_entries}

    packs_section: list[dict] = []
    for pack in all_packs:
        if pack.id not in processed:
            continue
        entry = dict(by_id[pack.id])
        entry["count"] = processed[pack.id]
        packs_section.append(entry)

    manifest = {"v": 1, "packs": packs_section}
    manifest_dir = out_dir / "packs"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def main(argv: list[str] | None = None) -> None:
    """Main entry point for the themed-pack builder CLI."""
    args = _parse_args(argv)

    langs = [lang.strip() for lang in args.langs.split(",") if lang.strip()]
    out_dir = Path(args.out).resolve()

    for lang in langs:
        if lang not in LANG_LOADERS:
            print(f"ERROR: unknown lang {lang!r}. Known langs: {list(LANG_LOADERS)}")
            sys.exit(1)

    all_packs = load_packs_meta()
    try:
        selected = _resolve_packs(args.packs, all_packs)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    print(f"Building pack(s): {[p.id for p in selected]} for langs: {langs}")
    print(f"Output directory: {out_dir}")

    # Only load vocab/embeddings for langs actually needed by a live, selected pack —
    # avoids a model load entirely when building only coming-soon packs.
    needed_langs = sorted(
        {lang for pack in selected if pack.status == "live" for lang in pack.langs if lang in langs}
    )

    vocab_by_lang: dict[str, list[str]] = {}
    matrix_by_lang: dict[str, NDArray[np.float32]] = {}
    for lang in needed_langs:
        print(f"[{lang}] Loading vocab...")
        vocab_by_lang[lang] = LANG_LOADERS[lang]()
        print(f"[{lang}] Embedding vocab (may load model on first run)...")
        # L2 lever (spec-residual-attack.md): see build.py's identical comment.
        embed_input = (
            apply_devanagari_patch(vocab_by_lang[lang]) if lang == "hi-en" else vocab_by_lang[lang]
        )
        matrix_by_lang[lang] = embed_vocab(embed_input, lang, show_progress=True)

    processed: dict[str, int] = {}
    any_size_violation = False

    for pack in selected:
        try:
            count, violation = build_one_pack(
                pack, langs, vocab_by_lang, matrix_by_lang, out_dir, args.strict_sizes
            )
        except ValueError as exc:
            print(f"ERROR: {exc}")
            sys.exit(1)
        processed[pack.id] = count
        any_size_violation = any_size_violation or violation

    manifest_path = _write_packs_manifest(all_packs, processed, out_dir)
    print(f"\nPacks manifest written: {manifest_path}")

    if any_size_violation and args.strict_sizes:
        print("\nBuild FAILED: size targets exceeded (--strict-sizes mode).")
        sys.exit(1)

    print("\nPack build complete.")


if __name__ == "__main__":
    main()
