from __future__ import annotations

"""
Assemble Hinglish contrastive training data from 5 sources (spec-hinglish-
finetune.md's "Training data" section), respecting the frozen split
(split.py) — NO training record may touch a held-out secret or its EN
translation, verified by assertion at the end of this module.

Sources:
  1. dim1 triplets — evals/scenarios/dim1_hien.json records whose secret is
     in the TRAIN split only (dev/test-secret records are left untouched in
     that file for held-out eval — see split.py's docstring for why we
     filter at read-time instead of mutating the shared fixture).
  2. LLM-augmented triplets — llm_augment.py, local qwen3:8b, quality-
     filtered, held-out secrets excluded from generation prompts AND
     re-checked post-generation.
  3. Cross-lingual anchor pairs — vocab/hinglish.txt (romanized word, EN
     anchor) pairs, excluding any pair touching a held-out secret or its EN
     translation.
  4. Alias variants — vocab/hi-en-aliases.txt (canonical, alias) trivial-
     positive pairs, excluding held-out canonicals.
  5. Corpus PMI pairs — evals/finetune/data/raw/corpus_pmi_pairs_filtered.jsonl
     (pmi_mine.py's corpus co-occurrence mining, LLM-judge quality-filtered by
     pmi_quality_filter.py), re-excluding held-out secrets and
     HOMOGRAPH_COLLISIONS independently of the upstream staging filters
     (belt-and-suspenders, matching this module's existing per-source
     paranoia — never trust an upstream filter alone). See
     corpus_pmi_source's docstring for the MNRL score cutoff.

Output (evals/finetune/data/):
  train_mnrl_pairs.jsonl    {"anchor", "positive", "source"}      — MultipleNegativesRankingLoss
  train_graded_pairs.jsonl  {"sentence1","sentence2","score","source"} — CosineSimilarityLoss
  counts.json               per-source counts + no-leakage proof
  sample_for_review.json    ~25-pair cross-source sample for GG spot-check

Run: uv run python -m evals.finetune.assemble_data
"""

import json
import random
from pathlib import Path

from evals.finetune.llm_augment import generate_and_filter
from evals.finetune.split import load_split
from profanity import load_en_profanity, load_hi_profanity
from vocab import parse_hinglish_file

DATA_DIR = Path(__file__).parent / "data"
SCENARIOS_PATH = Path(__file__).parent.parent / "scenarios" / "dim1_hien.json"
ALIASES_PATH = Path(__file__).parent.parent.parent / "vocab" / "hi-en-aliases.txt"
LLM_CACHE_PATH = DATA_DIR / "llm_triplets_accepted.json"
HOMOGRAPH_EXCLUSIONS_PATH = DATA_DIR / "homograph_exclusions.json"
CORPUS_PMI_FILTERED_PATH = DATA_DIR / "raw" / "corpus_pmi_pairs_filtered.jsonl"

# GG review (post-data-approval): any romanized-Hindi word whose Latin
# spelling ALSO happens to be a common, DIFFERENT-meaning English word is a
# training hazard — it teaches the model a false association for a real
# English word used in code-mixed play (e.g. "door" = far in Hinglish vs
# "door" = entrance in English). See data/homograph_exclusions.json for the
# full audit (two automated local-LLM-judge passes were tried and rejected
# as unreliable; this is a manual linguistic review). Dropped entirely from
# every source below — not disambiguated, just excluded, per GG's
# instruction ("a small fraction, not worth the risk").
HOMOGRAPH_COLLISIONS = frozenset(
    {
        "door", "din", "band", "pair", "pet", "chain", "beta", "pita",
        "teen", "agar", "koi", "mama", "nana",
    }
)

# GG review: LLM-generated "unrelated" negatives that turned out to be
# genuinely (if indirectly) related, not safe hard negatives — a fuzzy
# negative teaches a fuzzy boundary. (word, unrelated) pairs to drop.
FUZZY_NEGATIVE_EXCLUSIONS = frozenset({("guru", "music"), ("jar", "can")})

TIER_SCORE = {"near": 0.85, "mid": 0.55, "far": 0.05}
LLM_RELATED_SCORE = 0.80
LLM_UNRELATED_SCORE = 0.05
CROSSLINGUAL_SCORE = 0.90
ALIAS_SCORE = 0.95

SAMPLE_SIZE = 25
SAMPLE_SEED = 42


def _held_out(split: dict) -> set[str]:
    return {w.lower() for w in split["held_out_secrets"]} | {
        w.lower() for w in split["held_out_en_translations"]
    }


