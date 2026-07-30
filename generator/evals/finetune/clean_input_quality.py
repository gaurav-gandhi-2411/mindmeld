from __future__ import annotations

"""
Input-quality quantification + cleaning (spec-hinglish-diagnostic-sweep.md
Step 1d). The 34.6% dict/LLM romanization calibration-agreement figure
(PLAN.md, corpus-PMI mining session) means a large share of `corpus_pmi`
source pairs carry an LLM-guessed or dict-guessed romanized surface form
that may not match how that word is actually spelled/tokenized in the real
hi-en production vocab -- "bad surface forms teach bad embeddings" (spec).

Quantification (see quantify()): of the 325 quality-filtered corpus_pmi
graded pairs, only 185 (57%) have BOTH anchor and neighbor already present,
verbatim, in the real production hi-en vocabulary (vocab/secrets_hi-en.txt +
vocab/hinglish.txt derived vocab, via vocab.load_hien_vocab()) -- the
remaining 140 (43%) reference at least one romanized form that does not
correspond to any real in-game word at all: not "mis-transliterated" in a
way that collides with a different real word (which would be actively
harmful), but a token the game will never query, contributing pure noise to
the shared encoder's gradient updates for no compensating signal.

A stricter dict-only filter (both anchor+neighbor sourced from the
Aksharantar dict, not the LLM fallback) was tried and rejected: it retains
only 16 of 325 pairs -- gutting the source rather than cleaning it, since
dict coverage of common bare-stem words was independently found to be poor
(0/20 spot-check, PLAN.md/translit_verification.json). The vocab-presence
filter is the right level: it is provenance-agnostic (doesn't matter whether
dict or LLM proposed the spelling) and directly enforces "this pair only
teaches the model about words the game actually uses."

build_cleaned_assembled_data() reuses every OTHER assemble_data.py source
unchanged (dim1_triplets, llm_augmented, crosslingual, alias) -- only
corpus_pmi is filtered -- and writes to *_cleaned.jsonl / counts_cleaned.json
so the original v1/v2 assembled data stays byte-identical and reproducible.

Run: uv run python -m evals.finetune.clean_input_quality
"""

import json
from pathlib import Path

from evals.finetune.assemble_data import (
    CORPUS_PMI_FILTERED_PATH,
    HOMOGRAPH_COLLISIONS,
    alias_source,
    crosslingual_source,
    dim1_source,
    llm_source,
)
from evals.finetune.split import load_split
from vocab import load_hien_vocab

DATA_DIR = Path(__file__).parent / "data"


def quantify() -> dict:
    vocab = {w.lower() for w in load_hien_vocab()}
    records = []
    with CORPUS_PMI_FILTERED_PATH.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))

    both_in_vocab = sum(
        1 for r in records if r["anchor"].lower() in vocab and r["neighbor"].lower() in vocab
    )
    both_dict = sum(
        1
        for r in records
        if r["anchor_translit_source"] == "dict" and r["neighbor_translit_source"] == "dict"
    )
    return {
        "n_corpus_pmi_pairs": len(records),
        "n_both_in_production_vocab": both_in_vocab,
        "pct_both_in_production_vocab": both_in_vocab / len(records) if records else None,
        "n_both_dict_sourced": both_dict,
        "pct_both_dict_sourced": both_dict / len(records) if records else None,
        "decision": (
            "vocab-presence filter (both anchor+neighbor already real vocab words), "
            "not dict-only (which retains only 16/325 -- too aggressive)"
        ),
    }


