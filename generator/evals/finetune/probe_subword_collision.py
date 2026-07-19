from __future__ import annotations

"""
Cheap probe: does a SMALL, TARGETED batch of new hard-negative training data
move the needle on the "subword-tokenization-collision" failure class found
in the Phase 1 public-benchmark report's v1.1 addendum (junoon/registan/
jheel/udaasi -- their own nearest neighbors are dominated by unrelated
English words sharing a coincidental subword fragment, e.g.
junoon->afternoon/noon/june, registan->register/registry/registration)?

junoon/registan/jheel/udaasi themselves are FROZEN public-benchmark secrets
and must never be trained on (no-leakage). This probe instead:

  1. Finds 9 OTHER short/rare hi-en vocab words showing the SAME collision
     signature (own gloss ranks poorly; top nearest neighbors are dominated
     by unrelated English words/proper nouns sharing a coincidental letter
     fragment) -- verified programmatically to be clean of the 60 daily-
     schedule secrets, every pack secret, and the 34 public-benchmark
     secrets (see `_EXCLUDE_SET()`).
  2. A load-bearing finding, checked not assumed (see `check_existing_coverage`
     below): every one of these 9 words ALREADY has (a) an explicit positive
     pair in train_graded_pairs.jsonl/train_mnrl_pairs.jsonl (source=
     "crosslingual", score 0.9) and (b) an explicit MINED hard negative in
     train_mnrl_pairs_hard_neg.jsonl (the file the SHIPPED model's winning
     "obj_hard_neg" recipe actually trained on) -- mined at rank-band 50-500
     under the OFF-THE-SHELF (pre-fine-tune) model, per hard_negatives.py.
     Despite this, the SHIPPED (post-fine-tune) model still buries each
     word's own correct gloss at rank 300-4000+ out of ~10.5k words, with
     its own top neighbors dominated by a DIFFERENT set of collision words
     than the ones originally mined. This means the probe's real, novel
     contribution is NOT "add a first hard negative" (already done, and
     insufficient) -- it's a SECOND round of hard-negative mining, targeted
     at the SHIPPED model's own CURRENT top confusions (an iterative /
     second-round hard-negative-mining probe), which is a materially
     different and more informative experiment than originally scoped.
  3. Trains a probe checkpoint with the winning obj_hard_neg recipe (LoRA
     r=8/alpha=16/lr=2e-4/4 epochs, `evals/finetune/checkpoints/obj_hard_neg/`)
     PLUS these 9 new second-round hard-negative pairs, added in-memory to
     the exact base training set obj_hard_neg used (train_mnrl_pairs_hard_neg
     .jsonl + train_graded_pairs.jsonl) -- not the plain train_mnrl_pairs
     .jsonl, since that has zero hard negatives and would silently change
     the baseline recipe, confounding the probe (see module docstring's
     "load-bearing finding" above; the task brief named train_mnrl_pairs
     .jsonl as shorthand for "the current training data", but the
     apples-to-apples base for a valid ablation is the file the SHIPPED
     model actually trained on).
  4. Evaluates on the frozen public benchmark
     (data/public_benchmark_staging/dim1_hien.json + dim2_pairs.json) with
     the same _resolve_actuals/dim2_for_pairs/bootstrap_ci machinery used
     everywhere else in this project, paired against the shipped model's
     already-computed bakeoff_raw checkpoint (no re-embedding of the shipped
     model).

Run (from generator/):
    uv run python -m evals.finetune.probe_subword_collision --train
    uv run python -m evals.finetune.probe_subword_collision --eval
"""

import argparse
import json
from pathlib import Path

from build_packs import aliases_for_secret
from evals.finetune.bootstrap_ci import (
    bootstrap_dim1_spearman_ci,
    bootstrap_dim2_pass_rate_ci,
    paired_bootstrap_dim1_delta,
    paired_bootstrap_dim2_delta,
)
from evals.finetune.eval_model import _model_override, dim2_for_pairs
from evals.finetune.train_lib import TrainConfig, run_training
from evals.harness.dimension1_ranking import _band_accuracy, _resolve_actuals
from packs import load_pack_secrets, load_packs_meta
from schedule import load_schedule
from vocab import load_hien_vocab