def dim1_source(split: dict) -> tuple[list[dict], list[dict]]:
    """Returns (mnrl_pairs, graded_pairs) built ONLY from train-split secrets."""
    records = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
    train_secrets = set(split["train_secrets"])
    by_secret: dict[str, dict[str, list[str]]] = {}
    for r in records:
        if r["secret"] not in train_secrets:
            continue
        by_secret.setdefault(r["secret"], {"near": [], "mid": [], "far": []})
        by_secret[r["secret"]][r["tier"]].append(r["word"])

    mnrl: list[dict] = []
    graded: list[dict] = []
    for secret, tiers in by_secret.items():
        for tier, words in tiers.items():
            for w in words:
                graded.append(
                    {
                        "sentence1": secret,
                        "sentence2": w,
                        "score": TIER_SCORE[tier],
                        "source": "dim1_triplets",
                    }
                )
                if tier == "near":
                    mnrl.append({"anchor": secret, "positive": w, "source": "dim1_triplets"})
    return mnrl, graded


def llm_source(held_out: set[str]) -> tuple[list[dict], list[dict], dict]:
    en_profanity = load_en_profanity()
    hi_profanity = load_hi_profanity()

    # LLM generation is non-deterministic (temperature 0.2) and takes ~10+
    # minutes for the full domain sweep — cache the judge-accepted triplets
    # to disk so re-running assemble_data.py (e.g. to fix an unrelated bug
    # in a deterministic source) doesn't requery the LLM and doesn't churn
    # the frozen training set. Delete the cache file to force fresh
    # generation (e.g. after changing DOMAINS/N_PER_DOMAIN).
    if LLM_CACHE_PATH.exists():
        accepted = json.loads(LLM_CACHE_PATH.read_text(encoding="utf-8"))
        stats = {"loaded_from_cache": str(LLM_CACHE_PATH), "n_accepted_after_judge": len(accepted)}
    else:
        accepted, stats = generate_and_filter(held_out, (en_profanity, hi_profanity))
        LLM_CACHE_PATH.write_text(json.dumps(accepted, indent=2) + "\n", encoding="utf-8")

    mnrl: list[dict] = []
    graded: list[dict] = []
    for t in accepted:
        word = t["word"]
        if word.lower() in HOMOGRAPH_COLLISIONS:
            continue
        mnrl.append({"anchor": word, "positive": t["related"], "source": "llm_augmented"})
        graded.append(
            {
                "sentence1": word,
                "sentence2": t["related"],
                "score": LLM_RELATED_SCORE,
                "source": "llm_augmented",
            }
        )
        if (word.lower(), t["unrelated"].lower()) not in FUZZY_NEGATIVE_EXCLUSIONS:
            graded.append(
                {
                    "sentence1": word,
                    "sentence2": t["unrelated"],
                    "score": LLM_UNRELATED_SCORE,
                    "source": "llm_augmented",
                }
            )
    return mnrl, graded, stats


def crosslingual_source(held_out: set[str]) -> tuple[list[dict], list[dict]]:
    pairs = parse_hinglish_file()
    mnrl: list[dict] = []
    graded: list[dict] = []
    for word, anchor in pairs:
        if word.lower() in held_out or anchor.lower() in held_out:
            continue
        if word.lower() in HOMOGRAPH_COLLISIONS:
            continue
        if word.lower() == anchor.lower():
            # English loanwords used as-is in Hinglish (school->school,
            # bus->bus): a real (word, anchor) entry in hinglish.txt, but a
            # degenerate training pair — cos(x,x)=1 regardless of training,
            # zero contrastive signal, not worth the wasted step.
            continue
        mnrl.append({"anchor": word, "positive": anchor, "source": "crosslingual"})
        graded.append(
            {
                "sentence1": word,
                "sentence2": anchor,
                "score": CROSSLINGUAL_SCORE,
                "source": "crosslingual",
            }
        )
    return mnrl, graded


def alias_source(held_out: set[str]) -> tuple[list[dict], list[dict]]:
    mnrl: list[dict] = []
    graded: list[dict] = []
    for raw in ALIASES_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        canonical_raw, aliases_raw = line.split(":", 1)
        canonical = canonical_raw.strip().lower()
        if canonical in held_out:
            continue
        for alias_raw in aliases_raw.split(","):
            alias = alias_raw.strip().lower()
            if not alias or alias in held_out:
                continue
            mnrl.append({"anchor": canonical, "positive": alias, "source": "alias"})
            graded.append(
                {
                    "sentence1": canonical,
                    "sentence2": alias,
                    "score": ALIAS_SCORE,
                    "source": "alias",
                }
            )
    return mnrl, graded


