from __future__ import annotations

"""One-off script to generate fixture JSON files from validated candidate lists."""

import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"
KNOWN_FAILURES_DIR = Path(__file__).parent / "fixtures_known_failures"

FIXTURES_DIR.mkdir(exist_ok=True)
KNOWN_FAILURES_DIR.mkdir(exist_ok=True)

# Active fixtures (all verified PASS against the real model)
ACTIVE = [
    {
        "id": "H01",
        "lang": "hi-en",
        "anchor": "roti",
        "closer": "bread",
        "farther": "ocean",
        "note": "roti=bread; bread is far closer to ocean than bread (cross-lingual synonym)",
    },
    {
        "id": "H02",
        "lang": "hi-en",
        "anchor": "roti",
        "closer": "bread",
        "farther": "doctor",
        "note": "roti=bread; semantically food vs medical domain",
    },
    {
        "id": "H03",
        "lang": "hi-en",
        "anchor": "roti",
        "closer": "bread",
        "farther": "music",
        "note": "roti=bread; food vs music domain",
    },
    {
        "id": "H04",
        "lang": "hi-en",
        "anchor": "safar",
        "closer": "journey",
        "farther": "bread",
        "note": "safar=journey; travel domain vs food",
    },
    {
        "id": "H05",
        "lang": "hi-en",
        "anchor": "safar",
        "closer": "travel",
        "farther": "bread",
        "note": "safar=travel; cross-lingual synonym vs food",
    },
    {
        "id": "H06",
        "lang": "hi-en",
        "anchor": "jungle",
        "closer": "forest",
        "farther": "bread",
        "note": "jungle=forest; nature vs food",
    },
    {
        "id": "H07",
        "lang": "hi-en",
        "anchor": "jungle",
        "closer": "forest",
        "farther": "doctor",
        "note": "jungle=forest; nature vs medical domain",
    },
    {
        "id": "H08",
        "lang": "hi-en",
        "anchor": "pyaar",
        "closer": "love",
        "farther": "bread",
        "note": "pyaar=love; emotion vs food",
    },
    {
        "id": "H09",
        "lang": "hi-en",
        "anchor": "pyaar",
        "closer": "love",
        "farther": "ocean",
        "note": "pyaar=love; emotion vs nature",
    },
    {
        "id": "H10",
        "lang": "hi-en",
        "anchor": "dost",
        "closer": "friend",
        "farther": "bread",
        "note": "dost=friend; social vs food domain",
    },
    {
        "id": "H11",
        "lang": "hi-en",
        "anchor": "dost",
        "closer": "friend",
        "farther": "ocean",
        "note": "dost=friend; social vs nature",
    },
    {
        "id": "H12",
        "lang": "hi-en",
        "anchor": "maa",
        "closer": "mother",
        "farther": "bread",
        "note": "maa=mother; family vs food",
    },
    {
        "id": "H13",
        "lang": "hi-en",
        "anchor": "maa",
        "closer": "mother",
        "farther": "ocean",
        "note": "maa=mother; family vs nature",
    },
    {
        "id": "H14",
        "lang": "hi-en",
        "anchor": "gaana",
        "closer": "song",
        "farther": "bread",
        "note": "gaana=song; music vs food",
    },
    {
        "id": "H15",
        "lang": "hi-en",
        "anchor": "gaana",
        "closer": "music",
        "farther": "bread",
        "note": "gaana=music; music domain vs food",
    },
    {
        "id": "H16",
        "lang": "hi-en",
        "anchor": "zindagi",
        "closer": "life",
        "farther": "bread",
        "note": "zindagi=life; abstract concept vs food",
    },
    {
        "id": "H17",
        "lang": "hi-en",
        "anchor": "sapna",
        "closer": "dream",
        "farther": "bread",
        "note": "sapna=dream; abstract vs food",
    },
    {
        "id": "H18",
        "lang": "hi-en",
        "anchor": "chai",
        "closer": "tea",
        "farther": "ocean",
        "note": "chai=tea; beverage vs ocean",
    },
    {
        "id": "H21",
        "lang": "hi-en",
        "anchor": "maa",
        "closer": "mata",
        "farther": "ocean",
        "note": "maa/mata are Hindi near-synonyms for mother; ocean is unrelated",
    },
    {
        "id": "H22",
        "lang": "hi-en",
        "anchor": "gham",
        "closer": "dard",
        "farther": "ocean",
        "note": "gham=sorrow, dard=pain — semantically adjacent Hindi words vs ocean",
    },
    {
        "id": "H23",
        "lang": "hi-en",
        "anchor": "dost",
        "closer": "saathi",
        "farther": "ocean",
        "note": "dost/saathi are friend/companion in Hindi — vs ocean",
    },
    {
        "id": "H24",
        "lang": "hi-en",
        "anchor": "khushi",
        "closer": "anand",
        "farther": "ocean",
        "note": "khushi/anand are happiness synonyms in Hindi — vs ocean",
    },
    {
        "id": "H25",
        "lang": "hi-en",
        "anchor": "safar",
        "closer": "journey",
        "farther": "music",
        "note": "safar=journey; travel vs music domain",
    },
    {
        "id": "H26",
        "lang": "hi-en",
        "anchor": "kal",
        "closer": "yesterday",
        "farther": "medicine",
        "note": "kal=yesterday (time) vs medical domain",
    },
    {
        "id": "H28",
        "lang": "hi-en",
        "anchor": "din",
        "closer": "day",
        "farther": "medicine",
        "note": "din=day (time) vs medical domain",
    },
    {
        "id": "H29",
        "lang": "hi-en",
        "anchor": "raat",
        "closer": "night",
        "farther": "medicine",
        "note": "raat=night (time) vs medical domain",
    },
    {
        "id": "H30",
        "lang": "hi-en",
        "anchor": "kitaab",
        "closer": "book",
        "farther": "medicine",
        "note": "kitaab=book (education) vs medical domain",
    },
    {
        "id": "H31",
        "lang": "hi-en",
        "anchor": "dost",
        "closer": "friend",
        "farther": "medicine",
        "note": "dost=friend (social) vs medical domain",
    },
    {
        "id": "H32",
        "lang": "hi-en",
        "anchor": "ghar",
        "closer": "home",
        "farther": "battle",
        "note": "ghar=home (domestic) vs battle (conflict)",
    },
    {
        "id": "H34",
        "lang": "hi-en",
        "anchor": "naukri",
        "closer": "job",
        "farther": "flower",
        "note": "naukri=job (work) vs flower (nature)",
    },
    # English-English sanity pairs
    {
        "id": "E01",
        "lang": "hi-en",
        "anchor": "ocean",
        "closer": "sea",
        "farther": "mountain",
        "note": "ocean and sea are near-synonyms; mountain is unrelated geography",
    },
    {
        "id": "E02",
        "lang": "hi-en",
        "anchor": "music",
        "closer": "song",
        "farther": "water",
        "note": "music and song are close; water is unrelated",
    },
    {
        "id": "E03",
        "lang": "hi-en",
        "anchor": "friend",
        "closer": "buddy",
        "farther": "mountain",
        "note": "friend and buddy are synonyms; mountain is unrelated",
    },
    {
        "id": "E04",
        "lang": "hi-en",
        "anchor": "school",
        "closer": "education",
        "farther": "rain",
        "note": "school/education are same domain; rain is unrelated",
    },
    {
        "id": "E05",
        "lang": "hi-en",
        "anchor": "doctor",
        "closer": "medicine",
        "farther": "rain",
        "note": "doctor/medicine are same domain; rain is unrelated",
    },
    {
        "id": "E06",
        "lang": "hi-en",
        "anchor": "rain",
        "closer": "water",
        "farther": "book",
        "note": "rain/water are physically related; book is unrelated",
    },
    {
        "id": "E07",
        "lang": "hi-en",
        "anchor": "journey",
        "closer": "travel",
        "farther": "food",
        "note": "journey/travel are synonyms; food is unrelated",
    },
    {
        "id": "E08",
        "lang": "hi-en",
        "anchor": "dream",
        "closer": "sleep",
        "farther": "money",
        "note": "dream/sleep are cognitively linked; money is unrelated",
    },
    {
        "id": "E09",
        "lang": "hi-en",
        "anchor": "love",
        "closer": "heart",
        "farther": "mountain",
        "note": "love/heart are emotionally linked; mountain is unrelated",
    },
    {
        "id": "E10",
        "lang": "hi-en",
        "anchor": "family",
        "closer": "home",
        "farther": "jungle",
        "note": "family/home are conceptually linked; jungle is unrelated",
    },
    {
        "id": "E11",
        "lang": "hi-en",
        "anchor": "war",
        "closer": "battle",
        "farther": "flower",
        "note": "war/battle are synonyms; flower is unrelated",
    },
    {
        "id": "E12",
        "lang": "hi-en",
        "anchor": "teacher",
        "closer": "school",
        "farther": "ocean",
        "note": "teacher/school same domain; ocean is unrelated",
    },
    {
        "id": "E13",
        "lang": "hi-en",
        "anchor": "hospital",
        "closer": "medicine",
        "farther": "music",
        "note": "hospital/medicine same domain; music is unrelated",
    },
    {
        "id": "E14",
        "lang": "hi-en",
        "anchor": "book",
        "closer": "library",
        "farther": "rain",
        "note": "book/library same domain; rain is unrelated",
    },
    {
        "id": "E15",
        "lang": "hi-en",
        "anchor": "flower",
        "closer": "garden",
        "farther": "war",
        "note": "flower/garden same domain; war is unrelated",
    },
    {
        "id": "E16",
        "lang": "hi-en",
        "anchor": "winter",
        "closer": "cold",
        "farther": "fire",
        "note": "winter/cold are semantically linked; fire is antonymous",
    },
    {
        "id": "E17",
        "lang": "hi-en",
        "anchor": "fire",
        "closer": "heat",
        "farther": "water",
        "note": "fire/heat are related; water is antagonistic/unrelated",
    },
    {
        "id": "E18",
        "lang": "hi-en",
        "anchor": "king",
        "closer": "queen",
        "farther": "river",
        "note": "king/queen are related royalty terms; river is unrelated",
    },
    {
        "id": "E19",
        "lang": "hi-en",
        "anchor": "child",
        "closer": "baby",
        "farther": "mountain",
        "note": "child/baby are synonyms; mountain is unrelated",
    },
    {
        "id": "E20",
        "lang": "hi-en",
        "anchor": "city",
        "closer": "town",
        "farther": "forest",
        "note": "city/town are similar settlements; forest is contrasting",
    },
    {
        "id": "E21",
        "lang": "hi-en",
        "anchor": "money",
        "closer": "cash",
        "farther": "music",
        "note": "money/cash are synonyms; music is unrelated",
    },
    {
        "id": "E22",
        "lang": "hi-en",
        "anchor": "victory",
        "closer": "win",
        "farther": "rain",
        "note": "victory/win are synonyms; rain is unrelated",
    },
    {
        "id": "E23",
        "lang": "hi-en",
        "anchor": "morning",
        "closer": "sunrise",
        "farther": "money",
        "note": "morning/sunrise are linked; money is unrelated",
    },
    {
        "id": "E24",
        "lang": "hi-en",
        "anchor": "soldier",
        "closer": "army",
        "farther": "flower",
        "note": "soldier/army same domain; flower is unrelated",
    },
    {
        "id": "E25",
        "lang": "hi-en",
        "anchor": "forest",
        "closer": "tree",
        "farther": "music",
        "note": "forest/tree are related (part-whole); music is unrelated",
    },
    # From round 1 passes
    {
        "id": "R01",
        "lang": "hi-en",
        "anchor": "gham",
        "closer": "dard",
        "farther": "paisa",
        "note": "gham=sorrow, dard=pain (Hindi emotion pair) vs paisa=money",
    },
    {
        "id": "R02",
        "lang": "hi-en",
        "anchor": "maa",
        "closer": "mata",
        "farther": "ghar",
        "note": "maa/mata are mother synonyms vs ghar=home",
    },
    {
        "id": "R03",
        "lang": "hi-en",
        "anchor": "dada",
        "closer": "grandfather",
        "farther": "jungle",
        "note": "dada=grandfather (family) vs jungle (nature)",
    },
    {
        "id": "R04",
        "lang": "hi-en",
        "anchor": "roti",
        "closer": "bread",
        "farther": "khushi",
        "note": "roti=bread (food) vs khushi=happiness (emotion)",
    },
    {
        "id": "R05",
        "lang": "hi-en",
        "anchor": "safar",
        "closer": "journey",
        "farther": "paani",
        "note": "safar=journey (travel) vs paani=water (nature)",
    },
]

