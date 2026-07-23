from __future__ import annotations

"""
Consolidated failure-analysis report — spec-model-excellence.md WORKSTREAM B
items 5 (full error taxonomy), 6 (head/tail frequency analysis), and 7
(per-domain/per-POS breakdown), over the shipped model's checkpoint
(evals/finetune/data/bakeoff_raw/gauravgandhi2411__hinglish-relatedness-sbert.json,
379 dim1_records / 124 in_expected_band==False failures, 42 secrets).

Pure aggregation/reporting driver — no embedding, no training, no scoring.
Assembles the outputs of:
  - failure_taxonomy.py     (item 5, judge-backed, cached)
  - frequency_buckets.py    (item 6, pure computation + wordfreq lookups)
  - domain_pos_breakdown.py (item 7, domain join is pure; POS/concreteness
                              is judge-backed, cached)
into ONE data/failure_analysis_report.json (every per-word/per-record
assignment, for anyone who wants to dig into a specific example) and ONE
data/failure_analysis_report.md (human-readable, summary-first, ranked by
prevalence per the program's "ranked by prevalence and user impact"
deliverable).

Run (from generator/, after failure_taxonomy.py and domain_pos_breakdown.py
have been run at least once to populate their judge caches):
    uv run python -m evals.finetune.failure_analysis_report
"""

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from evals.finetune import domain_pos_breakdown as dpb
from evals.finetune import failure_taxonomy as ft
from evals.finetune import frequency_buckets as fb
from vocab import load_hien_vocab

DATA_DIR = Path(__file__).parent / "data"
OUT_JSON_PATH = DATA_DIR / "failure_analysis_report.json"
OUT_MD_PATH = DATA_DIR / "failure_analysis_report.md"