def corpus_pmi_source(held_out: set[str]) -> tuple[list[dict], list[dict]]:
    """
    Corpus PMI-mined relatedness pairs (pmi_mine.py + pmi_quality_filter.py's
    LLM-judge pass — see this module's docstring, source 5). Reads the
    already quality-filtered staging file; does NOT re-run mining or judging.

    Belt-and-suspenders re-filtering (matches every other source function in
    this module): held-out secrets and HOMOGRAPH_COLLISIONS were already
    excluded once upstream (pmi_mine.py step 5 / the judge filter doesn't
    check these at all), but this function independently re-checks both
    rather than trusting the staging file, exactly like crosslingual_source
    and alias_source re-check `held_out` even though their own upstream data
    sources are curated.

    MNRL cutoff: only pairs whose score is in the upper half of THIS
    source's own [min, max] score range are used as MNRL positives — i.e.
    score > (min + max) / 2 — mirroring dim1_source's choice to use only
    tier == "near" (the strongest slice) for MNRL, not "mid"/"far". Graded
    pairs use the full filtered range, mirroring dim1_source's graded pairs
    covering all three tiers.
    """
    if not CORPUS_PMI_FILTERED_PATH.exists():
        return [], []

    records: list[dict] = []
    with CORPUS_PMI_FILTERED_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))

    kept: list[dict] = []
    for r in records:
        anchor = r["anchor"].lower()
        neighbor = r["neighbor"].lower()
        if anchor in held_out or neighbor in held_out:
            continue
        if anchor in HOMOGRAPH_COLLISIONS or neighbor in HOMOGRAPH_COLLISIONS:
            continue
        kept.append(r)

    graded: list[dict] = [
        {
            "sentence1": r["anchor"],
            "sentence2": r["neighbor"],
            "score": r["score"],
            "source": "corpus_pmi",
        }
        for r in kept
    ]

    if kept:
        scores = [r["score"] for r in kept]
        cutoff = (min(scores) + max(scores)) / 2
    else:
        cutoff = 0.0
    mnrl: list[dict] = [
        {"anchor": r["anchor"], "positive": r["neighbor"], "source": "corpus_pmi"}
        for r in kept
        if r["score"] > cutoff
    ]
    return mnrl, graded


def _assert_no_leakage(mnrl: list[dict], graded: list[dict], held_out: set[str]) -> None:
    for rec in mnrl:
        for field in ("anchor", "positive"):
            assert rec[field].lower() not in held_out, f"LEAKAGE in mnrl: {rec}"
    for rec in graded:
        for field in ("sentence1", "sentence2"):
            assert rec[field].lower() not in held_out, f"LEAKAGE in graded: {rec}"


def build() -> dict:
    split = load_split()
    held_out = _held_out(split)

    d1_mnrl, d1_graded = dim1_source(split)
    llm_mnrl, llm_graded, llm_stats = llm_source(held_out)
    cl_mnrl, cl_graded = crosslingual_source(held_out)
    al_mnrl, al_graded = alias_source(held_out)
    pmi_mnrl, pmi_graded = corpus_pmi_source(held_out)

    all_mnrl = d1_mnrl + llm_mnrl + cl_mnrl + al_mnrl + pmi_mnrl
    all_graded = d1_graded + llm_graded + al_graded + cl_graded + pmi_graded

    # Dedup exact (anchor, positive) / (sentence1, sentence2, score) duplicates
    # that can arise across sources (e.g. dim1 and crosslingual both proposing
    # the same secret->translation pair for a train-split secret).
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
    with (DATA_DIR / "train_mnrl_pairs.jsonl").open("w", encoding="utf-8") as f:
        for r in deduped_mnrl:
            f.write(json.dumps(r) + "\n")
    with (DATA_DIR / "train_graded_pairs.jsonl").open("w", encoding="utf-8") as f:
        for r in deduped_graded:
            f.write(json.dumps(r) + "\n")

    counts = {
        "mnrl_pairs": {
            "dim1_triplets": len(d1_mnrl),
            "llm_augmented": len(llm_mnrl),
            "crosslingual": len(cl_mnrl),
            "alias": len(al_mnrl),
            "corpus_pmi": len(pmi_mnrl),
            "total_before_dedup": len(all_mnrl),
            "total_after_dedup": len(deduped_mnrl),
        },
        "graded_pairs": {
            "dim1_triplets": len(d1_graded),
            "llm_augmented": len(llm_graded),
            "crosslingual": len(cl_graded),
            "alias": len(al_graded),
            "corpus_pmi": len(pmi_graded),
            "total_before_dedup": len(all_graded),
            "total_after_dedup": len(deduped_graded),
        },
        "llm_augment_pipeline_stats": llm_stats,
        "held_out_secret_count": len(split["held_out_secrets"]),
        "homograph_collisions_excluded": sorted(HOMOGRAPH_COLLISIONS),
        "fuzzy_negative_pairs_excluded": sorted(
            f"{w}->{u}" for w, u in FUZZY_NEGATIVE_EXCLUSIONS
        ),
        "no_leakage_assertion": "passed — no training record contains a held-out "
        "secret or its EN translation (see _assert_no_leakage)",
    }
    (DATA_DIR / "counts.json").write_text(json.dumps(counts, indent=2) + "\n", encoding="utf-8")

    rng = random.Random(SAMPLE_SEED)
    sample_mnrl = rng.sample(deduped_mnrl, k=min(15, len(deduped_mnrl)))
    sample_graded = rng.sample(deduped_graded, k=min(10, len(deduped_graded)))
    sample = {"mnrl_sample": sample_mnrl, "graded_sample": sample_graded}
    (DATA_DIR / "sample_for_review.json").write_text(
        json.dumps(sample, indent=2) + "\n", encoding="utf-8"
    )

    return counts


if __name__ == "__main__":
    counts = build()
    print(json.dumps(counts, indent=2))
