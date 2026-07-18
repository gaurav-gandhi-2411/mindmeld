from __future__ import annotations

"""
Generate the held-out BENCHMARK-SUPPLEMENT dimension-1 scenarios — 34 brand
new secrets across 7 domains (nature, emotion, abstract, object, place,
food, kinship), added per spec-hinglish-benchmark.md Phase 1a to expand the
frozen held-out test set (n=16 -> n=50) with substantially more domain
diversity, WITHOUT touching the production 25-secret/60-word daily-schedule
pipeline (evals/gen_dim1_scenarios.py, evals/finetune/data/split.json's
core train/dev/test assignment) at all.

Architecture: deliberately a SIBLING module, not an extension of
gen_dim1_scenarios.py, so baseline_report.md's "full production set" scope
is completely unchanged by this expansion (GG decision, spec Phase 1a). This
module imports build_scenarios() from gen_dim1_scenarios.py (reused, not
duplicated) for the per-secret hashed-RNG far-tier sampling — the ONLY
shared code path.

Every one of the 34 new secrets + every near/mid word below was verified,
before being committed, against ALL FIVE assembled training files
(evals/finetune/data/train_{mnrl,graded}_pairs*.jsonl) with a direct
case-insensitive membership grep across every relevant field (anchor,
positive, negative, sentence1, sentence2) — zero hits, confirming none of
this benchmark-supplement content leaked into training via the open-
vocabulary crosslingual_source/corpus_pmi_source/llm_augment.py sources
(which scan the FULL vocab/hinglish.txt, not just the daily-schedule 60).
Also verified zero homograph collision: none of the 34 hien secret strings
appears anywhere in vocab/en.txt (the game's own curated English vocab),
so none carries the false-friend risk flagged in
evals/finetune/homograph_audit.py's docstring (e.g. "door"/"far",
"din"/"day").

Design choice — near/mid tiers are PURE ENGLISH (not new Hindi words):
gen_dim1_scenarios.py's EN_CURATED/HIEN_CURATED sometimes uses hand-picked
Hindi near/mid words (e.g. "yaad": mid=["past","purana"]), but ALSO already
has several entries whose HIEN near tier is 100% English (e.g. "sipahi":
near=["soldier","warrior"] — neither word is Hindi). This module leans
fully into that already-established pattern: HIEN_CURATED_SUPPLEMENT's
near/mid tiers are mechanically DERIVED from EN_CURATED_SUPPLEMENT (near =
[EN_CURATED_SUPPLEMENT's own near[0], the secret's EN gloss translation],
mid = EN_CURATED_SUPPLEMENT's own mid list verbatim — matching the
existing "aag"/"sapna"/"himmat" precedent where HIEN mid tier is often
byte-identical to the paired EN secret's mid tier). This was a deliberate
scope-control decision: introducing dozens of BRAND NEW Hindi near/mid
words would multiply the leak-check surface for no real benefit (the
translation-tagged near word already gives a genuine cross-lingual
correctness signal — see subtype logic in gen_dim1_scenarios.build_scenarios).

Output: evals/scenarios/dim1_benchmark_supplement_en.json,
        evals/scenarios/dim1_benchmark_supplement_hien.json
Same record schema as dim1_{en,hien}.json (see gen_dim1_scenarios.py's
module docstring for the schema).

Usage (from generator/):
    uv run python -m evals.gen_dim1_benchmark_supplement
"""

import json
from pathlib import Path

from evals.gen_dim1_scenarios import build_scenarios
from vocab import load_en_vocab, load_hien_vocab

SCENARIOS_DIR = Path(__file__).parent / "scenarios"

# (hien_secret, en_gloss, domain) — the single source of truth for this
# supplement's 34 secrets. evals/finetune/split.py imports this to union
# the secrets into test_secrets/held_out_secrets/held_out_en_translations
# (never into train_secrets/dev_secrets, never into the daily-schedule
# 55-secret shuffle pool).
BENCHMARK_SUPPLEMENT_PAIRS: list[tuple[str, str, str]] = [
    ("registan", "desert", "nature"),
    ("jheel", "lake", "nature"),
    ("chattan", "rock", "nature"),
    ("dhoop", "sunlight", "nature"),
    ("patta", "leaf", "nature"),
    ("sharm", "shyness", "emotion"),
    ("chinta", "worry", "emotion"),
    ("mazaa", "enjoyment", "emotion"),
    ("junoon", "passion", "emotion"),
    ("udaasi", "sadness", "emotion"),
    ("azaadi", "freedom", "abstract"),
    ("insaaf", "justice", "abstract"),
    ("waqt", "duration", "abstract"),
    ("sawaal", "question", "abstract"),
    ("kanoon", "law", "abstract"),
    ("chaabi", "key", "object"),
    ("sandook", "trunk", "object"),
    ("thaali", "platter", "object"),
    ("tokri", "basket", "object"),
    ("chimni", "chimney", "object"),
    ("sadak", "road", "place"),
    ("sarhad", "border", "place"),
    ("basti", "settlement", "place"),
    ("mohalla", "neighborhood", "place"),
    ("dehat", "countryside", "place"),
    ("mithai", "dessert", "food"),
    ("dahi", "yogurt", "food"),
    ("paneer", "paneer", "food"),
    ("besan", "gram", "food"),
    ("khichdi", "khichdi", "food"),
    ("mausi", "auntie", "kinship"),
    ("bhanja", "nephew", "kinship"),
    ("bhanji", "niece", "kinship"),
    ("judwaa", "twin", "kinship"),
]

