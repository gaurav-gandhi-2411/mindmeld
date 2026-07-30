# LLM-consensus label ceiling -- spec-metrics-ceiling-calibration.md WORKSTREAM 2

## FINAL STATUS: BLOCKED -- no consensus ceiling established

**This is an LLM-CONSENSUS ceiling attempt, NOT a human-annotated ceiling. Per GG's standing policy (spec-metrics-ceiling-calibration.md), manual labeling is never used -- the protocol requires two different-family LLM judges, blind, self-consistency-sampled, and BOTH must clear a mandatory calibration gate on unambiguous control items before any consensus label is trusted. This run could not clear that gate: see the FINAL FINDING below.**

Two independent candidate second judges were tried against the same qwen3:8b first judge; both failed the mandatory 90% calibration bar on far-tier control items. Per GG's explicit instruction, this is the FINAL finding for this workstream -- no third model was tried, the bar was not loosened, and no re-run at a different temperature was used to result-shop a pass (that is explicitly forbidden).

## Side-by-side control accuracy (all three judges tried)

| judge | model family | overall | near-control | far-control | n | bar | pass |
|---|---|---|---|---|---|---|---|
| qwen3:8b | Alibaba/Qwen | 96.7% | 100.0% | 93.3% | 30 | 90% | PASS |
| llama3.1:8b | Meta/Llama | 83.3% | 100.0% | 66.7% | 30 | 90% | FAIL |
| gemma2:9b | Google/Gemma | 86.7% | 100.0% | 73.3% | 30 | 90% | FAIL |

## Attempt 1 -- original pair (qwen3:8b + llama3.1:8b)

qwen3:8b PASSED (96.7%). llama3.1:8b FAILED (83.3%, far-tier 66.7% -- below the 90% bar).

Infra: 2026-07 (prior GCP session, g2-standard-8 + 1x NVIDIA L4, asia-south1-c, aetherart-497918, ~184.3s protocol wall-clock, ~$0.16).

## Attempt 2 -- replacement second-family judge (gemma2:9b)

gemma2:9b (Google, a genuinely different lineage from both qwen3/Alibaba and llama3.1/Meta) was pulled first per plan and ran successfully -- the mistral:7b fallback was never needed.

gemma2:9b FAILED (86.7%, far-tier 73.3% -- below the 90% bar). STOP condition reached per GG's exact instruction: no third model tried.

Infra: 2026-07-25, same GCP infra pattern (g2-standard-8 + 1x NVIDIA L4, asia-south1-c, aetherart-497918).

## Failure mode (reproducible, not noise)

Both failing judges share the SAME specific error pattern: over-predicting relatedness on unambiguous, domain-disjoint FAR-tier control pairs by labelling them 'mid' instead of 'far'. Near-tier (synonym) control accuracy was 100% for every judge tested -- the failure is confined to the far tier, not a general judging-quality problem.

- llama3.1:8b missed 5/30: registan/platter, mazaa/duration, tokri/law, junoon/auntie, bhanji/trunk (all 'mid' instead of 'far').
- gemma2:9b missed 4/30: dehat/yogurt, registan/platter, mazaa/duration, junoon/auntie (all 'mid' instead of 'far').
- **registan/platter and mazaa/duration fail for BOTH models** -- evidence these two specific control items are genuinely harder (or borderline) rather than random per-model noise, though both remain correctly labelled 'far' by construction (domain-disjoint hash-random fillers).

## Conclusion

The LLM-consensus label ceiling (spec-metrics-ceiling-calibration.md WORKSTREAM 2) CANNOT currently be established with locally-available ~7-9B instruction-tuned models. Two independent candidate second judges from two different model families (Meta/llama3.1:8b, Google/gemma2:9b) were tried against the SAME qwen3:8b first judge and BOTH failed the mandatory 90% calibration bar, with the SAME specific, reproducible failure mode: over-prediction of relatedness -- labelling unambiguous domain-disjoint FAR-tier control pairs as 'mid' instead of 'far' (llama3.1:8b missed 5/30 control items this way -- registan/platter, mazaa/duration, tokri/law, junoon/auntie, bhanji/trunk; gemma2:9b missed 4/30 -- dehat/yogurt, registan/platter, mazaa/duration, junoon/auntie -- registan/platter and mazaa/duration fail for BOTH models, suggesting these are genuinely harder control items, not model-specific noise). Near-tier control accuracy was 100% for all three models tested -- the failure is specific and asymmetric to the far/unrelated tier, not a general judge quality problem. qwen3:8b remains the one PASSING judge found so far (96.7% overall, 100% near, 93.3% far) and is documented here as the known-good first judge for any future attempt with a genuinely different third model family. Per GG's explicit stop instruction, no third replacement model was tried and the bar was not loosened or re-tested at a different temperature to result-shop a pass. This workstream is closed as a final, honest negative result -- not a blocker requiring further escalation.

## Sample sizes and provenance

- Calibration controls: 15 near + 15 far = 30 items per judge (same control set both attempts, seed=42, same exclude= set as run_full_protocol() computes internally).
- k=3 self-consistency samples/item, temperature=0.7, same schema-constrained Ollama generate call pattern as the rest of this module.
- Full per-item raw votes for all three judges preserved in the corresponding `.json` (`attempts` / `raw` keys) for future re-analysis.

---

**This is an LLM-CONSENSUS ceiling attempt, NOT a human-annotated ceiling. Per GG's standing policy (spec-metrics-ceiling-calibration.md), manual labeling is never used -- the protocol requires two different-family LLM judges, blind, self-consistency-sampled, and BOTH must clear a mandatory calibration gate on unambiguous control items before any consensus label is trusted. This run could not clear that gate: see the FINAL FINDING below.**