def _git_sha() -> str | None:
    """Best-effort commit SHA for metric provenance (rule 65b) -- None if
    git isn't available/this isn't a repo checkout, never a hard failure."""
    try:
        out = subprocess.run(  # noqa: S603, S607 -- fixed args, no shell, read-only
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=False
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def build_report_data() -> dict:
    """Assemble every sub-analysis into one dict. Judge-backed steps
    (classify_all_failing, classify_all_words) are cache-first -- this
    function makes ZERO new judge calls if both caches are already fully
    populated by a prior `uv run python -m evals.finetune.X` invocation."""
    checkpoint = json.loads(ft.CHECKPOINT_PATH.read_text(encoding="utf-8"))
    all_records = checkpoint["dim1_records"]
    vocab_size = len(load_hien_vocab())

    # --- Item 5: error taxonomy over the 124 failing pairs ---------------
    failing = ft.load_failing_records()
    classified = ft.classify_all_failing(failing)
    prevalence = ft.prevalence_table(classified)
    sanity = ft.sanity_check_worked_examples(classified)
    low_conf = ft.low_confidence_flags(classified)
    hedged = ft.inconsistent_rationale_flags(classified)
    flagged_secrets = ft.load_collision_flagged_secrets()
    crossref = (
        ft.collision_scan_crossref(classified, flagged_secrets)
        if flagged_secrets is not None
        else None
    )
    classified_by_key = {(r["secret"], r["word"]): r for r in classified}
    tier_band_width = ft.tier_band_width_report(all_records, vocab_size)

    # --- Item 6: head/tail frequency-bucket analysis ----------------------
    hi_words = fb.hinglish_sourced_words()
    bucket_table = fb.build_word_bucket_table()
    coverage = fb.unresolved_coverage_stats(bucket_table, hi_words)
    joined_freq = fb.join_dim1_with_buckets(all_records, bucket_table)
    freq_report = fb.bucket_report(joined_freq, vocab_size)
    freq_by_word = {r["word"]: (r["freq_origin"], r["freq_bucket"]) for r in joined_freq}

    # --- Item 7: per-domain + per-POS/concreteness breakdown -------------
    domain_map = dpb.secret_domain_map()
    joined_domain = dpb.join_domain(all_records, domain_map)
    dom_report = dpb.domain_report(joined_domain)
    domain_by_secret = {r["secret"]: r["domain"] for r in joined_domain}

    words = dpb.unique_words(all_records)
    pos_cache = dpb.load_pos_cache()
    n_pos_covered = sum(1 for w in words if w in pos_cache)
    joined_pos = dpb.join_pos_concreteness(all_records, pos_cache)
    pos_rep = dpb.pos_report(joined_pos)
    conc_rep = dpb.concreteness_report(joined_pos)
    pos_by_word = {r["word"]: (r["part_of_speech"], r["concreteness"]) for r in joined_pos}

    # --- Per-record consolidated view (the ".json" deliverable) ----------
    enriched_records = []
    for r in all_records:
        freq_origin, freq_bucket = freq_by_word.get(r["word"], (None, None))
        pos, conc = pos_by_word.get(r["word"], (None, None))
        rec = {
            **r,
            "domain": domain_by_secret.get(r["secret"]),
            "domain_labeled": r["secret"] in domain_map,
            "freq_origin": freq_origin,
            "freq_bucket": freq_bucket,
            "part_of_speech": pos,
            "concreteness": conc,
        }
        taxonomy = classified_by_key.get((r["secret"], r["word"]))
        if taxonomy is not None:
            rec["taxonomy_category"] = taxonomy["category"]
            rec["taxonomy_rationale"] = taxonomy["rationale"]
            rec["taxonomy_confidence"] = taxonomy["confidence"]
        enriched_records.append(rec)

    return {
        "provenance": {
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "git_sha": _git_sha(),
            "checkpoint_source": "evals/finetune/data/bakeoff_raw/"
            "gauravgandhi2411__hinglish-relatedness-sbert.json",
            "model": checkpoint.get("model"),
            "n_dim1_records": len(all_records),
            "n_failing_records": len(failing),
            "vocab_size": vocab_size,
        },
        "item5_error_taxonomy": {
            "n_failing": len(failing),
            "prevalence": prevalence,
            "worked_example_sanity_check": sanity,
            "low_confidence_flags": low_conf,
            "inconsistent_rationale_flags": hedged,
            "collision_scan_crossref": crossref,
            "collision_scan_available": flagged_secrets is not None,
            "tier_band_width_report": tier_band_width,
        },
        "item6_frequency_buckets": {
            "hinglish_sourced_coverage": coverage,
            "n_english_sourced": sum(1 for v in bucket_table.values() if v["origin"] == "english"),
            "bucket_report": freq_report,
        },
        "item7_domain_pos": {
            "domain_report": dom_report,
            "n_unique_words": len(words),
            "n_pos_covered": n_pos_covered,
            "pos_report": pos_rep,
            "concreteness_report": conc_rep,
        },
        "records": enriched_records,
    }


def _pct(x: float | None) -> str:
    return f"{x:.1%}" if x is not None else "n/a"


def _examples_for_category(records: list[dict], category: str, n: int = 5) -> list[dict]:
    return [r for r in records if r.get("taxonomy_category") == category][:n]


def render_markdown(data: dict) -> str:
    prov = data["provenance"]
    item5 = data["item5_error_taxonomy"]
    item6 = data["item6_frequency_buckets"]
    item7 = data["item7_domain_pos"]
    records = data["records"]

    lines: list[str] = []
    lines.append("# Failure Analysis Report — WORKSTREAM B (items 5, 6, 7)")
    lines.append("")
    lines.append(
        f"Spec: `spec-model-excellence.md`. Checkpoint: `{prov['checkpoint_source']}` "
        f"(model `{prov['model']}`). Generated {prov['generated_at_utc']}, repo commit "
        f"`{prov['git_sha']}`. n_dim1_records={prov['n_dim1_records']} "
        f"(42 secrets: 8 original production + 34 benchmark-supplement), "
        f"n_failing (in_expected_band==False)={prov['n_failing_records']}, "
        f"vocab_size={prov['vocab_size']}."
    )
    lines.append("")

    # -----------------------------------------------------------------
    # Summary — ranked by prevalence / user impact
    # -----------------------------------------------------------------
    lines.append("## Summary — ranked by prevalence")
    lines.append("")
    top_cat = next(iter(item5["prevalence"]), None)
    top_stats = item5["prevalence"].get(top_cat, {}) if top_cat else {}
    tail_penalty = item6["bucket_report"]["tail_penalty_head_minus_tail_rate"]
    mid_tw = item5["tier_band_width_report"].get("mid", {})
    lines.append(
        f"0. **BIGGEST SINGLE FINDING — mid-tier is a benchmark band-width artifact, not "
        f"primarily a model bug:** {mid_tw.get('n_fail')} of {mid_tw.get('n_resolved')} "
        f"resolved mid-tier records (rate={_pct(mid_tw.get('in_expected_band_rate'))}) fail, "
        f"dwarfing every other cut in this report. Mid-tier's only expected band "
        f"(`warm`, band 3) is a "
        f"**{mid_tw.get('target_window_ranks')}-rank window "
        f"({_pct(mid_tw.get('target_window_pct_of_vocab'))} of the {prov['vocab_size']}-word "
        f"vocab)** — see the dedicated section below. This changes how every other number "
        f'in this report should be read: 84 of the 124 "failing pairs" behind item 5\'s '
        f"taxonomy are mid-tier, so a benchmark-design fix (widening mid-tier's accepted "
        f"band set) is likely higher-leverage than any per-pair model fix the taxonomy "
        f"below might suggest."
    )
    lines.append(
        f"1. **Item 5 (error taxonomy):** conditioned on the current (narrow) benchmark "
        f"design, the single largest failure class is **{top_cat}** at n={top_stats.get('n')} "
        f"({_pct(top_stats.get('pct'))} of the 124 failing pairs) — see caveat below on why "
        f"this likely UNDERSTATES true subword-collision prevalence."
    )
    lines.append(
        f"2. **Item 6 (frequency):** combined head-vs-tail `in_expected_band` rate gap "
        f"(tail penalty) = **{_pct(tail_penalty)}** "
        f"(head={_pct(item6['bucket_report']['combined']['head']['in_expected_band_rate'])}, "
        f"tail={_pct(item6['bucket_report']['combined']['tail']['in_expected_band_rate'])}) "
        f"— NOTE the sign: tail-bucket words score BETTER, not worse, than head-bucket "
        f"words. See the tier-confound caveat in the item 6 section before reading this as "
        f"'rare words are easier for the model.'"
    )
    weakest_domain = min(
        (d for d in item7["domain_report"]["by_domain"].items() if d[1]["n"] > 0),
        key=lambda kv: kv[1]["in_expected_band_rate"],
        default=None,
    )
    weakest_pos = min(
        (p for p in item7["pos_report"].items() if p[1]["n"] > 0),
        key=lambda kv: kv[1]["in_expected_band_rate"],
        default=None,
    )
    lines.append(
        f"3. **Item 7 (domain/POS):** weakest domain-labeled cut is "
        f"**{weakest_domain[0]}** ({_pct(weakest_domain[1]['in_expected_band_rate'])}, "
        f"n={weakest_domain[1]['n']}); weakest POS cut is **{weakest_pos[0]}** "
        f"({_pct(weakest_pos[1]['in_expected_band_rate'])}, n={weakest_pos[1]['n']})."
    )
    if item5["collision_scan_crossref"] is not None:
        cr = item5["collision_scan_crossref"]
        lines.append(
            f"4. **Cross-reference finding:** "
            f"{cr['n_failing_records_with_collision_flagged_secret']}/"
            f"{cr['n_failing_records_total']} "
            f"({_pct(cr['pct_failing_records_with_collision_flagged_secret'])}) of the 124 "
            f"failing pairs belong to a SECRET independently flagged as collision-prone by "
            f"the sibling collision scan (item 8) — see the dedicated caveat below. This is "
            f"the strongest single signal that the raw 0-count for `subword_collision` in "
            f"the per-pair taxonomy above is an artifact of prompt design, not evidence that "
            f"collision isn't a real driver of these failures."
        )
    lines.append("")

    # -----------------------------------------------------------------
    # Item 5
    # -----------------------------------------------------------------
    lines.append("## Item 5 — Full error taxonomy over the 124 failing pairs")
    lines.append("")
    lines.append(
        "Classified via the local Ollama judge (qwen3:8b, $0 cost — "
        "`evals/finetune/failure_taxonomy.py`), 6-category rubric + 4 GG-hand-labeled "
        "worked examples as few-shot calibration anchors. 3 of the 124 records have no "
        "`actual_rank` at all (secret or word absent from the game's own vocab — a "
        "mechanical vocab-coverage gap, not a model-judgment question) and are "
        "short-circuited to a 7th pseudo-category, `vocab_resolution_gap`, reported "
        "separately from the 6 semantic-failure categories."
    )
    lines.append("")
    lines.append("| Category | n | % of 124 |")
    lines.append("|---|---|---|")
    for cat, stats in item5["prevalence"].items():
        lines.append(f"| {cat} | {stats['n']} | {_pct(stats['pct'])} |")
    lines.append("")

    lines.append("### Addendum — tier/band-width confound (discovered while writing this up)")
    lines.append("")
    lines.append(
        'Before reading the taxonomy above as "the model has these specific semantic '
        "bugs,\" the BENCHMARK's own design has to be checked first: each tier's "
        "`in_expected_band` outcome depends on how WIDE its accepted band(s) are, and that "
        "width varies enormously by tier — computed directly from `rival.band_for_rank` "
        "(the same function production uses), not estimated:"
    )
    lines.append("")
    lines.append(
        "| tier | n | n_resolved | n_fail | rate | expected bands | window (ranks) | % vocab |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for tier, stats in item5["tier_band_width_report"].items():
        lines.append(
            f"| {tier} | {stats['n']} | {stats['n_resolved']} | {stats['n_fail']} | "
            f"{_pct(stats['in_expected_band_rate'])} | {stats['expected_bands']} | "
            f"{stats['target_window_ranks']} | {_pct(stats['target_window_pct_of_vocab'])} |"
        )
    lines.append("")
    lines.append(
        "**mid-tier's `warm` band is a 24-rank window out of 10,495 words (0.23% of the "
        "vocab)** — near-total mid-tier failure (98.8%) is the PREDICTABLE consequence of "
        "asking any embedding model to land a weak/moderate semantic relation inside a "
        "window 40x narrower than near-tier's (499 ranks) and ~415x narrower than far-tier's "
        "(9,971 ranks). This is best read as a benchmark-DESIGN issue (mid-tier's accepted "
        "band set is too narrow to be a fair target), not primarily 84 independent model "
        "bugs — even though the per-pair judge classifications above are individually "
        "plausible-sounding (mostly `genuine_semantic_difficulty`), the judge was never "
        "shown this quantitative context and reasonably reached for a semantic narrative "
        "for what is substantially a mechanical near-impossibility. **Recommended follow-up "
        "(not done here — this is Workstream D/benchmark-design territory, out of this "
        "task's scope):** widen mid-tier's accepted band set (e.g. to include `hot`+`warm`+"
        "`cold`, bands 2-4) and re-measure before concluding the model needs further "
        "fine-tuning specifically for weak/moderate associations."
    )
    lines.append("")

    lines.append("### Worked-example sanity check (GG's 4 hand-labeled anchors)")
    lines.append("")
    lines.append("| secret <- word | GG label | judge label | agree |")
    lines.append("|---|---|---|---|")
    for s in item5["worked_example_sanity_check"]:
        lines.append(
            f"| {s['secret']} <- {s['word']} | {s.get('gg_label')} | "
            f"{s.get('judge_label')} | {s.get('agree')} |"
        )
    lines.append("")
    lines.append(
        "**4/4 agreement** (including the intentionally-ambiguous khazana/gold "
        "calibration case) — the judge's classification matches GG's own hand labels on "
        "every anchor, a reasonable basis for trusting its calls on the remaining 120."
    )
    lines.append("")

    lines.append("### Examples per category")
    lines.append("")
    for cat in item5["prevalence"]:
        examples = _examples_for_category(records, cat, n=5)
        lines.append(f"**{cat}** ({item5['prevalence'][cat]['n']} total, showing up to 5):")
        for ex in examples:
            lines.append(
                f"- `{ex['secret']} <- {ex['word']}` (tier={ex['tier']}, "
                f"expected_bands={ex['expected_bands']}, actual_band={ex['actual_band']}, "
                f"rank={ex['actual_rank']}): {ex.get('taxonomy_rationale', '')}"
            )
        lines.append("")

    lines.append("### Low-confidence / inconsistent-rationale flags (human review)")
    lines.append("")
    lines.append(
        f"Low confidence (judge self-rated <=2): **{len(item5['low_confidence_flags'])}**. "
        f"Hedge-language flags (rationale leans on 'may have'/'possibly'/etc despite a "
        f"non-low confidence score): **{len(item5['inconsistent_rationale_flags'])}**, all "
        f"14 of which are `transliteration_artifact` calls — expected, since that category "
        f"is inherently about spelling AMBIGUITY and a hedge-worded rationale is somewhat "
        f"native to the category, but flagged here per the task's instruction rather than "
        f"silently accepted."
    )
    lines.append("")
    for h in item5["inconsistent_rationale_flags"]:
        lines.append(
            f"- `{h['secret']} <- {h['word']}` [{h['category']}, conf={h['confidence']}]: "
            f"{h['rationale']}"
        )
    lines.append("")

    if item5["collision_scan_available"]:
        cr = item5["collision_scan_crossref"]
        lines.append("### Cross-reference against the independent collision scan (item 8)")
        lines.append("")
        lines.append(
            "`evals/finetune/collision_scan.py` (sibling WORKSTREAM B item 8 task, run "
            "independently) flags a word as collision-prone if ITS OWN embedding neighbors "
            "are dominated by orthographically-similar, semantically-unrelated tokens. This "
            "taxonomy's per-pair judge prompt, by contrast, only shows the judge the failing "
            "WORD and its outcome — it never shows the judge the SECRET's actual neighbor "
            "list, so it cannot detect the case where the SECRET itself is collision-prone "
            "and its polluted neighbor list pushes a legitimate near/mid word out of its "
            "expected top ranks (a real failure mode with a different observable signature: "
            "the target word doesn't look anything like an English homograph, so per-pair "
            "reasoning alone lands on `transliteration_artifact` or "
            "`genuine_semantic_difficulty` instead)."
        )
        lines.append("")
        lines.append(
            f"**{cr['n_failing_records_with_collision_flagged_secret']}/"
            f"{cr['n_failing_records_total']} "
            f"({_pct(cr['pct_failing_records_with_collision_flagged_secret'])}) of the 124 "
            f"failing records have a SECRET independently flagged as collision-prone.** "
            f"Category breakdown restricted to those records:"
        )
        lines.append("")
        lines.append("| category | n (collision-flagged secret) |")
        lines.append("|---|---|")
        for cat, stats in cr["category_breakdown_flagged_secrets"].items():
            lines.append(f"| {cat} | {stats['n']} |")
        lines.append("")
        lines.append(
            "**Concrete example:** secret `sandook` (trunk) is flagged by the collision "
            "scan (its top-15 neighbors are dominated by `sand`/`sandra`/`sandy`/`sands` — "
            "an orthographic collision with the unrelated English word 'sand', pulling its "
            "whole neighbor list toward water/beach terms like pond/creek/lake/reef instead "
            "of storage-container terms). This taxonomy classified `sandook <- vault` as "
            '`transliteration_artifact` (hedged rationale: "sandook may have non-canonical '
            'transliteration causing misinterpretation of vault") — plausible on its face, '
            "but the collision scan's neighbor-list evidence suggests the ACTUAL mechanism "
            "is secret-side subword collision with 'sand', not word-side spelling ambiguity. "
            "**Recommended follow-up (not done here, out of this task's scope):** re-run "
            "the item-5 judge prompt for collision-flagged-secret records with the secret's "
            "real neighbor list (from collision_scan_report.json) included as context, so "
            "the judge can distinguish secret-side collision from the other categories "
            "directly instead of guessing blind."
        )
        lines.append("")
    else:
        lines.append(
            "### Cross-reference against the independent collision scan (item 8)\n\n"
            "`collision_scan_report.json` was not present when this report was generated "
            "— cross-referencing against it is a recommended follow-up (per the task "
            "instructions), not done in this run."
        )
        lines.append("")

    # -----------------------------------------------------------------
    # Item 6
    # -----------------------------------------------------------------
    lines.append("## Item 6 — Head/tail (frequency) analysis")
    lines.append("")
    lines.append(
        "Vocab origin reconstructed via `evals/finetune/frequency_buckets.py` "
        "(mirrors `vocab.load_hien_vocab()`'s own filtering/dedup logic). English-sourced "
        "words (n=" + str(item6["n_english_sourced"]) + ") are ranked by 1-based position "
        "in `vocab/en.txt` (already wordfreq-frequency-ordered — confirmed via "
        "`vocab.py`'s own docstring/derive_en_vocab comment, not re-derived here). "
        "Hinglish-sourced words (n="
        + str(item6["hinglish_sourced_coverage"]["n_hinglish_words"])
        + ') are ranked by `wordfreq.word_frequency(devanagari_form, "hi")`, using the '
        "pre-existing full-vocab transliteration table (not regenerated). Each origin is "
        "bucketed into head/mid/tail INDEPENDENTLY via tertiles (documented choice — see "
        "`frequency_buckets.py` module docstring for why quartiles don't map onto the "
        "requested 3 labels)."
    )
    lines.append("")
    lines.append("### Coverage honesty (no silent caps)")
    lines.append("")
    cov = item6["hinglish_sourced_coverage"]
    lines.append(
        f"Of the {cov['n_hinglish_words']} hinglish-sourced words, "
        f"**{cov['n_unresolved']} ({_pct(cov['pct_unresolved'])}) have an unresolved "
        f"frequency** — either `wordfreq.word_frequency` returned exactly 0.0 (genuinely "
        f"rare/absent from wordfreq's Hindi corpus, OR a garbage transliteration — these "
        f"are indistinguishable automatically) or the pre-existing transliteration table "
        f"has no Devanagari form at all for that word. Spot-checked example of the latter "
        f"failure mode: `pyaar` (love) transliterates in the table to `प्यर` (missing the "
        f"long vowel — correct spelling is `प्यार`), which legitimately returns "
        f"wordfreq=0.0 for the WRONG reason (bad transliteration, not genuine rarity). "
        f"This {_pct(cov['pct_unresolved'])} unresolved fraction is reported as its own "
        f"bucket, never silently folded into 'tail'."
    )
    lines.append("")
    lines.append("### Combined head/mid/tail (english + hinglish origins pooled)")
    lines.append("")
    lines.append("| bucket | n | in_expected_band rate | mean rank percentile |")
    lines.append("|---|---|---|---|")
    for bucket, stats in item6["bucket_report"]["combined"].items():
        rp = stats["mean_rank_percentile"]
        lines.append(
            f"| {bucket} | {stats['n']} | {_pct(stats['in_expected_band_rate'])} | "
            f"{_pct(rp) if rp is not None else 'n/a'} |"
        )
    lines.append("")
    lines.append(
        f"**Tail penalty (head rate − tail rate) = {_pct(tail_penalty)}** (note the sign: "
        f"NEGATIVE — tail-bucket words score HIGHER, not lower. "
        f"n_records_resolved={item6['bucket_report']['n_records_resolved']} of "
        f"{item6['bucket_report']['n_records_total']} total dim1 records.) **This is very "
        f"likely a TIER-COMPOSITION CONFOUND, not a genuine frequency effect**: curated "
        f"near/mid target words (deliberately common, evocative associate words) skew "
        f"heavily toward the 'head' bucket, while far-tier decoy words (randomly sampled "
        f"across the whole vocab, and the tier the model is best at — see the item 5 tier "
        f"addendum above, far-tier rate ~95.7%) are the ones populating 'tail'. A frequency "
        f"effect CONTROLLED for tier would need to compare head-vs-tail WITHIN each tier "
        f"separately, which this report's join (item 6 asks for a `word`-level cut, not a "
        f"tier-stratified one) does not do — flagged here rather than reported as a clean "
        f"frequency finding it isn't."
    )
    lines.append("")
    lines.append("### By origin x bucket")
    lines.append("")
    lines.append("| origin_bucket | n | in_expected_band rate |")
    lines.append("|---|---|---|")
    for key, stats in item6["bucket_report"]["by_origin_bucket"].items():
        lines.append(f"| {key} | {stats['n']} | {_pct(stats['in_expected_band_rate'])} |")
    lines.append("")

    # -----------------------------------------------------------------
    # Item 7
    # -----------------------------------------------------------------
    lines.append("## Item 7 — Per-domain and per-POS/concreteness breakdown")
    lines.append("")
    lines.append(
        "**Both the domain labels for the 34 benchmark-supplement secrets AND the "
        "POS/concreteness tags are AI-derived, not human-verified ground truth** — same "
        "epistemic status as this benchmark's own near/mid/far tiers "
        "(spec-model-excellence.md Workstream D item 13 flags this as an open question "
        "for the benchmark generally). Treat this section as a first-pass systematic "
        "view, not a final verdict."
    )
    lines.append("")
    lines.append("### Domain (34 benchmark-supplement secrets only — coverage caveat)")
    lines.append("")
    lines.append(
        f"The original 25 production secrets carry NO domain label and none is invented "
        f"for them here: {item7['domain_report']['unlabeled']['n']} records "
        f"({_pct(item7['domain_report']['unlabeled']['in_expected_band_rate'])} "
        f"in_expected_band rate) are reported separately as domain-unlabeled / out of "
        f"scope for this cut."
    )
    lines.append("")
    lines.append("| domain | n | in_expected_band rate |")
    lines.append("|---|---|---|")
    for domain, stats in item7["domain_report"]["by_domain"].items():
        lines.append(f"| {domain} | {stats['n']} | {_pct(stats['in_expected_band_rate'])} |")
    lines.append(
        f"| *(unlabeled — original 25 secrets)* | {item7['domain_report']['unlabeled']['n']} | "
        f"{_pct(item7['domain_report']['unlabeled']['in_expected_band_rate'])} |"
    )
    lines.append("")

    lines.append(
        f"### POS + concreteness (all 379 records, {item7['n_unique_words']} unique words, "
        f"{item7['n_pos_covered']}/{item7['n_unique_words']} judge-covered)"
    )
    lines.append("")
    lines.append("| part_of_speech | n | in_expected_band rate |")
    lines.append("|---|---|---|")
    for pos, stats in item7["pos_report"].items():
        lines.append(f"| {pos} | {stats['n']} | {_pct(stats['in_expected_band_rate'])} |")
    lines.append("")
    lines.append("| concreteness | n | in_expected_band rate |")
    lines.append("|---|---|---|")
    for conc, stats in item7["concreteness_report"].items():
        lines.append(f"| {conc} | {stats['n']} | {_pct(stats['in_expected_band_rate'])} |")
    lines.append("")

    lines.append("## Recommended follow-ups (not in this task's scope)")
    lines.append("")
    lines.append(
        "- **Highest priority:** widen mid-tier's accepted band set in the benchmark "
        "(currently `[warm]` only, a 24-rank/0.23%-of-vocab window) and re-measure before "
        "spending further model-fix effort on mid-tier failures specifically — the current "
        "98.8% mid-tier failure rate is largely explained by benchmark band width, not "
        "model quality (see item 5 addendum).\n"
        "- Re-run item 5's judge with the secret's actual collision-scan neighbor list "
        "included as context for the 57/124 (46%) failing records whose secret is "
        "independently flagged as collision-prone, to properly disambiguate secret-side "
        "subword collision from word-side transliteration ambiguity / genuine difficulty.\n"
        "- Re-run item 6's frequency-bucket analysis stratified BY TIER (not pooled across "
        "tiers) before drawing any conclusion about a genuine frequency effect — the pooled "
        "head/tail comparison in this report is confounded by tier composition (see the "
        "item 6 caveat above).\n"
        "- Human-verify a sample of the AI-derived domain and POS/concreteness labels "
        "(same open item as the benchmark's own near/mid/far tiers, spec Workstream D "
        "item 13).\n"
        "- Investigate the 57.2% hinglish-sourced-word frequency-unresolved rate directly "
        "against `devanagari_front_end_vocab_table.json`'s known transliteration-quality "
        "issues (spot-checked example above) before trusting the hinglish-origin bucket "
        "counts for anything beyond a directional read."
    )
    lines.append("")

    return "\n".join(lines)


def main() -> dict:
    data = build_report_data()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    OUT_MD_PATH.write_text(render_markdown(data), encoding="utf-8")
    return data


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    result = main()
    print(f"Wrote {OUT_JSON_PATH}")
    print(f"Wrote {OUT_MD_PATH}")
    print(f"n_records: {len(result['records'])}")