DATA_DIR = Path(__file__).parent / "data"
STAGING_DIR = DATA_DIR / "public_benchmark_staging"
BAKEOFF_RAW_DIR = DATA_DIR / "bakeoff_raw"
RUN_NAME = "probe_subword_collision"

SHIPPED_MODEL = "gauravgandhi2411/hinglish-relatedness-sbert"

# The 34 public-benchmark secrets (spec-hinglish-benchmark.md Phase 1),
# copied verbatim from the task brief / public_benchmark_phase1_report.md
# section 1 -- checked programmatically below, never eyeballed.
PUBLIC_BENCHMARK_34_SECRETS: frozenset[str] = frozenset(
    {
        "registan",
        "jheel",
        "chattan",
        "dhoop",
        "patta",
        "sharm",
        "chinta",
        "mazaa",
        "junoon",
        "udaasi",
        "azaadi",
        "insaaf",
        "waqt",
        "sawaal",
        "kanoon",
        "chaabi",
        "sandook",
        "thaali",
        "tokri",
        "chimni",
        "sadak",
        "sarhad",
        "basti",
        "mohalla",
        "dehat",
        "mithai",
        "dahi",
        "paneer",
        "besan",
        "khichdi",
        "mausi",
        "bhanja",
        "bhanji",
        "judwaa",
    }
)

# The 4 words this probe cares about moving, specifically -- from the phase1
# report's v1.1 addendum ("Root cause of the emotion/nature residual").
TARGET_WORDS: tuple[str, ...] = ("junoon", "registan", "jheel", "udaasi")

# ---------------------------------------------------------------------------
# Step 1/2: probe candidates -- found by inspecting each word's own top-15
# nearest neighbors under the SHIPPED model's full hi-en vocab embedding
# (config.MODELS["hi-en"] default, the same default embed_vocab() call used
# everywhere else in this project), looking for the junoon/registan
# signature: correct gloss ranks poorly (buried far outside the vocab's
# top ~1%), and the top neighbors are dominated by unrelated English
# words/proper nouns sharing a coincidental letter fragment, not genuine
# synonyms/associates.
#
# evidence: (word, correct_gloss, gloss_rank_under_shipped_model,
#            top_10_neighbors_under_shipped_model)
# hard_negative: the single most clearly unrelated, collision-driven
# neighbor from that list, chosen the same way hard_negatives.py picks a
# "genuinely confusable" negative -- excludes anything in the no-leakage
# exclude set (see _EXCLUDE_SET) and anything that is itself a real
# semantic associate (e.g. "darwaza"/door IS excluded in favour of a purer
# collision case where possible; here it was the clearest single offender
# so it is kept, exactly like junoon's own "afternoon" example is a
# coincidental subword collision, not a synonym).
PROBE_CANDIDATES: list[dict] = [
    {
        "word": "daraa",
        "gloss": "scared",
        "gloss_rank": 4121,
        "neighbors": [
            "darren",
            "darwin",
            "door",
            "darpan",
            "darling",
            "darwaza",
            "doors",
            "corridor",
            "deewar",
        ],
        "hard_negative": "darwaza",
    },
    {
        "word": "accha",
        "gloss": "good",
        "gloss_rank": 3532,
        "neighbors": [
            "chachi",
            "ace",
            "chacha",
            "bachcha",
            "chick",
            "bachpan",
            "pocha",
            "ac",
            "adams",
            "angocha",
        ],
        "hard_negative": "adams",
    },
    {
        "word": "angocha",
        "gloss": "towel",
        "gloss_rank": 1329,
        "neighbors": [
            "angoor",
            "pocha",
            "bagicha",
            "angoothi",
            "accha",
            "angutha",
            "congo",
            "ncaa",
            "honda",
            "anal",
        ],
        "hard_negative": "congo",
    },
    {
        "word": "naukri",
        "gloss": "job",
        "gloss_rank": 1271,
        "neighbors": [
            "tokri",
            "nauka",
            "norfolk",
            "nariyal",
            "nau",
            "bruce",
            "kheer",
            "nascar",
            "barber",
            "coconut",
        ],
        "hard_negative": "norfolk",
    },
    {
        "word": "sharbat",
        "gloss": "juice",
        "gloss_rank": 1237,
        "neighbors": [
            "sharm",
            "sharon",
            "salwar",
            "sharminda",
            "sherman",
            "turban",
            "syria",
            "kurt",
            "shirt",
            "shirts",
        ],
        "hard_negative": "turban",
    },
    {
        "word": "seedha",
        "gloss": "straight",
        "gloss_rank": 392,
        "neighbors": [
            "seed",
            "seedi",
            "seeds",
            "root",
            "ruth",
            "stem",
            "rooted",
            "roots",
            "plant",
            "stems",
        ],
        "hard_negative": "seed",
    },
    {
        "word": "seena",
        "gloss": "chest",
        "gloss_rank": 341,
        "neighbors": [
            "sees",
            "see",
            "seeing",
            "sight",
            "looking",
            "viewed",
            "glance",
            "lookin",
            "looks",
            "look",
        ],
        "hard_negative": "seeing",
    },
    {
        "word": "halwa",
        "gloss": "sweet",
        "gloss_rank": 272,
        "neighbors": [
            "haldi",
            "tawa",
            "chawal",
            "milwaukee",
            "lightly",
            "lazy",
            "halloween",
            "slim",
            "mild",
            "lahsun",
        ],
        "hard_negative": "halloween",
    },
    {
        "word": "chashma",
        "gloss": "glasses",
        "gloss_rank": 368,
        "neighbors": [
            "chamcha",
            "chai",
            "kamar",
            "champ",
            "ash",
            "gum",
            "tea",
            "cough",
            "powder",
            "champagne",
        ],
        "hard_negative": "champagne",
    },
]


