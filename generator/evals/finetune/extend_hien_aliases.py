from __future__ import annotations

"""
Deterministic alias-file extension for the spelling-variance gap (docs/
model-excellence-final-report.md finding #2's "evidenced next attack" --
extend `vocab/hi-en-aliases.txt` directly instead of retraining, since
`bc4b25a`'s variant-augmented retraining regressed the main benchmark and
did not meaningfully improve robustness).

This module NEVER touches the model, its training data, or any *.jsonl
training file -- it only extends the LOOKUP-FOLDING table
(vocab/hi-en-aliases.txt) that normalize.py/payload.py already read.
Candidate mining reuses spelling_robustness.py's Aksharantar-grouping +
is_clean_variant noise filter verbatim (build_aksharantar_maps /
aksharantar_variants_for_secret) -- the SAME machinery
assemble_data.variant_source() uses for the (rejected) retraining attempt --
across the FULL ~544-word hinglish-sourced vocab, not just the 42 test
secrets or the train split. Unlike variant_source(), there is no held-out-
secret exclusion here: alias-folding is a deterministic lookup mechanism,
not a statistically-generalizing model, so covering held-out secrets' real
variants too is the whole point (broad real-world coverage), not a leakage
risk.

Quality gate (the single biggest risk named for this task): two genuinely
DIFFERENT words must never fold together. Every candidate is checked, in
order, against:
  1. vocab collision   -- normalize(variant) does NOT already equal a
     DIFFERENT canonical word's raw vocab spelling (the actual hash-
     collision surface: payload.py's words_map is keyed by the RAW vocab
     spelling, alt_map by the NORMALIZED variant string -- see this
     module's docstring in the code below for the full mechanism trace).
  2. existing-alias collision -- normalize(variant) does NOT already
     resolve (via the CURRENT, pre-extension vocab/hi-en-aliases.txt) to a
     DIFFERENT canonical.
  3. internal-batch consistency -- no two candidates in this run's NEW
     additions normalize to the same string for two different canonicals.
Candidates that already resolve correctly without any change (either a
literal duplicate of an existing alias, or a redundant case where
normalize(variant) already equals the candidate's OWN canonical -- i.e.
canonical_for() would already return the right answer even with zero
alias-file changes) are excluded too, but for a harmless reason, not a
risk reason -- reported in a separate bucket, never conflated with the
false-merge rejections.

KNOWN GAP, by design: this module's automated gate only knows about the
vocab list and the alias file -- it does NOT read clue/pack content, so it
cannot catch a mined variant that coincidentally collides with an unrelated
word in an authored clue (tests/test_clue_spoiler_gate.py's morphological-
variant check). That happened once during this module's own first real run
((pyaar, paayar) vs the bollywood pack's P01 clue) -- caught by running the
FULL test suite, not this module, and excluded manually with an inline
comment in vocab/hi-en-aliases.txt. Always run the full suite (not just
this module's own dry run) before treating a batch as safe to write.

Run (from generator/):
    uv run python -m evals.finetune.extend_hien_aliases              # dry run, report only
    uv run python -m evals.finetune.extend_hien_aliases --write       # also rewrite the alias file
"""

import json
from collections import defaultdict
from pathlib import Path

from evals.finetune.collision_scan import hinglish_sourced_words
from evals.finetune.spelling_robustness import (
    AKSHARANTAR_PATH,
    K_AKSHARANTAR_MAX_PER_SECRET,
    aksharantar_variants_for_secret,
    build_aksharantar_maps,
    parse_alias_file,
)
from normalize import load_alias_map, normalize
from vocab import load_hien_vocab

VOCAB_DIR = Path(__file__).parent.parent.parent / "vocab"
ALIASES_PATH = VOCAB_DIR / "hi-en-aliases.txt"
DATA_DIR = Path(__file__).parent / "data"
REPORT_PATH = DATA_DIR / "extend_hien_aliases_report.json"

_NEW_SECTION_HEADER = (
    "# --- Aksharantar-mined additions (spelling-variance fix, docs/"
    "model-excellence-final-report.md finding #2) ---\n"
    "# Mined via evals/finetune/extend_hien_aliases.py (build_aksharantar_maps +\n"
    "# aksharantar_variants_for_secret, is_clean_variant-filtered, full ~544-word\n"
    "# hinglish-sourced vocab, false-merge-gated -- see extend_hien_aliases_report.json\n"
    "# for the full accounting of what was excluded and why).\n"
)


