from __future__ import annotations

"""
Second round of candidate testing with model-informed fixture design.

Key insight from round 1:
  - Romanized Hindi words cluster together in embedding space regardless of meaning.
  - paani, gussa, parbat, jungle etc. are all "Hindi-looking" and sim very high to each other.
  - Best strategy: anchor=Hindi, closer=its direct English translation,
    farther=an English word from a completely different semantic domain.
  - OR: anchor=English, closer=English synonym, farther=English unrelated.
  - OR: anchor=Hindi, closer=Hindi near-synonym (Urdu/other Hindi word), farther=very different English concept.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
from sentence_transformers import SentenceTransformer

from config import MODELS

MODEL_NAME = MODELS["hi-en"]
model = SentenceTransformer(MODEL_NAME)

# New candidates using insights from round 1
# Strategy: anchor=Hindi, closer=English translation, farther=semantically distant English
CANDIDATES2 = [
    # Hindi → English translation closer than very distant English concept
    ("H01", "roti", "bread", "ocean", "bread vs ocean (roti=bread)"),
    ("H02", "roti", "bread", "doctor", "bread vs doctor"),
    ("H03", "roti", "bread", "music", "bread vs music"),
    ("H04", "safar", "journey", "bread", "journey vs bread"),
    ("H05", "safar", "travel", "bread", "travel vs bread"),
    ("H06", "jungle", "forest", "bread", "forest vs bread"),
    ("H07", "jungle", "forest", "doctor", "forest vs doctor"),
    ("H08", "pyaar", "love", "bread", "love vs bread"),
    ("H09", "pyaar", "love", "ocean", "love vs ocean"),
    ("H10", "dost", "friend", "bread", "friend vs bread"),
    ("H11", "dost", "friend", "ocean", "friend vs ocean"),
    ("H12", "maa", "mother", "bread", "mother vs bread"),
    ("H13", "maa", "mother", "ocean", "mother vs ocean"),
    ("H14", "gaana", "song", "bread", "song vs bread (gaana=song)"),
    ("H15", "gaana", "music", "bread", "music vs bread"),
    ("H16", "zindagi", "life", "bread", "life vs bread"),
    ("H17", "sapna", "dream", "bread", "dream vs bread"),
    ("H18", "chai", "tea", "ocean", "tea vs ocean"),
    ("H19", "baarish", "rain", "bread", "rain vs bread (baarish=rain)"),
    ("H20", "baarish", "rain", "music", "rain vs music"),
    # Hindi near-synonyms vs distant English
    ("H21", "maa", "mata", "ocean", "mother near-synonym vs ocean"),
    ("H22", "gham", "dard", "ocean", "sorrow/pain vs ocean"),
    ("H23", "dost", "saathi", "ocean", "friend/companion vs ocean"),
    ("H24", "khushi", "anand", "ocean", "happiness near-synonym vs ocean"),
    ("H25", "safar", "journey", "music", "journey vs music"),
    # English-English sanity (from round 1 passes)
    ("E01", "ocean", "sea", "mountain", "ocean~sea vs mountain"),
    ("E02", "music", "song", "water", "music~song vs water"),
    ("E03", "friend", "buddy", "mountain", "friend~buddy vs mountain"),
    ("E04", "school", "education", "rain", "school~education vs rain"),
    ("E05", "doctor", "medicine", "rain", "doctor~medicine vs rain"),
    ("E06", "rain", "water", "book", "rain~water vs book"),
    ("E07", "journey", "travel", "food", "journey~travel vs food"),
    ("E08", "dream", "sleep", "money", "dream~sleep vs money"),
    ("E09", "love", "heart", "mountain", "love~heart vs mountain"),
    ("E10", "family", "home", "jungle", "family~home vs jungle"),
    # More English sanity pairs
    ("E11", "war", "battle", "flower", "war~battle vs flower"),
    ("E12", "teacher", "school", "ocean", "teacher~school vs ocean"),
    ("E13", "hospital", "medicine", "music", "hospital~medicine vs music"),
    ("E14", "book", "library", "rain", "book~library vs rain"),
    ("E15", "flower", "garden", "war", "flower~garden vs war"),
    ("E16", "winter", "cold", "fire", "winter~cold vs fire"),
    ("E17", "fire", "heat", "water", "fire~heat vs water"),
    ("E18", "king", "queen", "river", "king~queen vs river"),
    ("E19", "child", "baby", "mountain", "child~baby vs mountain"),
    ("E20", "city", "town", "forest", "city~town vs forest"),
    ("E21", "money", "cash", "music", "money~cash vs music"),
    ("E22", "victory", "win", "rain", "victory~win vs rain"),
    ("E23", "morning", "sunrise", "money", "morning~sunrise vs money"),
    ("E24", "soldier", "army", "flower", "soldier~army vs flower"),
    ("E25", "forest", "tree", "music", "forest~tree vs music"),
    # Hindi-anchor, English-closer vs very different English domain
    ("H26", "kal", "yesterday", "medicine", "yesterday vs medicine"),
    ("H27", "subah", "morning", "medicine", "morning vs medicine"),
    ("H28", "din", "day", "medicine", "day vs medicine"),
    ("H29", "raat", "night", "medicine", "night vs medicine"),
    ("H30", "kitaab", "book", "medicine", "book vs medicine (different domains)"),
    # Cross-lingual synonym vs very different domain
    ("H31", "dost", "friend", "medicine", "friend vs medicine"),
    ("H32", "ghar", "home", "battle", "home vs battle"),
    ("H33", "khana", "food", "battle", "food vs battle"),
    ("H34", "naukri", "job", "flower", "job vs flower"),
    ("H35", "paani", "water", "battle", "water vs battle"),
]

all_words = set()
for _, a, c, f, _ in CANDIDATES2:
    all_words.update([a, c, f])

words_list = sorted(all_words)
print(f"Embedding {len(words_list)} unique words...")
vecs_arr = model.encode(
    words_list,
    batch_size=64,
    show_progress_bar=False,
    convert_to_numpy=True,
    normalize_embeddings=True,
)
word_to_vec = {w: vecs_arr[i] for i, w in enumerate(words_list)}

print("Results:")
passed_list = []
failed_list = []
for cid, anchor, closer, farther, note in CANDIDATES2:
    va = word_to_vec[anchor]
    vc = word_to_vec[closer]
    vf = word_to_vec[farther]
    sim_c = float(np.dot(va, vc))
    sim_f = float(np.dot(va, vf))
    ok = sim_c > sim_f
    status = "PASS" if ok else "FAIL"
    print(
        f"  [{status}] {cid}: {anchor}|closer={closer}({sim_c:.4f}) farther={farther}({sim_f:.4f}) ({note})"
    )
    if ok:
        passed_list.append((cid, anchor, closer, farther, note, sim_c, sim_f))
    else:
        failed_list.append((cid, anchor, closer, farther, note, sim_c, sim_f))

print(f"\nPassed: {len(passed_list)}/{len(CANDIDATES2)}")
if failed_list:
    print("Failed:")
    for cid, a, c, f, note, sc, sf in failed_list:
        print(f"  {cid}: {a} closer={c}({sc:.4f}) farther={f}({sf:.4f}) — {note}")