# ---------------------------------------------------------------------------
# EN curated near/mid tiers, keyed by EN gloss (34 secrets, 7 domains).
# Every word verified (see module docstring) against all 5 assembled
# training files + vocab/en.txt presence.
# ---------------------------------------------------------------------------
EN_CURATED_SUPPLEMENT: dict[str, dict[str, list[str]]] = {
    "desert": {"near": ["wasteland", "barren"], "mid": ["dune", "drought"]},
    "lake": {"near": ["lagoon", "reservoir"], "mid": ["shore", "fishing"]},
    "rock": {"near": ["boulder", "granite"], "mid": ["cliff", "mineral"]},
    "sunlight": {"near": ["brightness", "daylight"], "mid": ["warmth", "ray"]},
    "leaf": {"near": ["foliage", "petal"], "mid": ["stem", "twig"]},
    "shyness": {"near": ["modesty", "reticence"], "mid": ["blush", "introvert"]},
    "worry": {"near": ["unease", "apprehension"], "mid": ["stress", "nervous"]},
    "enjoyment": {"near": ["amusement", "delight"], "mid": ["cheer", "playful"]},
    "passion": {"near": ["zeal", "enthusiasm"], "mid": ["obsession", "drive"]},
    "sadness": {"near": ["melancholy", "grief"], "mid": ["misery", "despair"]},
    "freedom": {"near": ["liberty", "independence"], "mid": ["rights", "release"]},
    "justice": {"near": ["fairness", "equity"], "mid": ["verdict", "judge"]},
    "duration": {"near": ["interval", "moment"], "mid": ["schedule", "era"]},
    "question": {"near": ["query", "inquiry"], "mid": ["answer", "doubt"]},
    "law": {"near": ["rule", "regulation"], "mid": ["court", "legislation"]},
    "key": {"near": ["lock", "latch"], "mid": ["padlock", "security"]},
    "trunk": {"near": ["vault", "case"], "mid": ["storage", "luggage"]},
    "platter": {"near": ["dish", "crockery"], "mid": ["cutlery", "serving"]},
    "basket": {"near": ["hamper", "crate"], "mid": ["weave", "picnic"]},
    "chimney": {"near": ["flue", "exhaust"], "mid": ["soot", "duct"]},
    "road": {"near": ["street", "highway"], "mid": ["traffic", "pavement"]},
    "border": {"near": ["boundary", "frontier"], "mid": ["fence", "checkpoint"]},
    "settlement": {"near": ["hamlet", "township"], "mid": ["migrant", "housing"]},
    "neighborhood": {"near": ["locality", "community"], "mid": ["neighbor", "block"]},
    "countryside": {"near": ["rural", "farmland"], "mid": ["meadow", "pastoral"]},
    "dessert": {"near": ["candy", "confection"], "mid": ["sweetness", "treat"]},
    "yogurt": {"near": ["curd", "dairy"], "mid": ["breakfast", "chilled"]},
    "paneer": {"near": ["curd", "dairy"], "mid": ["cube", "curry"]},
    "gram": {"near": ["legume", "batter"], "mid": ["cooking", "protein"]},
    "khichdi": {"near": ["porridge", "stew"], "mid": ["comfort", "hearty"]},
    "auntie": {"near": ["relative", "guardian"], "mid": ["household", "niece"]},
    "nephew": {"near": ["kin", "relative"], "mid": ["household", "elder"]},
    "niece": {"near": ["kin", "relative"], "mid": ["household", "auntie"]},
    "twin": {"near": ["duplicate", "sibling"], "mid": ["household", "identical"]},
}


def _hien_to_en_map() -> dict[str, str]:
    """hien_secret -> en_gloss for this supplement's 34 pairs."""
    return {hien: en for hien, en, _domain in BENCHMARK_SUPPLEMENT_PAIRS}


def _build_hien_curated() -> dict[str, dict[str, list[str]]]:
    """Mechanically derive HIEN_CURATED_SUPPLEMENT from EN_CURATED_SUPPLEMENT
    (see module docstring's "Design choice" section for the rationale):
    near = [EN's own near[0], the secret's EN gloss translation (guarantees
    build_scenarios tags it subtype="translation")], mid = EN's own mid
    list verbatim.
    """
    hien_curated: dict[str, dict[str, list[str]]] = {}
    for hien, en_gloss, _domain in BENCHMARK_SUPPLEMENT_PAIRS:
        en_tiers = EN_CURATED_SUPPLEMENT[en_gloss]
        hien_curated[hien] = {
            "near": [en_tiers["near"][0], en_gloss],
            "mid": list(en_tiers["mid"]),
        }
    return hien_curated


HIEN_CURATED_SUPPLEMENT: dict[str, dict[str, list[str]]] = _build_hien_curated()


def main() -> None:
    SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)

    en_vocab = load_en_vocab()
    hien_vocab = load_hien_vocab()

    en_scenarios = build_scenarios(EN_CURATED_SUPPLEMENT, en_vocab)
    hien_scenarios = build_scenarios(HIEN_CURATED_SUPPLEMENT, hien_vocab, _hien_to_en_map())

    en_path = SCENARIOS_DIR / "dim1_benchmark_supplement_en.json"
    hien_path = SCENARIOS_DIR / "dim1_benchmark_supplement_hien.json"
    en_path.write_text(
        json.dumps(en_scenarios, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    hien_path.write_text(
        json.dumps(hien_scenarios, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"Wrote {len(en_scenarios)} EN scenarios -> {en_path}")
    print(f"Wrote {len(hien_scenarios)} hi-en scenarios -> {hien_path}")
    print(f"Secrets covered: {len(EN_CURATED_SUPPLEMENT)} EN, {len(HIEN_CURATED_SUPPLEMENT)} hi-en")


if __name__ == "__main__":
    main()