# ---------------------------------------------------------------------------
# No-leakage verification (step 1's CRITICAL constraint) -- reuses
# scrub_public_benchmark.collect_live_items()'s exact live-content
# collection (all 60 daily-schedule secrets both langs + every pack secret
# every pack x lang + every alias), plus an explicit check against the 34
# public-benchmark secrets, which collect_live_items() does not cover since
# it is a different content category (published benchmark, not live game
# content).
# ---------------------------------------------------------------------------


def build_exclude_set() -> frozenset[str]:
    """Full no-fly list for probe-candidate words: every daily-schedule
    secret (both langs), every pack secret (every pack x lang), every
    alias of any of the above, and the 34 public-benchmark secrets."""
    live: set[str] = set()
    for lang in ("en", "hi-en"):
        for secret in load_schedule(lang):
            live.add(secret.lower())
            for alias in aliases_for_secret(secret, lang):
                live.add(alias.lower())
    for pack in load_packs_meta():
        for lang in pack.langs:
            for secret in load_pack_secrets(pack, lang):
                live.add(secret.lower())
                for alias in aliases_for_secret(secret, lang):
                    live.add(alias.lower())
    return frozenset(live | {w.lower() for w in PUBLIC_BENCHMARK_34_SECRETS})


def verify_no_leakage(candidates: list[dict]) -> dict:
    """Verify every candidate word/gloss/hard_negative is clean of the full
    exclude set AND present in the hi-en vocab. Raises AssertionError with
    the offending word(s) on any hit -- never silently skips a leak."""
    exclude = build_exclude_set()
    vocab = set(load_hien_vocab())
    problems: list[str] = []
    for c in candidates:
        for field in ("word", "gloss", "hard_negative"):
            val = c[field].lower()
            if val in exclude:
                problems.append(f"{c['word']}: field {field!r}={val!r} is in the exclude set")
            if val not in vocab:
                problems.append(f"{c['word']}: field {field!r}={val!r} is NOT in hi-en vocab")
    if problems:
        raise AssertionError("no-leakage / vocab check FAILED:\n" + "\n".join(problems))
    return {
        "n_candidates": len(candidates),
        "n_exclude_set": len(exclude),
        "passed": True,
    }


