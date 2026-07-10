from __future__ import annotations

"""
Generate dimension-1 (semantic ranking quality) synthetic scenarios.

For a sample of secrets (drawn from the daily EN<->hi-en paired schedule),
produces (secret, guess, tier) triples where tier in {near, mid, far}:

  near — hand-curated true synonyms / very strong direct associates.
         Expected to land in the Scorching/Hot bands.
  mid  — hand-curated same-domain-but-not-synonym words.
         Expected to land in the Warm band.
  far  — SEEDED RANDOM sample from the full vocab, excluding the secret, its
         near/mid words, and anything within Levenshtein distance 3 of the
         secret (avoids accidental morphological closeness). Auto-labeling is
         safe here because a random word from a 10k-55k word vocab is
         overwhelmingly likely to be semantically unrelated to any given
         secret — unlike near/mid, which require real judgment.
         Expected to land in the Cold/Freezing bands.

near/mid tiers are the highest-risk-of-being-wrong labels (spec: "garbage
labels -> meaningless metrics"), so they're hand-authored with care, not
generated. hi-en near/mid words deliberately prefer the EN-paired translation
plus one more Hindi/English word confirmed present in the hi-en vocab — every
word in this file was checked against load_en_vocab()/load_hien_vocab()
before being committed (see PLAN.md for the two rejected drafts and why).

GG review (2026-07-10) relabeled two near-tier pairs that were only "related",
not true synonyms/strong associates: bagicha<-lawn and aaina<-glass both
moved to mid (with a replacement near word added to keep 2 near each); the
same flaw existed in the EN garden<-lawn / mirror<-glass pairs (not in GG's
sample, fixed proactively for consistency) — see garden/mirror/bagicha/aaina
below. forest<-safari (a weak mid label) was swapped for forest<-camping.

hi-en near-tier words are tagged with a "subtype": "translation" when the
word is exactly the secret's EN daily-schedule pair (see harness/pairs.py) —
a guaranteed-correct cross-lingual synonym — vs "associate" for anything
else (a genuine in-language semantic neighbor, e.g. baarish<-shower). GG
review: these test different model capabilities (does the model know a
translation vs does it understand in-language meaning) and must be reported
as separate band-accuracy numbers, not blended — the in-language number is
the real signal for whether Hinglish semantic play works.

Known watch-item: baarish<-shower is kept (per GG) but "shower" is polysemous
(rain-shower vs bathing-shower vs baby-shower) — flagged explicitly in the
report rather than silently trusted, same treatment as the pre-existing
KF-H19/H20 known-failure fixtures for baarish.

Output: evals/scenarios/dim1_en.json, evals/scenarios/dim1_hien.json
Each file is a flat list of records:
  {"secret": str, "word": str, "tier": "near"|"mid"|"far", "expected_bands": [int, ...],
   "subtype": "translation"|"associate"|null, "note": str|null}
expected_bands are TemperatureBand ordinals (see rival.band_for_rank):
  0=win 1=scorching 2=hot 3=warm 4=cold 5=freezing
near -> [1,2], mid -> [3], far -> [4,5]

Usage (from generator/):
    uv run python evals/gen_dim1_scenarios.py
"""

import json
import random
from pathlib import Path

from evals.harness.pairs import hien_to_en_map
from payload import levenshtein
from vocab import load_en_vocab, load_hien_vocab

SCENARIOS_DIR = Path(__file__).parent / "scenarios"

FAR_PER_SECRET = 5
FAR_SAMPLE_SEED = 42
FAR_MIN_LEVENSHTEIN = 4  # exclude anything within edit-distance 3 of the secret

# Common function words excluded from the far-tier sample pool: they're
# trivially "unrelated" to any secret but read as noise in a sample review
# (e.g. "from", "with") rather than a meaningful semantic-distance test.
_FAR_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "from", "that", "this", "have", "not",
        "are", "was", "were", "been", "being", "will", "would", "could",
        "should", "there", "their", "them", "than", "then", "when", "where",
        "which", "while", "what", "who", "whom", "whose", "how", "why",
        "into", "onto", "upon", "over", "under", "about", "above", "below",
        "between", "among", "through", "during", "before", "after", "again",
        "further", "once", "here", "any", "each", "few", "more", "most",
        "other", "some", "such", "only", "own", "same", "just", "but", "you",
        "your", "yours", "she", "her", "hers", "his", "him", "its", "our",
        "ours", "they", "these", "those", "yes",
    }
)

EXPECTED_BANDS = {"near": [1, 2], "mid": [3], "far": [4, 5]}

