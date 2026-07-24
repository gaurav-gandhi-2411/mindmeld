# Hinglish Model Excellence Program — Consolidated Final Report

Source of truth for scope: `spec-model-excellence.md` (repo root). This report is the
program's final deliverable: every finding produced across Workstreams A–F, ranked by
**prevalence** (how much of the game/vocab it touches) and **user impact** (how much it
degrades what a player actually sees), each with its evidenced next attack. Every number
below was independently computed and verified during this program — commit SHAs are
given so each claim can be traced to the exact code/data that produced it.

Model in scope throughout: `gauravgandhi2411/hinglish-relatedness-sbert` (published,
unchanged this program except the two shipped patches noted in finding 3 and F below).
Benchmark in scope: the internal 42-secret/379-scenario combined test set
(`evals/finetune/benchmark_bakeoff.py`) unless stated otherwise.

---

## Ranked findings

### 1. Mid-tier "Warm" band is structurally ~24 ranks wide — the single highest-prevalence, highest-impact issue found

**What**: `rival.band_for_rank`'s formula gives hi-en (vocab n=10,495) a Warm band
(band 3) spanning only ranks 501–524 — 24 ranks out of 10,495 (0.23% of vocab), vs
Near-tier's effective ~499-rank window and Far-tier's ~9,971-rank window. Two
independent analyses converged on this from opposite directions:
- Workstream A's band-confusion matrix (commit `00b0bfd`): the shipped model predicts
  Warm for only **2 of 84** human-expected-Warm test words.
- Workstream B's failure taxonomy (commit `ac6f41d`): **83 of 84** resolved mid-tier
  scenario records fail their expected-band check — traced directly to this band-width
  arithmetic, independently re-verified by hand from `rival.py`.

**Why it ranks #1**: this is not a model-quality problem — a perfect embedding could
not fix it, because the target the model is being measured against is nearly
unhittable by construction. It affects the majority of "moderately related" guesses
any player makes across the whole game (both languages share the same band formula),
not a narrow vocabulary slice.

**Evidenced next attack** (not yet attempted): widen the Warm band's formula (e.g.
`warm_max = int(n * 0.08)` instead of `0.05`, or a floor similar to Hot's
`max(500, n*0.01)`) and re-run the full Workstream A metric suite (band-confusion
matrix + per-band precision/recall + NDCG/MRR) to confirm mid-tier accuracy improves
without regressing Near/Far. This is a game-calibration change, not a model change —
cheap to test, no retraining required, and should be the very next thing attempted.

---

### 2. Spelling-variance non-invariance — real, held-out, and still unfixed

**What**: on 267 genuinely held-out real-world spelling variants (Aksharantar-corpus-
derived, 13 test secrets with coverage), the shipped model's band-agreement rate
between a word's canonical spelling and an alternate real spelling is only **67.4%
[95% CI 0.538, 0.801]** (commit `4eb6386`). Worst case: `azaadi`/`rights` rank 16
(scorching) vs `azaaadi`/`rights` rank 9753 (freezing) — the same secret, spelled two
valid ways, produces opposite game feedback.

**Why it ranks #2**: romanized Hindi has no canonical orthography, so this affects any
player who doesn't happen to type the one spelling baked into the vocab — plausibly a
large fraction of real usage, though (unlike finding 1) the exact hit rate among real
players hasn't been measured, only the model's raw sensitivity to it.

**Attempted fix, failed** (commit `bc4b25a`): variant-augmented retraining (189 new
Aksharantar-derived training pairs, exact shipped recipe) regressed the main benchmark
(dim1: 2 fixed/10 broken) and did not meaningfully improve robustness (66.3% vs 67.4%
baseline — within noise). Not shipped.

**Evidenced next attack**: the retraining approach failed at the scale attempted, but
a structurally different, lower-risk fix was never tried — **extend
`vocab/hi-en-aliases.txt` directly** with Aksharantar-derived variant pairs (the exact
same string-fold mechanism that already gives the 29 existing alias words 100%
consistency by construction, confirmed in the Workstream C research pass) rather than
relying on embedding generalization. This sidesteps all regression risk since it
doesn't touch the model at all — it's the same low-blast-radius mechanism class as the
L2 patch, and should be gated the same way (incremental, zero-regression-checked
batches, following the pattern that worked for `sharm` below) rather than one large
injection.

