# Warmer — Fix the Hinglish Semantic Engine (eval-gated bake-off)

## The problem (from the eval harness baseline)
The hi-en semantic engine scores ~random: Spearman **-0.003**, cross-language consistency 5.1% (indistinguishable from random), monotonicity violations 53.7%, translation-tier accuracy 0.0%. The English engine is fine (Spearman 0.837). Hinglish is the India-first wedge — this is a foundational break, not polish. Cannot launch Hinglish as-is.

## Root cause (confirmed hypothesis — verify in step 1)
`paraphrase-multilingual-MiniLM-L12-v2` was trained on Hindi in **Devanagari** script, not Latin-script romanized Hindi. Fed romanized Hindi ("baarish", "jeet"), it doesn't register the tokens as Hindi and embeds them near Latin-script lookalikes in other languages (observed: dil→Turkish, dua→Italian, milan→city). Result: embeddings cluster by surface form, not Hindi meaning. The 0.0% translation tier is the tell — the model can't align "jeet" with "victory" because it never sees "jeet" as Hindi.

## Constraints
- **Embedding is OFFLINE (generator, precomputed ranks).** So a heavier/better model is fine — it runs once at build time, zero runtime cost, no API key. Do NOT pick a model for on-device speed here; pick for quality.
- Note for later: the deferred "any-word guessing" feature would need an on-device model; whatever wins here, note whether a browser-runnable version exists, but do NOT let that constrain this fix.
- The existing alias/normalization layer stays (it handles romanized spelling variance).
- $0, local/open models only, no ANTHROPIC_API_KEY.
- English engine is untouched — this fix is hi-en only.

## Step 1 — Confirm root cause (quick, before building)
- Take ~15 known-fail hi-en pairs from the eval. For a sample, embed the romanized form vs the Devanagari transliteration vs the English translation with the current model; show that Devanagari aligns with the English translation while romanized does not. This confirms the OOD hypothesis empirically and validates Path A's premise. Report the comparison.

## Step 2 — Eval-gated model bake-off
Evaluate each candidate approach by regenerating hi-en ranks with it and running eval-harness dimensions 1 & 2 (band-accuracy, Spearman, monotonicity, cross-language consistency, with the translation/in-language near-tier split). The harness is the judge — no hand-waving.

Candidate approaches (evaluate all that are feasible; add others if found on HuggingFace):
- **A. Transliterate → Devanagari + current multilingual model.** Romanized hi-en → Devanagari via an Indic transliteration lib (indic-transliteration / ai4bharat IndicXlit), then embed with paraphrase-multilingual-MiniLM (or a stronger multilingual model, e.g. a multilingual-e5 / BGE-M3). Needs a language-ID / routing step so code-mixed ENGLISH tokens (hero, police, dialogue) stay English and are NOT transliterated. Reuse the alias layer for spelling variants.
- **B. L3Cube HingBERT family (native romanized code-mixed).** HingBERT / HingRoBERTa / HingMBERT (prefer the MIXED-SCRIPT variant — handles roman + Devanagari + English natively, no routing needed). BERT → mean-pool token embeddings for sentence vectors, or use an SBERT/sentence variant if available. This is the strongest single-model candidate.
- **C. MuRIL** (google/muril-base-cased — trained with transliterated Indic data), mean-pooled. Secondary candidate.
- **D. Optional:** a strong general multilingual model (BGE-M3, multilingual-e5-large) on romanized input directly, as a baseline to confirm they also fail (or surprise us).

For each: report the harness metrics. **Selection gate:** pick the approach with the best hi-en Spearman + cross-language consistency. Minimum viable = Spearman ≥ 0.5 and cross-language pass ≥ 40% (vs current ~0 and 5%); target = approach the EN engine's quality (0.8+). If NO approach clears minimum viable, surface that — it's a strategic finding (Hinglish may need a fine-tuned/custom model), not a silent ship.

## Step 3 — Ship the winner
- Regenerate ALL hi-en payloads (daily + Bollywood + Cricket packs) with the winning embedding approach. Byte-reproducible, size gates, spoiler gates all still pass.
- Re-run the FULL eval harness; commit an updated baseline report showing the before/after hi-en numbers.
- The app consumes the improved ranks with no code change (same payload schema) — but verify live that hi-en play now gives sensible hot/cold (a known-close guess should read Hot, not random).
- Update the known-limitations ledger: Hinglish moved from "broken" to its new measured state.

## Acceptance criteria
1. Root cause confirmed empirically (step 1 comparison reported).
2. Bake-off run: each candidate's harness metrics reported side by side (Spearman, band-accuracy, cross-language, monotonicity, near-tier split).
3. Winner clears minimum viable (Spearman ≥ 0.5, cross-language ≥ 40%) — or, if none does, that's reported as a strategic finding with a recommendation (fine-tune path).
4. hi-en payloads (daily + both packs) regenerated with the winner; all gates pass; byte-reproducible.
5. Updated baseline eval report committed showing before/after hi-en improvement.
6. Live verify on playwarmer.vercel.app: a Hinglish puzzle gives sensible hot/cold — a known-close guess reads Hot/Scorching, a far guess reads Cold (spot-check 3-4 puzzles).
7. English engine provably unchanged (its metrics identical); all tests green.

## Risks
- **Transliteration ambiguity / routing** (Path A): romanized→Devanagari is many-to-one and needs language-ID for code-mixed English; get this wrong and English words get mangled. Path B (native model) avoids it — that's a point in B's favor if quality is comparable.
- **Sentence-embedding quality from a raw BERT** (Paths B/C): mean-pooling a masked-LM isn't always great for similarity; an SBERT/fine-tuned variant is better if available. Report which pooling was used.
- **None clears the bar:** possible the off-the-shelf options aren't enough and a fine-tune on Hinglish similarity pairs is needed. If so, that's the next spec — but the bake-off must establish it, not assume it.
- **Model licensing** — confirm candidates are open/permissively licensed for a commercial product.