# ---------------------------------------------------------------------------
# Curated near/mid tiers — 20 secrets, drawn from the daily EN<->hi-en paired
# schedule (vocab/secrets_en.txt / secrets_hi-en.txt, same line number).
# Every word here is confirmed present in its language's vocab.
# ---------------------------------------------------------------------------

EN_CURATED: dict[str, dict[str, list[str]]] = {
    "ocean": {"near": ["sea", "water"], "mid": ["beach", "wave"]},
    "music": {"near": ["song", "melody"], "mid": ["concert", "instrument"]},
    "rain": {"near": ["shower", "storm"], "mid": ["umbrella", "monsoon"]},
    "family": {"near": ["relatives", "kin"], "mid": ["parents", "home"]},
    "mountain": {"near": ["peak", "hill"], "mid": ["climb", "snow"]},
    "fire": {"near": ["flame", "blaze"], "mid": ["smoke", "heat"]},
    "dream": {"near": ["sleep", "vision"], "mid": ["imagination", "wish"]},
    "friend": {"near": ["buddy", "companion"], "mid": ["friendship", "trust"]},
    "garden": {"near": ["yard", "greenery"], "mid": ["flower", "plant", "lawn"]},
    "river": {"near": ["stream", "creek"], "mid": ["bank", "flow"]},
    "forest": {"near": ["woods", "jungle"], "mid": ["wildlife", "camping"]},
    "market": {"near": ["shop", "store"], "mid": ["vendor", "price"]},
    "memory": {"near": ["recollection", "remember"], "mid": ["nostalgia", "past"]},
    "mirror": {"near": ["reflection", "reflective"], "mid": ["bathroom", "image", "glass"]},
    "victory": {"near": ["win", "triumph"], "mid": ["champion", "celebration"]},
    "courage": {"near": ["bravery", "boldness"], "mid": ["hero", "strength"]},
    "wisdom": {"near": ["knowledge", "intelligence"], "mid": ["wise", "learning"]},
    "childhood": {"near": ["youth", "kid"], "mid": ["innocence", "nostalgia"]},
    "hunger": {"near": ["starving", "appetite"], "mid": ["food", "meal"]},
    "flower": {"near": ["bloom", "petal"], "mid": ["garden", "fragrance"]},
    "moon": {"near": ["lunar", "crescent"], "mid": ["satellite", "eclipse"]},
    "temple": {"near": ["shrine", "worship"], "mid": ["prayer", "god"]},
    "letter": {"near": ["mail", "envelope"], "mid": ["writing", "post"]},
    "soldier": {"near": ["warrior", "army"], "mid": ["battle", "uniform"]},
    "treasure": {"near": ["gold", "riches"], "mid": ["gem", "wealth"]},
}

# hi-en secrets are the EN-paired line for each EN_CURATED secret above (same
# schedule line in vocab/secrets_{en,hi-en}.txt). near-tier deliberately
# includes the EN translation (a guaranteed-correct cross-lingual synonym,
# same pattern as the existing H01-H35 eval fixtures) plus one more word
# confirmed in the hi-en vocab.
HIEN_CURATED: dict[str, dict[str, list[str]]] = {
    "samunder": {"near": ["sea", "paani"], "mid": ["beach", "wave"]},
    "gaana": {"near": ["geet", "song"], "mid": ["concert", "instrument"]},
    "baarish": {"near": ["shower", "rain"], "mid": ["umbrella", "cloud"]},
    "parivar": {"near": ["family", "relatives"], "mid": ["parents", "ghar"]},
    "pahad": {"near": ["peak", "mountain"], "mid": ["climb", "snow"]},
    "aag": {"near": ["flame", "fire"], "mid": ["smoke", "heat"]},
    "sapna": {"near": ["neend", "dream"], "mid": ["imagination", "wish"]},
    "dost": {"near": ["yaar", "friend"], "mid": ["trust", "friendship"]},
    "bagicha": {"near": ["yard", "garden"], "mid": ["phool", "plant", "lawn"]},
    "nadi": {"near": ["stream", "river"], "mid": ["flow", "water"]},
    "jungle": {"near": ["woods", "van"], "mid": ["wildlife", "trees"]},
    "bazar": {"near": ["shop", "dukaan"], "mid": ["vendor", "price"]},
    "yaad": {"near": ["memory", "remember"], "mid": ["past", "purana"]},
    "aaina": {"near": ["reflection", "mirror"], "mid": ["bathroom", "image", "glass"]},
    "jeet": {"near": ["win", "victory"], "mid": ["champion", "celebration"]},
    "himmat": {"near": ["courage", "brave"], "mid": ["hero", "strength"]},
    "gyaan": {"near": ["knowledge", "wisdom"], "mid": ["wise", "learning"]},
    "bachpan": {"near": ["youth", "childhood"], "mid": ["innocence", "past"]},
    "bhook": {"near": ["starving", "appetite"], "mid": ["khana", "meal"]},
    "phool": {"near": ["bloom", "flower"], "mid": ["bagicha", "khushbu"]},
    "chaand": {"near": ["moon", "satellite"], "mid": ["eclipse", "sky"]},
    "mandir": {"near": ["temple", "worship"], "mid": ["prayer", "god"]},
    "khat": {"near": ["letter", "mail"], "mid": ["envelope", "writing"]},
    "sipahi": {"near": ["soldier", "warrior"], "mid": ["army", "battle"]},
    "khazana": {"near": ["treasure", "gold"], "mid": ["gem", "wealth"]},
}


