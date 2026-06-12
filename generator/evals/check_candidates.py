from __future__ import annotations

"""
Temporary script to test candidate eval assertions against the real model.
Run once to determine which candidates pass, then author fixtures accordingly.
Output goes to stdout for manual review.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
from sentence_transformers import SentenceTransformer

from config import MODELS

MODEL_NAME = MODELS["hi-en"]
print(f"Loading model: {MODEL_NAME}")
model = SentenceTransformer(MODEL_NAME)

# Candidates: (id, anchor, closer, farther, note)
CANDIDATES = [
    # Emotion word pairs
    ("001", "khushi", "happiness", "paisa", "happiness synonym vs money"),
    ("002", "khushi", "joy", "paani", "happiness vs water"),
    ("003", "khushi", "anand", "darr", "joy vs fear in Hindi"),
    ("004", "gham", "sadness", "roti", "sorrow vs bread"),
    ("005", "gham", "dard", "paisa", "sorrow vs pain vs money"),
    ("006", "pyaar", "love", "paisa", "love vs money"),
    ("007", "pyaar", "mohabbat", "darr", "love synonyms vs fear"),
    ("008", "darr", "fear", "khushi", "fear vs happiness"),
    ("009", "gussa", "anger", "khushi", "anger vs happiness"),
    ("010", "gussa", "rage", "paani", "anger vs water"),
    # Family
    ("011", "maa", "mother", "paisa", "mother vs money"),
    ("012", "maa", "mata", "ghar", "mother synonyms vs home"),
    ("013", "bhai", "brother", "parbat", "brother vs mountain"),
    ("014", "behen", "sister", "jungle", "sister vs forest"),
    ("015", "pita", "father", "baarish", "father vs rain"),
    ("016", "bachcha", "child", "paisa", "child vs money"),
    ("017", "parivar", "family", "paisa", "family vs money"),
    ("018", "dada", "grandfather", "jungle", "grandfather vs forest"),
    # Daily objects
    ("019", "paani", "water", "parbat", "water vs mountain"),
    ("020", "paani", "water", "gussa", "water vs anger"),
    ("021", "ghar", "home", "jungle", "home vs forest"),
    ("022", "ghar", "house", "samunder", "house vs ocean"),
    ("023", "khana", "food", "darr", "food vs fear"),
    ("024", "roti", "bread", "khushi", "bread vs happiness"),
    ("025", "chai", "tea", "parbat", "tea vs mountain"),
    ("026", "kitaab", "book", "paani", "book vs water"),
    ("027", "kitaab", "book", "baarish", "book vs rain"),
    # Cross-lingual synonyms
    ("028", "dost", "friend", "paisa", "friend vs money"),
    ("029", "dost", "yaar", "parbat", "friend synonyms vs mountain"),
    ("030", "dost", "saathi", "darr", "friend/companion vs fear"),
    ("031", "zindagi", "life", "paisa", "life vs money"),
    ("032", "zindagi", "life", "kitaab", "life vs book"),
    ("033", "safar", "journey", "paani", "journey vs water"),
    ("034", "sapna", "dream", "paisa", "dream vs money"),
    ("035", "baarish", "rain", "paisa", "rain vs money"),
    ("036", "baarish", "monsoon", "gussa", "rain/monsoon vs anger"),
    ("037", "gaana", "music", "paisa", "music vs money"),
    ("038", "gaana", "song", "parbat", "song vs mountain"),
    # Nature
    ("039", "samunder", "ocean", "kitaab", "ocean vs book"),
    ("040", "samunder", "sea", "paisa", "sea vs money"),
    ("041", "parbat", "mountain", "paisa", "mountain vs money"),
    ("042", "jungle", "forest", "khushi", "forest vs happiness"),
    ("043", "nadi", "river", "paisa", "river vs money"),
    ("044", "subah", "morning", "jungle", "morning vs forest"),
    # Time / daily life
    ("045", "kal", "yesterday", "jungle", "yesterday vs forest"),
    ("046", "aaj", "today", "samunder", "today vs ocean"),
    ("047", "raat", "night", "paisa", "night vs money"),
    ("048", "din", "day", "parbat", "day vs mountain"),
    ("049", "kaam", "work", "baarish", "work vs rain"),
    ("050", "naukri", "job", "baarish", "job vs rain"),
    # Emotion vs emotion (should be closer than unrelated)
    ("051", "khushi", "anand", "jungle", "both happiness words vs forest"),
    ("052", "gham", "udaas", "paani", "sadness vs sad feeling vs water"),
    ("053", "darr", "bhay", "kitaab", "fear vs fear-word vs book"),
    ("054", "sukoon", "peace", "gussa", "peace vs anger"),
    ("055", "ummeed", "hope", "darr", "hope vs fear"),
    # en-en sanity pairs
    ("056", "ocean", "sea", "mountain", "ocean closer to sea than mountain"),
    ("057", "family", "home", "jungle", "family closer to home than jungle"),
    ("058", "music", "song", "water", "music closer to song than water"),
    ("059", "friend", "buddy", "mountain", "friend closer to buddy than mountain"),
    ("060", "rain", "water", "book", "rain closer to water than book"),
    ("061", "dream", "sleep", "money", "dream closer to sleep than money"),
    ("062", "journey", "travel", "food", "journey closer to travel than food"),
    ("063", "school", "education", "rain", "school closer to education than rain"),
    ("064", "doctor", "medicine", "rain", "doctor closer to medicine than rain"),
    ("065", "love", "heart", "mountain", "love closer to heart than mountain"),
]

all_words = set()
for _, a, c, f, _ in CANDIDATES:
    all_words.update([a, c, f])

words_list = sorted(all_words)
print(f"Embedding {len(words_list)} unique words...")
vecs_arr = model.encode(
    words_list,
    batch_size=64,
    show_progress_bar=True,
    convert_to_numpy=True,
    normalize_embeddings=True,
)
word_to_vec = {w: vecs_arr[i] for i, w in enumerate(words_list)}

print("\nResults:")
passed = []
failed = []
for cid, anchor, closer, farther, note in CANDIDATES:
    va = word_to_vec[anchor]
    vc = word_to_vec[closer]
    vf = word_to_vec[farther]
    sim_c = float(np.dot(va, vc))
    sim_f = float(np.dot(va, vf))
    ok = sim_c > sim_f
    status = "PASS" if ok else "FAIL"
    print(
        f"  [{status}] {cid}: cos({anchor},{closer})={sim_c:.4f} > cos({anchor},{farther})={sim_f:.4f}  ({note})"
    )
    if ok:
        passed.append(cid)
    else:
        failed.append((cid, anchor, closer, farther, note, sim_c, sim_f))

print(f"\nPassed: {len(passed)}/{len(CANDIDATES)}")
print(f"Failed: {len(failed)}")
if failed:
    print("\nFailed cases:")
    for cid, a, c, f, note, sc, sf in failed:
        print(f"  {cid}: {a} | closer={c}({sc:.4f}) farther={f}({sf:.4f}) — {note}")
