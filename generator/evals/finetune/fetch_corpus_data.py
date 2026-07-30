from __future__ import annotations

"""
Data acquisition for the (not-yet-approved next round of) Hinglish fine-tune:
pulls the two commercially-clean sources cleared by the licensing gate and
builds a Devanagari -> romanized transliteration dictionary from one of them.

Sources (both public, no auth required — verified by anonymous HfApi calls
before writing this module):
  1. Aksharantar (ai4bharat/Aksharantar, CC-BY manually-collected tier +
     CC0 mined tier) — word/name-level Devanagari<->romanized transliteration
     pairs. Pulled directly as `hin.zip` (not through datasets' streaming
     "default" config, which interleaves all 21 languages by
     unique_identifier prefix and would require scanning past every earlier
     language alphabetically to reach "hin"). hin.zip contains hin_train.json
     (1,299,155 pairs — matches the spec's "~1.3M train pairs" figure
     exactly), hin_valid.json (6,357) and hin_test.json (10,112). Only TRAIN
     is pulled: valid/test are AI4Bharat's own held-out eval split for their
     transliteration model, not needed for a dictionary-building task.
  2. IndicCorp v2 (ai4bharat/IndicCorpV2, CC0) — raw Hindi sentences,
     `hin_Deva` split. This is NOT a `datasets` BuilderConfig name (that
     confusion is corrected here for the next person): `hin_Deva` is a KEY
     inside the `indiccorp_v2` config's IterableDatasetDict, backed by three
     26.6GB shards (data/hi-1.txt, hi-2.txt, hi-3.txt). Streaming through
     `datasets`' own text-file loader hit a Windows-only bug (its default
     `open()` has no explicit encoding, so it decodes with the process
     locale's codepage instead of UTF-8, e.g. cp1252, and dies on the first
     multi-byte character no matter how early you stop). This module
     bypasses that entirely: it resolves the file's HTTP URL via
     `huggingface_hub.hf_hub_url` and streams raw bytes with `requests`,
     decoding each complete line as UTF-8 itself. Collection stops at the
     first of MAX_SENTENCES / MAX_BYTES (see constants below) — always
     starting from hi-1.txt, since either cap is reached well inside that
     one 26.6GB shard; hi-2.txt and hi-3.txt are never touched. No shuffling
     or sampling is performed: this is a deterministic byte-prefix of a
     fixed public file, so (unlike the stochastic steps documented in
     split.py/assemble_data.py) there is no SEED to pin — the same prefix
     is produced on every run against the same file revision.

Transliteration dictionary policy (documented per spec — see
build_translit_dict docstring for the exact tie-break rule).

Run: uv run python -m evals.finetune.fetch_corpus_data
Outputs (generator/evals/finetune/data/):
  raw/aksharantar_hi.jsonl        — all 1,299,155 Aksharantar hin_train pairs, gitignored
  raw/translit_dict_hi.json       — {devanagari: romanized} dictionary, gitignored
  raw/indiccorp_v2_hi_sample.txt  — capped sentence sample, one per line, gitignored
  translit_verification.json      — spot-check table against vocab/hinglish.txt, tracked
"""

import json
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import requests
from huggingface_hub import hf_hub_download, hf_hub_url

from vocab import parse_hinglish_file

DATA_DIR = Path(__file__).parent / "data"
RAW_DIR = DATA_DIR / "raw"

AKSHARANTAR_REPO = "ai4bharat/Aksharantar"
AKSHARANTAR_ZIP_ENTRY = "hin_train.json"
AKSHARANTAR_OUT = RAW_DIR / "aksharantar_hi.jsonl"
TRANSLIT_DICT_OUT = RAW_DIR / "translit_dict_hi.json"

INDICCORP_REPO = "ai4bharat/IndicCorpV2"
INDICCORP_SHARD = "data/hi-1.txt"  # see module docstring: caps hit inside this one shard
INDICCORP_OUT = RAW_DIR / "indiccorp_v2_hi_sample.txt"
MAX_SENTENCES = 2_000_000
MAX_BYTES = 150 * 1024 * 1024  # 150MB
LOG_EVERY = 200_000

VERIFICATION_OUT = DATA_DIR / "translit_verification.json"