def _sample_far_words(
    secret: str,
    exclude: set[str],
    vocab: list[str],
    rng: random.Random,
    k: int,
) -> list[str]:
    """Seeded-random sample of `k` words unrelated to `secret`.

    Excludes `exclude` (secret + its near/mid words) and anything within
    Levenshtein distance < FAR_MIN_LEVENSHTEIN of the secret.
    """
    pool = [
        w
        for w in vocab
        if w not in exclude
        and w not in _FAR_STOPWORDS
        and levenshtein(w, secret) >= FAR_MIN_LEVENSHTEIN
    ]
    return rng.sample(pool, k)


# Watch-list notes attached to specific (secret, word) pairs — documented
# risk kept deliberately (GG review 2026-07-10), not silently trusted.
_WATCH_NOTES: dict[tuple[str, str], str] = {
    ("baarish", "shower"): (
        "polysemous: 'shower' can mean rain-shower (intended), bathing-shower, "
        "or baby-shower — kept per GG review, flag explicitly in the report "
        "rather than averaging away; see also KF-H19/H20 known-failure fixtures "
        "for baarish's other documented clustering issues."
    ),
}


def build_scenarios(
    curated: dict[str, dict[str, list[str]]],
    vocab: list[str],
    hien_pair_map: dict[str, str] | None = None,
) -> list[dict]:
    """Build the full scenario list (near + mid + seeded-random far) for one language.

    `hien_pair_map` (hien_secret -> en_secret), when given, tags every
    near-tier record with subtype "translation" (word == the secret's EN
    pair) or "associate" (anything else) — see module docstring. EN records
    and non-near tiers always get subtype=None.
    """
    rng = random.Random(FAR_SAMPLE_SEED)
    records: list[dict] = []
    for secret in sorted(curated):  # sorted: deterministic iteration order
        tiers = curated[secret]
        exclude = {secret, *tiers["near"], *tiers["mid"]}
        en_pair = (hien_pair_map or {}).get(secret)
        for tier in ("near", "mid"):
            for word in tiers[tier]:
                subtype = None
                if tier == "near" and hien_pair_map is not None:
                    subtype = "translation" if word == en_pair else "associate"
                records.append(
                    {
                        "secret": secret,
                        "word": word,
                        "tier": tier,
                        "expected_bands": EXPECTED_BANDS[tier],
                        "subtype": subtype,
                        "note": _WATCH_NOTES.get((secret, word)),
                    }
                )
        far_words = _sample_far_words(secret, exclude, vocab, rng, FAR_PER_SECRET)
        for word in far_words:
            records.append(
                {
                    "secret": secret,
                    "word": word,
                    "tier": "far",
                    "expected_bands": EXPECTED_BANDS["far"],
                    "subtype": None,
                    "note": None,
                }
            )
    return records


def main() -> None:
    SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)

    en_vocab = load_en_vocab()
    hien_vocab = load_hien_vocab()

    en_scenarios = build_scenarios(EN_CURATED, en_vocab)
    hien_scenarios = build_scenarios(HIEN_CURATED, hien_vocab, hien_to_en_map())

    en_path = SCENARIOS_DIR / "dim1_en.json"
    hien_path = SCENARIOS_DIR / "dim1_hien.json"
    en_path.write_text(
        json.dumps(en_scenarios, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    hien_path.write_text(
        json.dumps(hien_scenarios, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"Wrote {len(en_scenarios)} EN scenarios -> {en_path}")
    print(f"Wrote {len(hien_scenarios)} hi-en scenarios -> {hien_path}")
    print(f"Secrets covered: {len(EN_CURATED)} EN, {len(HIEN_CURATED)} hi-en")


if __name__ == "__main__":
    main()