# Known failures (linguistically valid but model fails)
KNOWN_FAILURES = [
    {
        "id": "KF-H19",
        "lang": "hi-en",
        "anchor": "baarish",
        "closer": "rain",
        "farther": "bread",
        "note": "baarish=rain but 'baarish' clusters with other Hindi tokens not English 'rain'",
        "reason": "paraphrase-multilingual-MiniLM-L12-v2 maps romanized Hindi weather words closer "
        "to English food words than their direct translations. baarish(rain)=0.39 < baarish(bread)=0.51. "
        "Model limitation: Hinglish romanization not well-represented in multilingual training data.",
    },
    {
        "id": "KF-H20",
        "lang": "hi-en",
        "anchor": "baarish",
        "closer": "rain",
        "farther": "music",
        "note": "baarish=rain but model places it closer to music than rain",
        "reason": "Same as KF-H19: baarish(rain)=0.39 < baarish(music)=0.50. "
        "Model does not reliably ground romanized Hindi weather terms to English equivalents.",
    },
    {
        "id": "KF-H27",
        "lang": "hi-en",
        "anchor": "subah",
        "closer": "morning",
        "farther": "medicine",
        "note": "subah=morning but model places subah closer to medicine than morning",
        "reason": "subah(morning)=0.47 < subah(medicine)=0.50. Marginal failure. "
        "The romanized time-of-day word 'subah' is not reliably grounded in multilingual model.",
    },
    {
        "id": "KF-H33",
        "lang": "hi-en",
        "anchor": "khana",
        "closer": "food",
        "farther": "battle",
        "note": "khana=food but model places it closer to battle than food",
        "reason": "khana(food)=0.29 < khana(battle)=0.36. "
        "'khana' as romanized Hindi food word is poorly grounded; model may map to 'khan' (title) "
        "or other non-food senses in multilingual space.",
    },
    {
        "id": "KF-H35",
        "lang": "hi-en",
        "anchor": "paani",
        "closer": "water",
        "farther": "battle",
        "note": "paani=water but model places it closer to battle than water",
        "reason": "paani(water)=0.40 < paani(battle)=0.51. "
        "'paani' does not reliably cluster with English 'water' in this multilingual model. "
        "Romanized Hindi phonology does not match English equivalent tokens.",
    },
]

# Write active fixtures
for fix in ACTIVE:
    fid = fix["id"]
    path = FIXTURES_DIR / f"{fid}.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(fix, fh, indent=2, ensure_ascii=False)
    print(f"Wrote fixture: {path.name}")

# Write known failures
for fix in KNOWN_FAILURES:
    fid = fix["id"]
    path = KNOWN_FAILURES_DIR / f"{fid}.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(fix, fh, indent=2, ensure_ascii=False)
    print(f"Wrote known failure: {path.name}")

print(f"\nActive fixtures: {len(ACTIVE)}")
print(f"Known failures: {len(KNOWN_FAILURES)}")