# 20 romanized words already in vocab/hinglish.txt, hand-mapped to their
# Devanagari spelling from GG's own Hindi knowledge (spec step 3). Several
# common words have more than one "standard" Devanagari spelling (nuqta vs
# no-nuqta for loan consonants like ज़/ख़; anusvara ं vs chandrabindu ँ for
# nasalization) — where that ambiguity exists, CANDIDATES lists every
# spelling worth trying against the dict, in the order a fluent reader would
# reach for them, and the verification step reports whichever one actually
# hits.
VERIFICATION_WORDS: list[tuple[str, list[str]]] = [
    ("dost", ["दोस्त"]),
    ("yaar", ["यार"]),
    ("zindagi", ["ज़िंदगी", "जिंदगी"]),
    ("sapna", ["सपना"]),
    ("raat", ["रात"]),
    ("khana", ["खाना"]),
    ("chai", ["चाय"]),
    ("baarish", ["बारिश"]),
    ("bachcha", ["बच्चा"]),
    ("maa", ["माँ", "मां"]),
    ("pita", ["पिता"]),
    ("bhai", ["भाई"]),
    ("behen", ["बहन"]),
    ("kitaab", ["किताब"]),
    ("gaana", ["गाना"]),
    ("shehar", ["शहर"]),
    ("paisa", ["पैसा"]),
    ("kaam", ["काम"]),
    ("khushi", ["ख़ुशी", "खुशी"]),
    ("ummeed", ["उम्मीद"]),
]