def generate_candidates() -> list[tuple[str, str]]:
    """(canonical, variant) pairs across the FULL hinglish-sourced vocab --
    reuses spelling_robustness.py's Aksharantar-grouping + is_clean_variant
    machinery verbatim, capped at K_AKSHARANTAR_MAX_PER_SECRET variants per
    word (same cap the eval module and variant_source() use). No held-out
    exclusion: see module docstring for why that's correct here."""
    hi_words = sorted(hinglish_sourced_words())
    rom_to_deva, deva_to_rom = build_aksharantar_maps(AKSHARANTAR_PATH)
    candidates: list[tuple[str, str]] = []
    for word in hi_words:
        variants = aksharantar_variants_for_secret(
            word, rom_to_deva, deva_to_rom, max_variants=K_AKSHARANTAR_MAX_PER_SECRET
        )
        for variant in variants:
            candidates.append((word, variant))
    return candidates


def gate_candidates(
    candidates: list[tuple[str, str]],
    vocab_set: set[str],
    existing_alias_map: dict[str, str],
) -> dict:
    """Runs every candidate through the false-merge + redundancy gates
    described in the module docstring, in a fixed, deterministic order
    (candidates are sorted before processing so tie-breaking in the
    internal-batch-conflict check never depends on generation order).
    Returns a full accounting: survivors ready to add, plus every
    exclusion bucket with its reason.
    """
    ordered = sorted(set(candidates))

    vocab_collisions: list[dict] = []
    existing_alias_collisions: list[dict] = []
    duplicate_of_existing: list[dict] = []
    redundant_self_resolving: list[dict] = []
    stage1_survivors: list[dict] = []  # {"word", "variant", "norm_variant"}

    for word, variant in ordered:
        norm_variant = normalize(variant)

        if norm_variant in existing_alias_map and existing_alias_map[norm_variant] == word:
            duplicate_of_existing.append(
                {"word": word, "variant": variant, "norm_variant": norm_variant}
            )
            continue

        if norm_variant == word:
            redundant_self_resolving.append(
                {"word": word, "variant": variant, "norm_variant": norm_variant}
            )
            continue

        if norm_variant in vocab_set and norm_variant != word:
            vocab_collisions.append(
                {
                    "word": word,
                    "variant": variant,
                    "norm_variant": norm_variant,
                    "collides_with_vocab_word": norm_variant,
                }
            )
            continue

        if norm_variant in existing_alias_map and existing_alias_map[norm_variant] != word:
            existing_alias_collisions.append(
                {
                    "word": word,
                    "variant": variant,
                    "norm_variant": norm_variant,
                    "existing_canonical": existing_alias_map[norm_variant],
                }
            )
            continue

        stage1_survivors.append({"word": word, "variant": variant, "norm_variant": norm_variant})

    # Internal-batch consistency: no norm_variant may map to >1 distinct
    # canonical among stage1_survivors.
    by_norm_variant: dict[str, set[str]] = defaultdict(set)
    for rec in stage1_survivors:
        by_norm_variant[rec["norm_variant"]].add(rec["word"])

    conflicting_norm_variants = {nv for nv, words in by_norm_variant.items() if len(words) > 1}
    internal_batch_conflicts = [
        rec for rec in stage1_survivors if rec["norm_variant"] in conflicting_norm_variants
    ]
    survivors_after_conflict = [
        rec for rec in stage1_survivors if rec["norm_variant"] not in conflicting_norm_variants
    ]

    # Redundant-duplicate normalized form within the new batch itself (two
    # raw spellings for the SAME canonical that normalize identically) --
    # keep the first (sorted, so deterministic), report the rest.
    seen_norm_per_word: dict[str, set[str]] = defaultdict(set)
    final_survivors: list[dict] = []
    redundant_duplicate_within_batch: list[dict] = []
    for rec in sorted(survivors_after_conflict, key=lambda r: (r["word"], r["variant"])):
        key = rec["norm_variant"]
        if key in seen_norm_per_word[rec["word"]]:
            redundant_duplicate_within_batch.append(rec)
            continue
        seen_norm_per_word[rec["word"]].add(key)
        final_survivors.append(rec)

    return {
        "n_candidates_generated": len(ordered),
        "final_survivors": final_survivors,
        "n_final_added": len(final_survivors),
        "excluded": {
            "vocab_collisions": vocab_collisions,
            "existing_alias_collisions": existing_alias_collisions,
            "internal_batch_conflicts": internal_batch_conflicts,
        },
        "excluded_counts": {
            "vocab_collisions": len(vocab_collisions),
            "existing_alias_collisions": len(existing_alias_collisions),
            "internal_batch_conflicts": len(internal_batch_conflicts),
        },
        "harmless_noop_excluded": {
            "duplicate_of_existing_alias": duplicate_of_existing,
            "redundant_self_resolving": redundant_self_resolving,
            "redundant_duplicate_normalized_form_within_new_batch": (
                redundant_duplicate_within_batch
            ),
        },
        "harmless_noop_counts": {
            "duplicate_of_existing_alias": len(duplicate_of_existing),
            "redundant_self_resolving": len(redundant_self_resolving),
            "redundant_duplicate_normalized_form_within_new_batch": len(
                redundant_duplicate_within_batch
            ),
        },
    }


