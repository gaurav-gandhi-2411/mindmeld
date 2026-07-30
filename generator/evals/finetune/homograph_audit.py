from __future__ import annotations

"""
Homograph-collision audit (post-data-approval fix, GG review).

Any romanized-Hindi word whose Latin spelling ALSO happens to be a common
English dictionary word with an UNRELATED meaning is a training hazard: it
teaches the model a false association for a real English word used in
code-mixed play (e.g. "door" = far in Hinglish vs "door" = entrance in
English). This is the single most dangerous training-pair class for a
code-mixed model — worse than an ordinary bad label, because it actively
corrupts an otherwise-correct English word's embedding.

Candidates: intersect every crosslingual/LLM-augmented pair's Hindi-side
token against the game's own curated English vocabulary
(vocab.load_en_vocab()) — NOT raw wordfreq, which is itself contaminated by
code-mixed internet text (wordfreq's English corpus ranks "bhai"/"yaar" too,
purely from code-switched social media text, not because they're real
distinct-meaning English words).

Most candidates are FALSE POSITIVES: genuine English loanwords used as-is
in Hinglish with a COMPATIBLE meaning ("mobile"->"phone", "test"->"exam" —
not a collision, just a cross-language synonym pair where one side happens
to be a borrowed English word). A single isolated judge call per candidate
decides collision vs loanword — reusing the isolated-single-purpose-prompt
pattern from judge_client.py/llm_augment.py rather than trusting the model
to self-adjudicate in a compound prompt.

Run: uv run python -m evals.finetune.homograph_audit
Output: evals/finetune/data/homograph_exclusions.json (word -> verdict + reasoning-free bool)
"""

import json
import urllib.error
import urllib.request
from pathlib import Path

from vocab import load_en_vocab

DATA_DIR = Path(__file__).parent / "data"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen3:8b"
TIMEOUT_SECONDS = 60

_COLLISION_PROMPT = """A word-association game pairs "{word}" with the meaning "{meaning}".

Imagine an English speaker who only knows English (no Hindi) sees the bare word "{word}" with \
NO other context. What would THEY assume it means?

- If their default/first-guess understanding of "{word}" would ALREADY be something like \
"{meaning}" (the same concept, a synonym, or a direct English loanword sense) — this is NOT a \
collision. Answer false.
- If their default/first-guess understanding of "{word}" would be a COMPLETELY DIFFERENT, \
unrelated concept (so pairing it with "{meaning}" would actively mislead them) — this IS a \
collision. Answer true.

Calibration examples:
- "door" paired with "far": an English speaker assumes "door" = entrance/hinged panel, totally \
unrelated to "far" -> collision=true.
- "din" paired with "day": an English speaker assumes "din" = loud noise, unrelated to "day" -> \
collision=true.
- "mobile" paired with "phone": an English speaker's first guess for "mobile" IS phone/cellphone \
-> collision=false (same concept, not misleading).
- "test" paired with "exam": an English speaker's first guess for "test" IS exam/trial -> \
collision=false (same concept).
- "fridge" paired with "refrigerator": literally the same word abbreviated -> collision=false.
- "cycle" paired with "bicycle": an English speaker's first guess for "cycle" IS bicycle in this \
context -> collision=false.
- "guru" paired with "teacher": an English speaker already understands "guru" to mean an expert/\
teacher figure -> collision=false.

Respond with ONLY: {{"collision": <true|false>}}"""


def _call_ollama(word: str, meaning: str) -> bool:
    body = json.dumps(
        {
            "model": MODEL,
            "prompt": _COLLISION_PROMPT.format(word=word, meaning=meaning),
            "stream": False,
            "think": False,
            "format": "json",
            "options": {"temperature": 0.0},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
        outer = json.loads(response.read())
    return bool(json.loads(outer.get("response", "{}")).get("collision", False))


def find_candidates() -> dict[str, str]:
    """word -> its POSITIVE-pair meaning, for every crosslingual/llm_augmented
    training record whose Hindi-side token is also in the game's EN vocab."""
    en = set(load_en_vocab())
    mnrl = [
        json.loads(line)
        for line in (DATA_DIR / "train_mnrl_pairs.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    candidates: dict[str, str] = {}
    for r in mnrl:
        if r["source"] not in ("crosslingual", "llm_augmented"):
            continue
        w = r["anchor"].lower()
        if w in en and w not in candidates:
            candidates[w] = r["positive"].lower()
    return candidates


def audit() -> dict:
    candidates = find_candidates()
    verdicts: dict[str, bool] = {}
    for word, meaning in sorted(candidates.items()):
        verdicts[word] = _call_ollama(word, meaning)

    collisions = sorted(w for w, is_collision in verdicts.items() if is_collision)
    cleared = sorted(w for w, is_collision in verdicts.items() if not is_collision)

    result = {
        "n_candidates": len(candidates),
        "collisions": collisions,
        "cleared_loanwords": cleared,
        "candidate_meanings": candidates,
    }
    out_path = DATA_DIR / "homograph_exclusions.json"
    out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    result = audit()
    print(f"n_candidates: {result['n_candidates']}")
    print(f"collisions ({len(result['collisions'])}): {result['collisions']}")
    print(f"cleared as loanwords ({len(result['cleared_loanwords'])})")