def corpus_pmi_source_cleaned(held_out: set[str]) -> tuple[list[dict], list[dict]]:
    """Same filtering as assemble_data.corpus_pmi_source, PLUS: both anchor
    and neighbor must already exist in the real production hi-en vocab."""
    vocab = {w.lower() for w in load_hien_vocab()}

    if not CORPUS_PMI_FILTERED_PATH.exists():
        return [], []

    records: list[dict] = []
    with CORPUS_PMI_FILTERED_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    kept: list[dict] = []
    for r in records:
        anchor = r["anchor"].lower()
        neighbor = r["neighbor"].lower()
        if anchor in held_out or neighbor in held_out:
            continue
        if anchor in HOMOGRAPH_COLLISIONS or neighbor in HOMOGRAPH_COLLISIONS:
            continue
        if anchor not in vocab or neighbor not in vocab:
            continue
        kept.append(r)

    graded: list[dict] = [
        {
            "sentence1": r["anchor"],
            "sentence2": r["neighbor"],
            "score": r["score"],
            "source": "corpus_pmi_cleaned",
        }
        for r in kept
    ]
    if kept:
        scores = [r["score"] for r in kept]
        cutoff = (min(scores) + max(scores)) / 2
    else:
        cutoff = 0.0
    mnrl: list[dict] = [
        {"anchor": r["anchor"], "positive": r["neighbor"], "source": "corpus_pmi_cleaned"}
        for r in kept
        if r["score"] > cutoff
    ]
    return mnrl, graded


def _held_out(split: dict) -> set[str]:
    return {w.lower() for w in split["held_out_secrets"]} | {
        w.lower() for w in split["held_out_en_translations"]
    }


def _assert_no_leakage(mnrl: list[dict], graded: list[dict], held_out: set[str]) -> None:
    for rec in mnrl:
        for field in ("anchor", "positive"):
            assert rec[field].lower() not in held_out, f"LEAKAGE in mnrl: {rec}"
    for rec in graded:
        for field in ("sentence1", "sentence2"):
            assert rec[field].lower() not in held_out, f"LEAKAGE in graded: {rec}"


def build_cleaned_assembled_data() -> dict:
    split = load_split()
    held_out = _held_out(split)

    d1_mnrl, d1_graded = dim1_source(split)
    llm_mnrl, llm_graded, llm_stats = llm_source(held_out)
    cl_mnrl, cl_graded = crosslingual_source(held_out)
    al_mnrl, al_graded = alias_source(held_out)
    pmi_mnrl, pmi_graded = corpus_pmi_source_cleaned(held_out)

    all_mnrl = d1_mnrl + llm_mnrl + cl_mnrl + al_mnrl + pmi_mnrl
    all_graded = d1_graded + llm_graded + al_graded + cl_graded + pmi_graded

    seen_mnrl = set()
    deduped_mnrl = []
    for r in all_mnrl:
        key = (r["anchor"].lower(), r["positive"].lower())
        if key not in seen_mnrl:
            seen_mnrl.add(key)
            deduped_mnrl.append(r)

    seen_graded = set()
    deduped_graded = []
    for r in all_graded:
        key = (r["sentence1"].lower(), r["sentence2"].lower())
        if key not in seen_graded:
            seen_graded.add(key)
            deduped_graded.append(r)

    _assert_no_leakage(deduped_mnrl, deduped_graded, held_out)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with (DATA_DIR / "train_mnrl_pairs_cleaned.jsonl").open("w", encoding="utf-8") as f:
        for r in deduped_mnrl:
            f.write(json.dumps(r) + "\n")
    with (DATA_DIR / "train_graded_pairs_cleaned.jsonl").open("w", encoding="utf-8") as f:
        for r in deduped_graded:
            f.write(json.dumps(r) + "\n")

    counts = {
        "mnrl_total_after_dedup": len(deduped_mnrl),
        "graded_total_after_dedup": len(deduped_graded),
        "corpus_pmi_cleaned_mnrl": len(pmi_mnrl),
        "corpus_pmi_cleaned_graded": len(pmi_graded),
        "no_leakage_assertion": "passed",
    }
    (DATA_DIR / "counts_cleaned.json").write_text(
        json.dumps(counts, indent=2) + "\n", encoding="utf-8"
    )
    return counts


if __name__ == "__main__":
    print(json.dumps(quantify(), indent=2))
    print(json.dumps(build_cleaned_assembled_data(), indent=2))