def render_new_file_text(current_text: str, survivors: list[dict]) -> str:
    """Merge `survivors` into the existing alias file's exact format
    (`canonical: alias1, alias2, ...`), preserving all 29 existing entries
    and their comments byte-for-byte: aliases for a canonical that ALREADY
    has a line get appended to that line (in place, in the ordered position
    of that line); canonicals with no existing line get a new line appended
    under a new dated section header at the end of the file.
    """
    existing_grouped = parse_alias_file(ALIASES_PATH)  # {canonical: [alias, ...]} raw form

    by_word: dict[str, list[str]] = defaultdict(list)
    for rec in sorted(survivors, key=lambda r: (r["word"], r["variant"])):
        by_word[rec["word"]].append(rec["variant"])

    lines = current_text.splitlines(keepends=True)
    out_lines: list[str] = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if stripped and not stripped.startswith("#") and ":" in stripped:
            canonical_raw, aliases_raw = stripped.split(":", 1)
            canonical = canonical_raw.strip().lower()
            if canonical in existing_grouped and canonical in by_word:
                new_aliases = ", ".join(by_word.pop(canonical))
                trailing_comment = ""
                if "#" in aliases_raw:
                    aliases_part, trailing_comment = aliases_raw.split("#", 1)
                    trailing_comment = "  #" + trailing_comment
                else:
                    aliases_part = aliases_raw
                aliases_part = aliases_part.rstrip()
                newline = "\n" if raw_line.endswith("\n") else ""
                out_lines.append(
                    f"{canonical_raw}:{aliases_part}, {new_aliases}{trailing_comment}{newline}"
                )
                continue
        out_lines.append(raw_line)

    remaining_canonicals = sorted(by_word)
    if remaining_canonicals:
        # Trim any trailing blank line(s) already at EOF before adding exactly
        # one blank-line separator -- matches the file's existing one-blank-
        # line-between-sections convention (see e.g. line 55-56 before the
        # "Phase 6c" section header).
        while out_lines and not out_lines[-1].strip():
            out_lines.pop()
        out_lines.append("\n")
        out_lines.append(_NEW_SECTION_HEADER)
        out_lines.append("\n")
        for canonical in remaining_canonicals:
            aliases = ", ".join(by_word[canonical])
            out_lines.append(f"{canonical}: {aliases}\n")

    return "".join(out_lines)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Also rewrite vocab/hi-en-aliases.txt with the gated survivors merged in "
        "(default: dry run, report only).",
    )
    args = parser.parse_args()

    candidates = generate_candidates()
    vocab_set = set(load_hien_vocab())
    existing_alias_map = load_alias_map()  # {normalized_alias: canonical}, CURRENT file

    result = gate_candidates(candidates, vocab_set, existing_alias_map)

    print(f"candidates generated: {result['n_candidates_generated']}")
    print(f"final survivors (to add): {result['n_final_added']}")
    print(f"excluded (false-merge risk): {result['excluded_counts']}")
    print(f"excluded (harmless no-op): {result['harmless_noop_counts']}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {REPORT_PATH}")

    if args.write:
        current_text = ALIASES_PATH.read_text(encoding="utf-8")
        new_text = render_new_file_text(current_text, result["final_survivors"])
        ALIASES_PATH.write_text(new_text, encoding="utf-8")
        print(f"wrote {ALIASES_PATH} ({result['n_final_added']} new aliases merged in)")


if __name__ == "__main__":
    main()
