from __future__ import annotations

"""
Local LLM-as-judge client — Ollama qwen3:8b, $0 cost, no API key (respects
the Claude-Max-plan "never set ANTHROPIC_API_KEY" rule; this doesn't touch
Anthropic's API at all, it's a fully local model call).

Requires `ollama serve` running locally with qwen3:8b pulled:
    ollama pull qwen3:8b

THREE SEPARATE CALLS PER CLUE, not one compound call — both splits were
earned during calibration (2026-07-10), not assumed:

  1. spoiler check: a single compound prompt (solvability+spoiler+difficulty
     together) made the model silently fail spoiler detection even for
     blatant cases (a clue ending "...a classic village scene" against
     secret "village" judged spoiler_flag=false). Isolating it to a short,
     single-purpose "does word X appear in text Y" prompt fixed this —
     calibration agreement went 59%->97% on the golden spoiler set.
  2. solvability check: even after isolating spoiler detection, a combined
     solvability+difficulty(+cultural_fit) prompt was too lenient — it rated
     a "shadow" clue ("Follows you everywhere; never exists on cloudy days")
     as solvability=5 for the WRONG secret "coffee". Isolating solvability
     into its own strict "does this clue actually, logically describe X —
     say false even if you can imagine a stretch" prompt fixed the
     false-positive problem, but shifted some risk the other way: this
     game's clues are deliberately indirect/evocative by design (not literal
     restatements), and "be strict" made the judge occasionally rate a
     genuinely-correct, GG-approved clue as low-solvability too. Calibrated
     agreement after this change: spoiler 96.9%, solvability 65.6% (up from
     53% pre-fix, not fully resolved) — see baseline_report.md. Reported
     honestly rather than iterated indefinitely chasing a bigger number;
     this is a real, expected characteristic of an 8B local judge model, not
     a bug to keep patching.
  3. difficulty + cultural_fit stay combined — no calibration ground truth
     exists for either (no objective "correct" difficulty/cultural-fit
     label), and neither showed the same collapse under a compound prompt,
     so splitting further buys nothing measurable for 33% more calls.
"""

import json
import urllib.error
import urllib.request

OLLAMA_URL = "http://localhost:11434/api/generate"
JUDGE_MODEL = "qwen3:8b"
TIMEOUT_SECONDS = 60

_SPOILER_PROMPT = (
    'Does the word "{secret}" appear in the text "{clue}"? '
    'Respond with ONLY: {{"present": <true|false>}}'
)

_SOLVABILITY_PROMPT = """A word-guessing game clue is meant to describe exactly one secret word.
Clue: "{clue}"
Proposed secret word: "{secret}"

Does this specific clue actually, logically describe "{secret}"? Be strict: if the clue \
describes something else entirely, say false even if you can imagine a stretch. Then rate \
how strongly it points at "{secret}" specifically, from 1 (no real connection) to 5 (points \
at it clearly and unambiguously).

Respond with ONLY: {{"matches": <true|false>, "solvability": <1-5 int>}}"""

_DIFFICULTY_PROMPT = """You are judging a clue for a semantic word-guessing game. A player sees \
ONLY the clue (never the secret) and must guess the secret word.

Secret word: {secret}
Clue: "{clue}"
Language: {lang_label}

1. difficulty (1-5): assuming the clue does correctly describe the secret, how hard is it to \
solve? 1 = very easy/obvious, 5 = very hard/obscure.
{cultural_fit_instruction}

Respond with ONLY a JSON object, no other text, no markdown fences:
{{"difficulty": <1-5 int>{cultural_fit_field}}}"""

_CULTURAL_FIT_INSTRUCTION = (
    "2. cultural_fit (1-5): this clue is written in Hinglish (romanized Hindi + English "
    "code-mixing) for an Indian player. Does it read as natively written for that audience "
    "(idiomatic, culturally grounded) rather than a stiff translation from English? "
    "5 = natively idiomatic, 1 = reads like a translated English sentence."
)


class JudgeUnavailableError(RuntimeError):
    """Raised when the local Ollama judge model can't be reached."""


def _call_ollama(prompt: str, secret: str) -> dict:
    body = json.dumps(
        {
            "model": JUDGE_MODEL,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "format": "json",
            "options": {"temperature": 0.0},
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            outer = json.loads(response.read())
    except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
        raise JudgeUnavailableError(
            f"Could not reach local Ollama judge at {OLLAMA_URL} "
            f"(model={JUDGE_MODEL}). Run `ollama serve` and `ollama pull {JUDGE_MODEL}` "
            f"first. Underlying error: {e}"
        ) from e

    raw = outer.get("response", "")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise JudgeUnavailableError(
            f"Judge returned non-JSON output for secret={secret!r}: {raw!r}"
        ) from e


def judge_clue(secret: str, clue: str, lang: str) -> dict:
    """Call the local LLM judge for one (secret, clue) pair — three calls
    under the hood (see module docstring for why each axis is isolated).

    lang: "en" or "hi-en" — hi-en additionally requests a cultural_fit score.
    Returns {"solvability": int, "spoiler_flag": bool, "difficulty": int,
              "cultural_fit": int | None, "matches": bool}.
    Raises JudgeUnavailableError if Ollama isn't reachable (caller decides
    whether to skip dimension 3 or fail loudly — see run_harness.py).
    """
    is_hien = lang == "hi-en"

    spoiler_parsed = _call_ollama(_SPOILER_PROMPT.format(secret=secret, clue=clue), secret)

    solvability_parsed = _call_ollama(
        _SOLVABILITY_PROMPT.format(secret=secret, clue=clue), secret
    )

    difficulty_prompt = _DIFFICULTY_PROMPT.format(
        secret=secret,
        clue=clue,
        lang_label="Hinglish (romanized Hindi + English)" if is_hien else "English",
        cultural_fit_instruction=_CULTURAL_FIT_INSTRUCTION if is_hien else "",
        cultural_fit_field=', "cultural_fit": <1-5 int>' if is_hien else "",
    )
    difficulty_parsed = _call_ollama(difficulty_prompt, secret)

    return {
        "solvability": int(solvability_parsed["solvability"]),
        "matches": bool(solvability_parsed["matches"]),
        "spoiler_flag": bool(spoiler_parsed["present"]),
        "difficulty": int(difficulty_parsed["difficulty"]),
        "cultural_fit": (
            int(difficulty_parsed["cultural_fit"])
            if is_hien and "cultural_fit" in difficulty_parsed
            else None
        ),
    }


def is_judge_available() -> bool:
    """Quick reachability probe — used to skip/report dimension 3 gracefully."""
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=5) as response:  # noqa: S310
            return response.status == 200
    except Exception:
        return False