---

### 3. Subword collision — systematic, only 1/211 flagged words safely fixed so far

**What**: a full-vocab scan (commit `ac6f41d`) found **211 of 544** hinglish-sourced
vocab words (38.8%) show the subword-collision signature (embedding neighbors
dominated by orthographically-similar but semantically-unrelated English tokens) —
calibrated against the 4 already-shipped L2 patch words plus the 9 hand-picked
candidates from `probe_subword_collision.py`. A gated extension attempt found the full
58-word dict-coverable batch **fails** the zero-broken-pairs bar (4 broken pairs), and
bisection found no larger safe subset — but a minimal **+1 word (`sharm`→शरम) cleared
both gates cleanly** and was shipped to production (commit `80cf3ad`, re-verified
through the real production path, CI-significant improvement on every Workstream A
top-heavy metric).

**Why it ranks #3**: 211 flagged words is a meaningful fraction of the curated secret
pool (554 words), but only word-pairs that actually become a scheduled secret and a
plausible guess surface this failure in practice — narrower blast radius than findings
1–2, and one instance is already fixed.

**Evidenced next attack**: continue the same incremental, gate-gated pattern that
worked for `sharm` — take the next-most-severe words from the ranked
`collision_scan_report.json` list one at a time (or in very small batches of 2–3,
given the demonstrated cliff between "+1 safe" and "+2 through +58 all fail"), testing
each against the full regression floor before adding.

---

### 4. Genuine semantic difficulty — the largest raw failure count, but not a lever

**What**: of the 124 failing pairs analyzed (Workstream B, commit `ac6f41d`), **79.8%
(99/124)** were classified as genuine semantic difficulty — a real but subtle/weak
association (e.g. `bachpan`/`innocence`) that no amount of targeted fixing addresses,
since it isn't a bug. Transliteration artifacts were 11.3% (14/124); polysemy,
commonsense/world-knowledge, and label-error each ~2-3%. Cross-referencing against the
collision scan found 46% (57/124) of failing pairs also have a collision-flagged
secret — evidence the raw taxonomy likely undercounts subword-collision as a
contributing cause, since per-pair judging never sees the full neighbor list.

**Why it ranks #4**: highest count, lowest actionability. This is the honest ceiling
of what fine-tuning alone can fix — matches the project's own established finding
(large training-data injections regress rather than help, findings 2 and 5 below)
that the remaining gap isn't purely a data problem.

