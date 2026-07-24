# Spelling-variance robustness report

Model: `gauravgandhi2411/hinglish-relatedness-sbert`. Test secrets: 42 (evals/finetune/data/bakeoff_raw/gauravgandhi2411__hinglish-relatedness-sbert.json's checkpointed canonical ranks -- reused, not recomputed).

Ollama available: False. Secrets with no real (alias/Aksharantar) coverage: 26 (llm_generated fallback produced usable variants for 0 of them).

Aksharantar full-vocab coverage (context, not the eval itself): 105/544 hinglish-sourced vocab words have >=1 clean Aksharantar-mined variant.

Secrets with an internal space (whitespace 'doubled_internal_space' sub-case applies): 0/42.

## Summary table

| category | n pairs | band-agreement rate [95% CI] | mean rank drift [95% CI] | median rank drift | top-weighted corr [95% CI] |
|---|---|---|---|---|---|
| alias_in_training | 0 | n/a | n/a | n/a | n/a |
| alias_file_untrained_heldout | 37 | 0.432 [0.333, 0.500] | 1603.514 [922.600, 2273.889] | 1194.0 | 0.843 [0.820, 0.878] |
| aksharantar_heldout | 267 | 0.674 [0.538, 0.801] | 1380.127 [954.375, 1810.790] | 742.0 | 0.796 [0.690, 0.886] |
| llm_generated | 0 | n/a | n/a | n/a | n/a |
| casing | 1128 | 0.602 [0.546, 0.655] | 1864.411 [1598.111, 2159.376] | 1219.0 | 0.711 [0.659, 0.758] |
| whitespace | 376 | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 0.0 | 1.000 [1.000, 1.000] |
| typo | 752 | 0.608 [0.549, 0.662] | 1878.367 [1604.350, 2184.729] | 1178.0 | 0.702 [0.648, 0.750] |

## Worst-case example per category

- **alias_in_training**: n/a
  - _SANITY CHECK ONLY -- these exact pairs were in the shipped model's training data (verified via literal membership in train_mnrl_pairs.jsonl). Strong performance here is expected and must NOT be used to support a spelling-invariance claim on its own._
- **alias_file_untrained_heldout**: secret='pahad' word='limitations' variant_word='pahaad' (alias_file_untrained_heldout/pahaad): canonical_rank=1795 (band 4) -> variant_rank=6538 (band 5), drift=4743
  - _Curated real variant, excluded from training via the held-out-secret rule -- genuine held-out evidence, alongside aksharantar_heldout._
- **aksharantar_heldout**: secret='azaadi' word='rights' variant_word='azaaadi' (aksharantar_heldout/azaaadi): canonical_rank=16 (band 1) -> variant_rank=9753 (band 5), drift=9737
  - _THE actual held-out measurement -- real-world mined variants, never trained on. This is the category that answers 'is the model spelling-invariant on words it wasn't trained for'._
- **llm_generated**: n/a
  - _LOWER CONFIDENCE -- the LLM's own beliefs about plausible romanizations, not observed real-world usage. Used only for secrets lacking both alias and Aksharantar coverage._
- **casing**: secret='kanoon' word='court' variant_word='KANOON' (casing/upper): canonical_rank=19 (band 1) -> variant_rank=9897 (band 5), drift=9878
  - _Synthetic, full 42-secret coverage._
- **whitespace**: secret='azaadi' word='liberty' variant_word='  azaadi  ' (whitespace/padded): canonical_rank=4 (band 1) -> variant_rank=4 (band 1), drift=0
  - _Synthetic, full 42-secret coverage (internal-space sub-case only when applicable)._
- **typo**: secret='sadak' word='road' variant_word='sdaak' (typo/transposition_or_insertion): canonical_rank=2 (band 1) -> variant_rank=10282 (band 5), drift=10280
  - _Synthetic, full 42-secret coverage._

## Verdict

NOT SUPPORTED: aksharantar_heldout band-agreement-rate=0.6741573033707865 with n=267 held-out real spelling variants -- robustness degrades meaningfully outside the trained alias words. Workstream C item 10 (variant-augmented contrastive retraining) IS warranted.

(n_real_heldout_pairs=304, n_aksharantar_heldout=267, n_alias_file_untrained_heldout=37, aksharantar band-agreement-rate=0.674)