def fetch_aksharantar() -> list[tuple[str, str]]:
    """
    Download hin.zip, extract hin_train.json, write the raw pairs to
    AKSHARANTAR_OUT, and return [(devanagari, romanized), ...] for
    build_translit_dict. Devanagari is kept as-is; romanized is NOT
    lowercased here (that happens in build_translit_dict) so the raw JSONL
    preserves exactly what Aksharantar shipped.
    """
    zip_path = Path(
        hf_hub_download(repo_id=AKSHARANTAR_REPO, filename="hin.zip", repo_type="dataset")
    )
    pairs: list[tuple[str, str]] = []
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with (
        zipfile.ZipFile(zip_path) as zf,
        zf.open(AKSHARANTAR_ZIP_ENTRY) as member,
        AKSHARANTAR_OUT.open("w", encoding="utf-8") as out,
    ):
        for raw_line in member:
            record = json.loads(raw_line)
            deva = record["native word"]
            rom = record["english word"]
            out.write(
                json.dumps(
                    {
                        "devanagari": deva,
                        "romanized": rom,
                        "source": record.get("source"),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            pairs.append((deva, rom))
    return pairs


def build_translit_dict(pairs: list[tuple[str, str]]) -> dict[str, str]:
    """
    Build {devanagari_word: romanized_word} from Aksharantar pairs.

    Policy (spec step 2 — documented here, not just in the summary report):
    Aksharantar has multiple romanized variants per Devanagari word (mined
    from different annotators/sources — Dakshina, AK-Freq, etc). For each
    Devanagari word, count how often each lowercased romanized form occurs
    across all pairs and keep the MOST FREQUENT one. Ties are broken by
    (1) shortest string, then (2) alphabetically first — both purely
    deterministic, so re-running this function against the same input
    always produces the same dictionary (no seed needed; this is a counting
    aggregation, not a stochastic sample).

    Romanized side is lowercased to match the engine's vocab convention
    (vocab.py's parse_hinglish_file lowercases both columns of hinglish.txt).
    """
    tally: dict[str, Counter[str]] = defaultdict(Counter)
    for deva, rom in pairs:
        tally[deva][rom.strip().lower()] += 1

    result: dict[str, str] = {}
    for deva, counts in tally.items():
        best_rom, _ = min(counts.items(), key=lambda item: (-item[1], len(item[0]), item[0]))
        result[deva] = best_rom
    return result


def fetch_indiccorp_sample() -> dict:
    """
    Stream INDICCORP_SHARD over HTTP and write plain-text lines to
    INDICCORP_OUT until MAX_SENTENCES or MAX_BYTES is hit (see module
    docstring for why streaming bypasses `datasets` entirely). Returns a
    stats dict with the ACTUAL counts collected (never estimated).
    """
    url = hf_hub_url(INDICCORP_REPO, INDICCORP_SHARD, repo_type="dataset")
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    sentences = 0
    bytes_written = 0
    stop_reason = "exhausted_stream"  # overwritten below on the actual cap hit
    buffer = b""

    with requests.Session() as session:
        resp = session.get(url, stream=True, timeout=(10, 60))
        resp.raise_for_status()
        try:
            with INDICCORP_OUT.open("w", encoding="utf-8", newline="\n") as out:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    buffer += chunk
                    lines = buffer.split(b"\n")
                    buffer = lines.pop()  # last element may be a partial line — keep buffering
                    for raw_line in lines:
                        text = raw_line.decode("utf-8", errors="replace").strip()
                        if not text:
                            continue
                        out.write(text + "\n")
                        sentences += 1
                        bytes_written += len(text.encode("utf-8")) + 1
                        if sentences % LOG_EVERY == 0:
                            print(f"  ...{sentences:,} sentences, {bytes_written:,} bytes")
                        if sentences >= MAX_SENTENCES:
                            stop_reason = "max_sentences_reached"
                            break
                        if bytes_written >= MAX_BYTES:
                            stop_reason = "max_bytes_reached"
                            break
                    if stop_reason != "exhausted_stream":
                        break
        finally:
            resp.close()

    return {
        "shard": INDICCORP_SHARD,
        "shards_skipped": ["data/hi-2.txt", "data/hi-3.txt"],
        "sentences_collected": sentences,
        "bytes_collected": bytes_written,
        "stop_reason": stop_reason,
    }


def verify_translit_quality(translit_dict: dict[str, str]) -> list[dict]:
    """
    Spec step 3: for each of VERIFICATION_WORDS, look up the Devanagari
    candidate spelling(s) in translit_dict and compare the dict's
    romanization against the existing romanization already in
    vocab/hinglish.txt. `match` is "yes" (identical), "close" (same after
    stripping vowel-length doubling, i.e. what normalize.py's aa/ee/oo
    folding rules would collapse), or "no".
    """
    existing = dict(parse_hinglish_file())  # {romanized: en_anchor} — we just need the keys

    def _fold(s: str) -> str:
        # Mirrors normalize.py's vowel-length folding so "close" means
        # "the engine's own normalizer would already treat these as equal",
        # not an arbitrary fuzzy-match threshold.
        return s.replace("chh", "ch").replace("aa", "a").replace("ee", "i").replace("oo", "u")

    rows: list[dict] = []
    for expected_rom, candidates in VERIFICATION_WORDS:
        if expected_rom not in existing:
            raise ValueError(
                f"{expected_rom!r} not found in vocab/hinglish.txt — pick a word that is"
            )
        dict_rom = None
        matched_deva = None
        for deva in candidates:
            if deva in translit_dict:
                dict_rom = translit_dict[deva]
                matched_deva = deva
                break
        if dict_rom is None:
            match = "no"
        elif dict_rom == expected_rom:
            match = "yes"
        elif _fold(dict_rom) == _fold(expected_rom):
            match = "close"
        else:
            match = "no"
        rows.append(
            {
                "devanagari_tried": candidates,
                "devanagari_matched": matched_deva,
                "expected_existing_romanization": expected_rom,
                "dict_romanization": dict_rom,
                "match": match,
            }
        )
    return rows


def main() -> dict:
    print("Fetching Aksharantar hin_train.json ...")
    pairs = fetch_aksharantar()
    print(f"  {len(pairs):,} pairs -> {AKSHARANTAR_OUT}")

    print("Building transliteration dictionary ...")
    translit_dict = build_translit_dict(pairs)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    TRANSLIT_DICT_OUT.write_text(
        json.dumps(translit_dict, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"  {len(translit_dict):,} unique Devanagari words -> {TRANSLIT_DICT_OUT}")

    print(
        f"Streaming IndicCorp v2 {INDICCORP_SHARD} (cap: {MAX_SENTENCES:,} sentences / "
        f"{MAX_BYTES:,} bytes) ..."
    )
    indiccorp_stats = fetch_indiccorp_sample()
    print(f"  {indiccorp_stats}")

    print("Verifying transliteration quality against vocab/hinglish.txt ...")
    verification_rows = verify_translit_quality(translit_dict)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    VERIFICATION_OUT.write_text(
        json.dumps(verification_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    summary = {
        "aksharantar_pairs_loaded": len(pairs),
        "translit_dict_size": len(translit_dict),
        "indiccorp": indiccorp_stats,
        "translit_verification_rows": verification_rows,
    }
    return summary


if __name__ == "__main__":
    result = main()
    print(json.dumps(result, ensure_ascii=False, indent=2))