**Evidenced next attack**: none identified this program beyond what's already being
pursued (finding 3's collision fixes address a real slice of this overlap). The
benchmark-power finding (below) is the actual lever here — more statistical power is
needed to tell a real fix from noise on this residual.

---

### 5. Model size and its lone real efficiency win

**What**: the shipped model is 956.7MB on disk (Workstream E, commit `bf4744a`),
dominated by a 197,285-token multilingual embedding table (~606MB of the ~950MB total).
Three shrink/speed approaches were gated on the full metric suite:
- **Binary quantization of the precomputed vocab embedding cache: PASSES** — 32x
  storage reduction (32.24MB→1.01MB), zero net regression. Real, but shrinks the
  reusable embedding-cache artifact, not the 956MB model file, and delivers no speed
  win without a real vector-search dependency (deliberately not added).
- int8 embedding quantization: fails the strict per-pair floor (dim2 net −1).
- torch dynamic model-weight quantization: decisive fail (dim1 0.67→0.28) — only
  shrinks the small transformer body, not the dominant embedding table.
- MiniLM-L12-v2 distillation candidate: decisive fail (dim1 0.67→0.23) — this base
  already scored near-random on hi-en off-the-shelf in the original bake-off; 4
  epochs can't teach romanized-Hindi understanding from scratch.

**Why it ranks #5**: production has **no live per-user embedding inference today**
(`payload.py` precomputes once per secret at build time; the live game is O(1)
hash-lookups) — this is not currently a user-facing bottleneck. It matters for
hosting/clone cost and any future on-device roadmap, not today's gameplay.

**Evidenced next attack**: the "same quality, materially smaller/faster MODEL" USP is
not achieved and no further lever was identified this program (both routes that could
shrink the model itself — weight quantization, distillation — failed decisively, for
structurally different reasons each). Lowest priority to revisit unless the
architecture changes (e.g. a future on-device requirement).

---

### 6. Benchmark statistical power — an enabling investment, not a bug

**What**: the 34-secret public benchmark would need roughly **56 secrets (~22 more)**
to reliably (≥80% power) detect a ~0.06-magnitude effect — the size of change that
repeatedly near-misses significance in this program's own history (commit `4152473`).
This doesn't describe a model defect; it describes the ruler's own resolution limit.

**Why it ranks #6**: doesn't affect what players see, but affects whether future
`model change` decisions can be told apart from noise — directly relevant to
evaluating any fix attempted for findings 1–3 above.

**Evidenced next attack**: author ~22 more benchmark secrets following the existing
`gen_dim1_benchmark_supplement.py` pipeline (domain tuple + 4 curated EN words + no-
leakage grep + two scrub-script passes + GG review of new advisory hits) — a real
content-authoring investment, explicitly not undertaken this program pending GG's
prioritization call.

---

### 7. Benchmark label ceiling — measurement in progress, GG action pending

**What**: the near/mid/far tiers are AI-authored and have never been checked against
independent human judgment. A blind, stratified 75-pair sample is ready
(`evals/finetune/data/label_ceiling_sample_for_gg.csv`, commit `4152473`) — GG's
tier judgments, once filled in, will produce a weighted-kappa agreement score (scorer
already written and validated against textbook golden values).

**Why it ranks #7**: can't be ranked by impact until the number exists. Flagged here
so it isn't lost — this is the program's one outstanding **stop point** requiring
action only GG can take.

---

### 8. External comparability — resolved as a documented absence

**What**: a live search (GLUECoS, LinCE, SemRel2024, IIIT-Hyderabad word-similarity
sets, HinglishEval — `docs/known-limitations.md` entry 22, commit `7526c93`) found no
existing public resource matching this project's task shape (word-level relatedness
ranking over romanized, code-mixed Hindi-English). This is now an evidenced claim, not
an assumption.

---

### 9. L5 dormancy — closed this program

**What**: L5's 8 trigger words never appeared in any live schedule and had never
fired in production. Fixed by scheduling all 8 into the existing cyclic schedule
(commit `2f4dd15`) — each will fire on a confirmed future date (2026-08-11 through
2026-08-18). No longer an open item.

---

### 10. L4/L6 — confirmed still open, untested at scale

**What**: both remain live, probed-at-small-scale-only levers (L4 knowledge
distillation: bounded, zero-net-regression on 5/8 candidates; L6 commonsense training
data: 5/8 improved, 3/8 regressed, n=8 too small to call) — `docs/known-limitations.md`
entry 20's addendum (commit `2f4dd15`) now correctly cross-references both, closing a
documentation gap where the entry never actually carried the L4/L6 labels its own
probe scripts pointed readers to.

---

## What this program did NOT change about the shipped model

The published model (`gauravgandhi2411/hinglish-relatedness-sbert`) is unchanged
except two small, fully-gated production patches: the L2 Devanagari patch grew from 4
to 5 words (`sharm`), and L5's trigger words are now reachable via the schedule. No
retraining was promoted — both attempts this program (variant-augmentation,
distillation) produced honest, evidenced NO-GOs, and "the current published model
stands until beaten" held throughout, per the program's own gates.

## Provenance

All findings above were computed on branch `feat/hinglish-finetune`; commit SHAs are
quoted inline. Every headline number was independently re-derived or spot-checked
(hand computation, direct JSON inspection, or a separate verifier pass) before being
included here — see `PLAN.md`'s Model Excellence Program checkpoints for the full
per-workstream verification trail.