def check_existing_coverage(candidates: list[dict]) -> dict:
    """Load-bearing finding (see module docstring point 2): checks whether
    each candidate word already has a positive pair and/or a mined hard
    negative in the EXISTING on-disk training files, so the probe's
    contribution is reported honestly as incremental (a 2nd hard-negative
    round), not as a naive "first hard negative ever added" claim. Read-only
    -- does not mutate any file."""
    mnrl = _load_jsonl(DATA_DIR / "train_mnrl_pairs.jsonl")
    mnrl_hard_neg = _load_jsonl(DATA_DIR / "train_mnrl_pairs_hard_neg.jsonl")

    report = {}
    for c in candidates:
        w = c["word"]
        existing_positive = [r for r in mnrl if r["anchor"] == w and "negative" not in r]
        existing_hard_neg = [r for r in mnrl_hard_neg if r["anchor"] == w and "negative" in r]
        report[w] = {
            "existing_positive_pairs": existing_positive,
            "existing_mined_hard_negatives": [r["negative"] for r in existing_hard_neg],
        }
    return report


# ---------------------------------------------------------------------------
# Step 2/3: build the new probe records, extend the EXISTING obj_hard_neg
# base training set in-memory (never touching the on-disk files).
# ---------------------------------------------------------------------------


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def build_probe_records(candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (new_mnrl_records, new_graded_records) -- NEW rows only, not
    including anything already on disk. One MNRL triplet per candidate
    (anchor/positive/negative, positive reused verbatim from the existing
    crosslingual pair, negative = the newly-identified 2nd-round collision
    word) + one graded far-score row pinning the new hard negative down
    (the existing positive graded row, score 0.9, is already on disk and is
    NOT re-added -- see check_existing_coverage)."""
    new_mnrl = [
        {
            "anchor": c["word"],
            "positive": c["gloss"],
            "negative": c["hard_negative"],
            "source": RUN_NAME,
        }
        for c in candidates
    ]
    new_graded = [
        {
            "sentence1": c["word"],
            "sentence2": c["hard_negative"],
            "score": 0.05,
            "source": RUN_NAME,
        }
        for c in candidates
    ]
    return new_mnrl, new_graded


def build_extended_training_set(candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    """The obj_hard_neg base training set (train_mnrl_pairs_hard_neg.jsonl +
    train_graded_pairs.jsonl -- the exact files the SHIPPED model trained
    on, see module docstring point 3) extended in-memory with this probe's
    new records. Never writes to disk."""
    base_mnrl = _load_jsonl(DATA_DIR / "train_mnrl_pairs_hard_neg.jsonl")
    base_graded = _load_jsonl(DATA_DIR / "train_graded_pairs.jsonl")
    new_mnrl, new_graded = build_probe_records(candidates)
    return base_mnrl + new_mnrl, base_graded + new_graded


# ---------------------------------------------------------------------------
# Step 3: train, matching the winning obj_hard_neg recipe exactly (LoRA r=8/
# alpha=16/lr=2e-4/4 epochs/early_stopping_patience=2 -- WINNER_KWARGS in
# step1b_objective_sweep.py; every other field is a TrainConfig default that
# already matches, per data/runs/obj_hard_neg.train_summary.json).
# ---------------------------------------------------------------------------


def train_probe() -> dict:
    leak_check = verify_no_leakage(PROBE_CANDIDATES)
    print(f"no-leakage check: {leak_check}")

    extended_mnrl, extended_graded = build_extended_training_set(PROBE_CANDIDATES)
    print(
        f"extended training set: {len(extended_mnrl)} mnrl "
        f"(base {len(extended_mnrl) - len(PROBE_CANDIDATES)} + "
        f"{len(PROBE_CANDIDATES)} new), {len(extended_graded)} graded "
        f"(base {len(extended_graded) - len(PROBE_CANDIDATES)} + "
        f"{len(PROBE_CANDIDATES)} new)"
    )

    cfg = TrainConfig(
        name=RUN_NAME,
        method="lora",
        lora_r=8,
        lora_alpha=16,
        learning_rate=2e-4,
        num_epochs=4,
        early_stopping_patience=2,
        mnrl_records=extended_mnrl,
        graded_records=extended_graded,
    )
    summary = run_training(cfg)
    print(json.dumps({k: v for k, v in summary.items() if k != "dev_curve"}, indent=2))
    return summary


# ---------------------------------------------------------------------------
# Step 4: evaluate the probe checkpoint on the frozen public 34-secret
# benchmark, paired against the shipped model's already-computed bakeoff_raw
# checkpoint (no re-embedding of the shipped model).
# ---------------------------------------------------------------------------


def _public_benchmark_dim1_records(model_name_or_path: str) -> list[dict]:
    scenarios = json.loads((STAGING_DIR / "dim1_hien.json").read_text(encoding="utf-8"))
    with _model_override(model_name_or_path):
        return _resolve_actuals(scenarios, "hi-en")


def _public_benchmark_dim2_result(model_name_or_path: str) -> dict:
    pairs_raw = json.loads((STAGING_DIR / "dim2_pairs.json").read_text(encoding="utf-8"))
    pairs = [(r["en_gloss"], r["hien_secret"]) for r in pairs_raw]
    with _model_override(model_name_or_path):
        return dim2_for_pairs(pairs)


def _shipped_model_dim1_records_34() -> list[dict]:
    """Filter the shipped model's already-computed bakeoff_raw checkpoint
    (42-secret combined production+supplement set) down to just the 34
    public-benchmark secrets, so the paired comparison uses the SAME
    secret set as the probe model -- no re-embedding of the shipped model.
    """
    checkpoint = json.loads(
        (BAKEOFF_RAW_DIR / "gauravgandhi2411__hinglish-relatedness-sbert.json").read_text(
            encoding="utf-8"
        )
    )
    return [r for r in checkpoint["dim1_records"] if r["secret"] in PUBLIC_BENCHMARK_34_SECRETS]


def _shipped_model_dim2_records_34() -> list[dict]:
    """Filter the shipped model's bakeoff_raw dim2_records down to the 34
    public-benchmark secrets. NOTE (honest caveat, checked not assumed):
    bakeoff_raw's dim2_records were computed against
    evals.gen_dim1_benchmark_supplement.BENCHMARK_SUPPLEMENT_PAIRS, which
    still has besan's PRE-v1.1-fix gloss "gram" -- the public benchmark's
    published dim2_pairs.json has the FIXED gloss "flour" (see
    public_benchmark_phase1_report.md's v1.1 addendum). This one-pair
    mismatch is a pre-existing artifact of this repo's history, not
    introduced here; paired_bootstrap_dim2_delta's dict-key intersection
    naturally drops the mismatched pair from the paired n (33/34 instead of
    34/34) rather than crashing or silently misaligning -- verified below,
    reported explicitly, not swept under the rug.
    """
    checkpoint = json.loads(
        (BAKEOFF_RAW_DIR / "gauravgandhi2411__hinglish-relatedness-sbert.json").read_text(
            encoding="utf-8"
        )
    )
    return [
        r for r in checkpoint["dim2_records"] if r["hien_secret"] in PUBLIC_BENCHMARK_34_SECRETS
    ]


def _target_word_summary(dim1_records: list[dict], dim2_records: list[dict]) -> dict:
    """Per-target-word (junoon/registan/jheel/udaasi) dim1 (all scenario
    rows for that secret) + dim2 (the one cross-lingual pair) rank/band
    detail, for the specific "did it move" question."""
    out = {}
    for w in TARGET_WORDS:
        dim1_rows = [r for r in dim1_records if r["secret"] == w]
        dim2_rows = [r for r in dim2_records if r["hien_secret"] == w]
        out[w] = {
            "dim1_rows": dim1_rows,
            "dim2_row": dim2_rows[0] if dim2_rows else None,
        }
    return out


def evaluate_probe(model_path: str | None = None) -> dict:
    """Full step-4 evaluation: probe model's dim1/dim2 on the public 34-
    secret benchmark, paired bootstrap deltas vs the shipped model, target-
    word-specific before/after, and a regression-floor check (any of the 34
    that were passing before and now fail)."""
    if model_path is None:
        summary_path = DATA_DIR / "runs" / f"{RUN_NAME}.train_summary.json"
        model_path = json.loads(summary_path.read_text(encoding="utf-8"))["output_dir"]

    probe_dim1 = _public_benchmark_dim1_records(model_path)
    probe_dim2 = _public_benchmark_dim2_result(model_path)

    shipped_dim1 = _shipped_model_dim1_records_34()
    shipped_dim2 = _shipped_model_dim2_records_34()

    probe_dim1_ci = bootstrap_dim1_spearman_ci(probe_dim1)
    probe_dim2_ci = bootstrap_dim2_pass_rate_ci(probe_dim2["records"])
    shipped_dim1_ci = bootstrap_dim1_spearman_ci(shipped_dim1)
    shipped_dim2_ci = bootstrap_dim2_pass_rate_ci(shipped_dim2)

    dim1_delta = paired_bootstrap_dim1_delta(shipped_dim1, probe_dim1)
    dim2_delta = paired_bootstrap_dim2_delta(shipped_dim2, probe_dim2["records"])

    by_tier = {t: [r for r in probe_dim1 if r["tier"] == t] for t in ("near", "mid", "far")}
    probe_band_accuracy = {
        "overall": _band_accuracy(probe_dim1),
        "near": _band_accuracy(by_tier["near"]),
        "mid": _band_accuracy(by_tier["mid"]),
        "far": _band_accuracy(by_tier["far"]),
    }

    # Zero-net-regression check: any of the 34 secrets' dim2 pair that was
    # PASSING (consistent=True) under the shipped model and is now FAILING
    # under the probe model (matched by hien_secret, since besan's en_gloss
    # differs -- see _shipped_model_dim2_records_34's docstring).
    shipped_pass = {r["hien_secret"]: r["consistent"] for r in shipped_dim2}
    probe_pass = {r["hien_secret"]: r["consistent"] for r in probe_dim2["records"]}
    common_secrets = sorted(set(shipped_pass) & set(probe_pass))
    newly_broken = [
        s for s in common_secrets if shipped_pass[s] is True and probe_pass[s] is not True
    ]
    newly_fixed = [
        s for s in common_secrets if shipped_pass[s] is not True and probe_pass[s] is True
    ]

    target_before = _target_word_summary(shipped_dim1, shipped_dim2)
    target_after = _target_word_summary(probe_dim1, probe_dim2["records"])

    result = {
        "model_path": model_path,
        "n_dim1_secrets": len({r["secret"] for r in probe_dim1}),
        "n_dim1_scenarios": len(probe_dim1),
        "n_dim2_pairs": len(probe_dim2["records"]),
        "probe_dim1_spearman_ci": probe_dim1_ci,
        "probe_dim2_pass_rate_ci": probe_dim2_ci,
        "shipped_dim1_spearman_ci": shipped_dim1_ci,
        "shipped_dim2_pass_rate_ci": shipped_dim2_ci,
        "probe_band_accuracy": probe_band_accuracy,
        "dim1_delta_vs_shipped": dim1_delta,
        "dim2_delta_vs_shipped": dim2_delta,
        "dim2_regression_floor": {
            "n_common_secrets": len(common_secrets),
            "n_newly_broken": len(newly_broken),
            "newly_broken": newly_broken,
            "n_newly_fixed": len(newly_fixed),
            "newly_fixed": newly_fixed,
        },
        "target_words_before_shipped": target_before,
        "target_words_after_probe": target_after,
    }
    out_path = DATA_DIR / f"{RUN_NAME}.eval_result.json"
    out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", action="store_true", help="run the probe fine-tune")
    parser.add_argument("--eval", action="store_true", help="evaluate the trained probe checkpoint")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="only run no-leakage + existing-coverage checks, no training/eval",
    )
    args = parser.parse_args()

    if args.check_only or not (args.train or args.eval):
        print(json.dumps(verify_no_leakage(PROBE_CANDIDATES), indent=2))
        print(json.dumps(check_existing_coverage(PROBE_CANDIDATES), indent=2))
        return

    if args.train:
        train_probe()
    if args.eval:
        evaluate_probe()


if __name__ == "__main__":
    main()
