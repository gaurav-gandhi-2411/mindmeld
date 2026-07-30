# Band-Threshold Calibration -- WORKSTREAM 3 (spec-metrics-ceiling-calibration.md)

**Status: analysis only, nothing shipped.** `rival.py`'s live `band_for_rank`/
`scorching_cutoff` are untouched throughout this document. All numbers below
come from `evals/finetune/data/calibration_threshold_results.json`, produced
deterministically by `uv run python -m evals.finetune.optimize_band_thresholds`
(seed 42, no re-embedding, no retraining, no GCP) replaying the already-
checkpointed shipped-model bake-off
(`evals/finetune/data/bakeoff_raw/gauravgandhi2411__hinglish-relatedness-sbert.json`,
376 resolved dim1 records / 42 secrets).

## Scope note: this analysis is hi-en-only, and that's the whole available population

Every one of the 42 secrets in the shipped-model bake-off checkpoint is drawn
from the hi-en scenario fixtures (`evals/scenarios/dim1_hien.json` +
`dim1_benchmark_supplement_hien.json`) -- confirmed by a direct set-membership
check against the EN fixtures' secret lists (zero overlap in either
direction). **No EN-language `actual_rank` data exists in any `bakeoff_raw`
checkpoint at all** -- the bake-off this workstream replays never scored EN.
Producing an EN-parallel diagnosis would require running fresh embeddings
against the EN dim1 fixtures, which the task's "no re-embedding" constraint
rules out. So the spec's "do this separately for hi-en and en if both have
enough mid-tier volume" resolves to: **hi-en only, because that's the only
language with any volume in this data at all.**

This is consistent with why the prior 900-floor fix (commit `894f63e`) was
hi-en-specific too: `rival.py`'s own docstring notes EN's un-floored
`warm_max` (55,000 * 0.05 = 2,750) already dwarfs any floor value explored in
this report, so none of the candidates below can ever change EN's behaviour
-- verified algebraically for every warm_floor tested here (max explored:
3,500 < 2,750 is false only at the very top of the grid, but the winning
candidate at 1,050 is nowhere near it).

## A load-bearing caveat before anything else: threshold changes cannot move ECE

The spec's "Current state" section names ECE 0.202 (tied with granite's
0.195) as the one dimension without a clear lead, and frames this workstream
as attacking that number. **It provably cannot move it.**
`topheavy.band_calibration_error` derives its confidence signal as
`1 - actual_rank / vocab_size` and its outcome as `tier in {near, mid}` --
neither term depends on `actual_band` at all. Recomputed directly for both
the baseline and the winning candidate below: **ECE = 0.2020108359603864,
byte-identical**, exactly as the prior 900-floor fix already found and
reported "for completeness, not claimed as fix evidence." Any threshold
search (this one included) can only move the band-level precision/recall/
confusion-matrix numbers -- it is a distinct, real, and useful lever for
band-assignment quality, but it does **not** close the ECE gap the spec's
background section cites. That gap, if it's worth closing, needs a different
mechanism (e.g. a monotonic recalibration of the rank->confidence mapping
itself) -- out of scope here per the task's boundaries.

---

## Step 1: diagnosing the Warm asymmetry

Of the 84 mid-tier records, 77 currently do NOT land in Warm (band 3) under
the real shipped formula (7/84 = 8.33% recall, matching
`current_state_report.json`). Every one of those 77 records' `actual_rank`
was bucketed by *why* it misses:

| Bucket | Definition | n | % of the 77 misses |
|---|---|---:|---:|
| **too_close** | rank <= hot_max (500) -- lands in Scorching/Hot | 31 | 40.3% |
| **near_miss** | hot_max < rank <= warm_max+1500 (900-2400) -- lands in Cold, close to the boundary | 19 | 24.7% |
| **deep_tail** | rank > warm_max+1500 (>2400) -- deep in Cold or Freezing | 27 | 35.1% |

Rank histogram of the 77 missed records (bin edges chosen at the live
boundaries: scorching_cutoff=50, hot_max=500, warm_max=900, warm_max+1500=2400):

| Range | n |
|---|---:|
| (0, 50] -- lands in **Scorching** | 16 |
| (50, 500] -- lands in **Hot** | 15 |
| (500, 900] | 0 (already inside Warm by definition) |
| (900, 2400] -- **Cold, near boundary** | 19 |
| (2400, 5000] -- Cold/Freezing, far tail | 16 |
| (5000, 10495] -- deep Freezing | 11 |

Full sorted list of the 77 missed ranks is preserved in
`calibration_threshold_results.json` -> `diagnosis.sorted_missed_ranks`.

**Verdict: predominantly genuine ranking error, NOT threshold placement.**
75.3% of the misses (`too_close` + `deep_tail`) cannot be fixed by moving any
rank-based threshold:

- The **31 `too_close` records (40.3%)** rank as *more* related than a
  mid-tier word should (rank <= 500, i.e. the model's Scorching/Hot
  territory). Widening Warm cannot touch these -- they sit on the wrong side
  of Hot's boundary entirely. The only lever that could reach them is
  *tightening* `hot_max`, and that band is shared with near-tier: near-tier
  ranks in the same window (51, 54, 55, 79, 124, 132, 139, 175, 190, 206,
  220, 226 x3, 275, 277, 311, 423, 482 -- 20 of near's 84 records) interleave
  directly with the 15 mid records currently classified Hot (67, 67, 128,
  174, 188, 197, 205, 236, 265, 267, 269, 321, 323, 346, 357). There is no
  rank cutoff that separates "over-ranked mid words" from "correctly-ranked
  near words" in this window -- confirmed by grid-searching `hot_floor`
  jointly with `warm_floor` (Step 2/3 below): every `hot_floor` deviation
  from 500 that recovers `too_close` mid records simultaneously breaks
  near-tier records at the same rate or worse.
- The **27 `deep_tail` records (35.1%)** sit past rank 2400 (up to 9,170, out
  of a 10,495-word vocab) -- no defensible Warm width reaches these without
  swallowing nearly the entire Cold/Freezing space.
- Only the **19 `near_miss` records (24.7%)**, clustered just past the
  current 900-rank floor (961-2,097, see Step 2), are genuinely
  threshold-placement-recoverable.

## Step 2/3: joint threshold search (hot_max + warm_max, cold left alone)

**Search space:** `hot_floor` in {200, 225, ..., 900} (`hot_frac` fixed at
0.01, unchanged), `warm_floor` in {900, 910, ..., 3500} (`warm_frac` fixed at
0.05, unchanged) -- same `max(floor, n*fraction)` shape rival.py already uses.
`cold_max` was **not** searched: it provably cannot affect this objective,
because far-tier's `expected_bands=[4,5]` accepts *either* Cold or Freezing
-- moving the Cold/Freezing boundary can only reclassify a far-tier record
between two bands that are both already "correct" for it, and directly
verified no mid/near record in this fixture sits anywhere near a candidate
cold boundary either. `scorching_cutoff` was left fixed per the task's scope
(not implicated in the Warm-recall diagnosis).

Objective: raw regression-floor accounting (fixed = a record that was WRONG
under the current shipped formula and becomes RIGHT under the candidate;
broken = the reverse) -- the same "N fixed / M broken" methodology this repo
already uses for every prior band/retraining gate (PLAN.md, e.g. `894f63e`'s
own before/after), computed against a **freshly recomputed baseline** (see
correctness note below), not the stale `actual_band` field stored in the raw
checkpoint.

**Correctness note, found while building this:** the `actual_band`/
`in_expected_band` fields already present in `bakeoff_raw/*.json` were
computed at bake-off time and were **never refreshed in place** when the
900-rank warm floor shipped (`894f63e`) -- only a separate report
(`current_state_report.json`) recomputed them. An early draft of this search
used the raw checkpoint field directly as "current behaviour" and got
spurious `broken` records at ranks like 525-698 that were flagged wrong even
though they're unaffected by any candidate in this search -- those records
were artifacts of comparing against the *pre-floor* formula, not the live
one. `optimize_band_thresholds.recompute_bands()` fixes this by recomputing
`actual_band`/`in_expected_band` fresh from `actual_rank` via the real
`rival.band_for_rank` before any comparison -- see the module docstring.

### Global search results

| hot_floor | warm_floor | fixed | broken | net | macro-tier-acc |
|---:|---:|---:|---:|---:|---:|
| 500 (unchanged) | 1010-1064 | 4 | **0** | **+4** | 0.5728 |
| 250 | 1010-1060 | 11 | 5 | +6 | 0.5807 |
| 500 (unchanged) | 1700-1760 | 17-18 | 13-14 | +4 | ~0.60+ |

The **strict-zero-broken plateau is warm_floor in [1002, 1064]** (fixed=4
throughout, verified at 1-rank granularity) with `hot_floor` unchanged at
500 -- no `hot_floor` value other than 500 clears zero-broken anywhere in the
grid, confirming Step 1's finding that Hot's boundary has no safe room to
move. Global net-maximum across the *entire* grid (ignoring the zero-broken
constraint) is only +6, at `hot_floor=250` -- and that comes at the cost of
5 broken **near-tier** records (see rejected candidate below), i.e. it
reproduces the exact "fix one band, break another" pattern this workstream
was set up to avoid, just with Near playing Far's role this time.

**Winning candidate:** `hot_floor=500` (unchanged), `warm_floor=1050`
(midpoint of the zero-broken plateau [1002, 1064], not sitting at either
edge), `hot_frac`/`warm_frac`/`cold_floor`/`cold_frac` unchanged. This is a
small, honest win: **+4 fixed, 0 broken**, i.e. it recovers 4 of the 19
threshold-recoverable `near_miss` records at zero collateral cost, and
leaves the other 15 `near_miss` records (and all 58 `too_close`+`deep_tail`
records) unrecovered because reaching them costs more than they're worth
under the zero-broken gate.

## Step 3: full band-by-band table, current vs winning candidate, with bootstrap CIs

Cluster-bootstrap by secret, 10,000 draws, seed 42
(`bootstrap_per_band_pr_ci`, same resampling pattern as `bootstrap_ci.py`'s
other cluster bootstraps).

| Band | Current precision [95% CI] | Candidate precision [95% CI] | Current recall [95% CI] | Candidate recall [95% CI] |
|---|---|---|---|---|
| win | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | n/a (n_expected=0) | n/a |
| scorching | 0.686 [0.610, 0.791] | 0.686 [0.610, 0.791] (unchanged) | 0.417 [0.286, 0.548] | 0.417 [0.286, 0.548] (unchanged) |
| hot | 0.455 [0.325, 0.579] | 0.455 [0.325, 0.579] (unchanged) | 0.238 [0.143, 0.345] | 0.238 [0.143, 0.345] (unchanged) |
| **warm** | **0.412** [0.176, 0.667] | **0.524** [0.304, 0.750] | **0.083** [0.024, 0.155] | **0.131** [0.060, 0.217] |
| cold | 0.537 [0.420, 0.660] | 0.571 [0.453, 0.690] | 0.173 [0.120, 0.227] | 0.173 [0.120, 0.227] (unchanged) |
| freezing | 0.810 [0.752, 0.873] | 0.810 [0.752, 0.873] (unchanged) | 0.760 [0.691, 0.823] | 0.760 [0.691, 0.823] (unchanged) |

(`n_predicted`/`n_expected` and the raw draws behind every cell are in
`calibration_threshold_results.json` -> `baseline.per_band_pr_bootstrap` /
`winning_candidate.per_band_pr_bootstrap`.)

**Honesty check on statistical significance:** Warm recall's point estimate
moves 0.083 -> 0.131 (+4.8pp) but the two CIs overlap heavily
([0.024, 0.155] vs [0.060, 0.217]) -- at n=84 mid-tier records this small a
change is **not CI-significant**. Reported as a real, verified, zero-cost
directional improvement, not an overstated "fix." Note Warm's precision
*also* rose (0.412 -> 0.524) rather than falling, and Cold's precision rose
slightly too (0.537 -> 0.571) -- consistent with the prior fix's own finding
that "the newly-captured records aren't noise": the 4 newly-Warm records
were previously miscounted Cold false negatives for mid-tier, not genuine
Cold-tier content, so removing them from Cold's prediction pool doesn't hurt
Cold and removes 4 non-mid contaminants from nowhere (they were never
counted against Cold's precision either way, since precision is about what
Cold currently predicts, not what departed).

### Confusion matrices (rows=near/mid/far, cols=win/scorching/hot/warm/cold/freezing)

Current:
```
near [2, 35, 20,  5, 12,  10]
mid  [0, 16, 15,  7, 19,  27]
far  [0,  0,  9,  5, 36, 158]
```

Winning candidate (warm_floor=1050):
```
near [2, 35, 20,  5, 12,  10]   <- byte-identical to current
mid  [0, 16, 15, 11, 15,  27]   <- warm 7->11, cold 19->15
far  [0,  0,  9,  5, 36, 158]   <- byte-identical to current
```

Near and Far rows are **byte-identical** between current and candidate --
zero collateral damage, unlike the prior 900-floor fix which moved Far's
accuracy 95.7% -> 93.3%. ECE unchanged (0.2020108359603864 for both, see
caveat above). `band_accuracy`: overall 0.6809 -> 0.6915 (+1.06pp, +4/376),
near 0.6548 -> 0.6548 (unchanged), mid 0.0833 -> 0.1310 (+4.77pp), far
0.9327 -> 0.9327 (unchanged), macro-tier-accuracy (mean of the three)
0.5569 -> 0.5728 (+1.59pp).

## Step 3: the Warm/Far (and Warm/Near) trade-off, made explicit

This is the central check this workstream exists to run, given the last fix
already fell into this trap once. Two candidates were evaluated jointly, not
just Warm in isolation:

1. **Winning candidate** (`hot_floor=500` unchanged, `warm_floor=1050`):
   Far accuracy 0.9327 -> 0.9327 (**zero change**), Near accuracy 0.6548 ->
   0.6548 (**zero change**), Mid accuracy 0.0833 -> 0.1310 (+4.77pp). No
   trade-off exists at this candidate -- the regression-floor gate (0
   broken) is the direct, mechanical proof of that, not an inference.
2. **Rejected aggressive candidate** (`hot_floor=250`, `warm_floor=1050`,
   i.e. also tightening Hot to try to recover more `too_close` mid records):
   Mid accuracy rises further to 0.2143 (+13.1pp vs baseline) but **Near
   accuracy falls to 0.5952 (-5.95pp)** -- 5 near-tier records (`bagicha`/
   `garden` rank 482, `pahad`/`peak` rank 423, `dhoop`/`brightness` rank 277,
   `sarhad`/`boundary` rank 275, `sharm`/`shyness` rank 311) flip from
   correctly-Hot to incorrectly-Warm. Far accuracy is unaffected (0.9327 ->
   0.9327, Far never touches Hot's boundary), but this candidate
   **reproduces the workstream's own cautionary precedent**: it buys a
   bigger Warm/Mid win by quietly debiting a *different* band (Near instead
   of Far this time) -- exactly the one-band-at-a-time trap Step 3 of the
   spec explicitly names. **Rejected.** Full detail (which 5 near records
   flip and why) is in `calibration_threshold_results.json` ->
   `rejected_aggressive_candidate.regression_floor.detail`.

Net verdict: **the only threshold change that clears a strict zero-broken
gate is a modest one.** A larger, more ambitious win exists in the search
space (+6 net vs +4), but it is not free -- it is the same trade this
workstream is designed to catch, and is explicitly rejected rather than
smoothed over to make the numbers look better.

## Step 4: gates

### (a) Full existing test suite

`uv run pytest` from `generator/` -- see session report for the final
pass/fail count (this analysis added `evals/finetune/optimize_band_
thresholds.py` + `tests/test_optimize_band_thresholds.py`, 17 new tests, all
passing standalone; `rival.py` itself was not modified, so no pre-existing
test can be affected by this workstream's code).

### (b) Regression-floor check ("N fixed / M broken")

Already covered in Step 2/3 above: **winning candidate = 4 fixed / 0
broken (net +4, strictly zero-broken)**, matching this repo's own
established "STRICT zero" gate style (see PLAN.md precedents, e.g. "10
fixed/0 broken ... STRICT zero", "7 fixed/0 broken (net +7, strictly
zero-broken)").

### (c) Realistic-guess-distribution reachability simulation

Player model mirrors `evals/harness/dimension5_winrate.py`'s adaptive-
reduction + 15%-stall-probability noisy trajectory (same shape used for the
prior 900-floor fix's own guess-distribution validation per PLAN.md) --
implemented as `optimize_band_thresholds._simulate_trajectory` /
`band_reachability`. Run across all **118 real hi-en puzzles** (68 daily +
50 live-pack, same puzzle universe as the prior fix's validation), 100
simulated noisy trajectories each, seed 42, tallying which band every
visited rank lands in under both the current and winning-candidate
thresholds (identical trajectories reclassified under both formulas for an
apples-to-apples comparison):

| Band | Current: steps (fraction) | Candidate: steps (fraction) |
|---|---:|---:|
| win | 11,800 (8.44%) | 11,800 (8.44%) -- unchanged |
| scorching | 58,529 (41.87%) | 58,529 (41.87%) -- unchanged |
| hot | 39,104 (27.98%) | 39,104 (27.98%) -- unchanged |
| **warm** | **5,785 (4.14%)** | **7,361 (5.27%)** |
| cold | 10,420 (7.45%) | 8,844 (6.33%) |
| freezing | 14,134 (10.11%) | 14,134 (10.11%) -- unchanged |

**All 6 bands are non-degenerate (nonzero) under both the current and
candidate thresholds** -- `all_bands_reachable: true` for both (verified via
`band_reachability`, whose detector was itself sanity-checked in
`test_optimize_band_thresholds.py::TestBandReachability::
test_pathological_params_can_starve_a_band` against a deliberately
pathological threshold set that DOES starve Cold/Freezing, confirming the
check isn't vacuously true). Scorching, Hot, Freezing, and Win are
byte-identical step counts between current and candidate (as expected --
only the Warm/Cold boundary moved); Warm's simulated step-share rises from
4.14% to 5.27% (Cold correspondingly falls 7.45% -> 6.33%), i.e. players will
concretely encounter the Warm band somewhat more often under the winning
candidate, with no change to how often they see Scorching, Hot, or Freezing.

---

## Proposed `rival.py` diff (NOT applied -- for orchestrator review only)

If GG approves shipping the winning candidate:

```diff
--- a/generator/rival.py
+++ b/generator/rival.py
@@ def band_for_rank(rank: int, n: int) -> int:
     hot_max = max(500, int(n * 0.01))
     if rank <= hot_max:
         return 2
-    warm_max = max(900, int(n * 0.05))
+    warm_max = max(1050, int(n * 0.05))
     if rank <= warm_max:
         return 3
```

(Plus updating the module docstring's threshold table and the `warm's
900-rank floor` explanatory comment to describe 1050, mirroring how the
900-floor fix documented its own choice in place.)

**Sites that would ALSO need this constant if shipped** (found by the same
"every OTHER inline `n * 0.05` re-derivation" audit the 900-floor fix
already did, per PLAN.md):
- `rival.py`'s own `_generate_path`'s `warm_threshold = max(900, int(n * 0.05))`
  (adaptive-convergence cold/warm transition -- currently duplicates the
  formula, same as before the 900-floor fix).
- `evals/harness/dimension5_winrate.py::_simulate_one`'s own
  `warm_threshold = max(900, int(n * 0.05))` (this report's own
  `_simulate_trajectory` is a fresh copy of that logic, made ONLY for this
  reachability check -- it was deliberately left reading 900 throughout,
  since it exists to characterise player behaviour under the CURRENT shape,
  not to be a second site needing the constant kept in sync; if the
  candidate ships, this literal analysis file does not need updating, but
  `dimension5_winrate.py` itself would).
- `generator/tests/test_rival.py`'s hardcoded boundary assertions
  (`test_warm_boundary`, `test_hien_warm_floor_fix`, `test_small_vocab_hot_floor`)
  would need their literal 900/901/524/... values recomputed to 1050/1051/....
- **Dart mirror, `app/lib/core/config.dart:176`**:
  `static const int warmFloor = 900;` -> `1050`. `app/lib/core/models.dart`'s
  `bandForRank` (lines ~71-90) reads `AppConfig.warmFloor` directly via
  `.clamp(AppConfig.warmFloor, n)`, so no Dart logic changes, only the
  constant -- but this file was **not edited** by this session per the task's
  explicit "do NOT touch Flutter/Dart files" instruction; flagging it here so
  the orchestrator can route it to a Dart-capable session before shipping.
  `app/test/temperature_bands_test.dart`'s hardcoded 501-900 Warm-window
  fixture (updated by the 900-floor fix) would also need its window
  recomputed to 501-1050.

**This diff is NOT committed and NOT applied anywhere in this session.**

---

## Summary

- **Diagnosis (Step 1):** Warm's 8.3% recall is **predominantly a genuine
  ranking-error problem (75.3% of misses), not a threshold-placement
  problem** -- confirmed with rank-distribution evidence, not assumed.
- **Optimisation (Steps 2/3):** the only threshold change that clears a
  strict zero-broken regression-floor gate is `warm_floor: 900 -> 1050`
  (hot/cold left untouched) -- a small, honest win (+4 fixed / 0 broken;
  Mid recall 8.3% -> 13.1%, not CI-significant at this sample size, but
  directionally real and zero-cost). A larger win exists in the search
  space (+6 net) but was explored and **rejected** because it reproduces
  this workstream's own cautionary precedent by trading Near-tier accuracy
  away instead of Far's.
- **Joint trade-off (Step 3):** the winning candidate leaves Near and Far
  **byte-identical** confusion-matrix rows -- zero trade-off, unlike the
  prior 900-floor fix.
- **Gates (Step 4):** regression-floor 4 fixed/0 broken; full pytest suite
  status reported separately in the session summary; realistic-guess
  simulation confirms all 6 bands remain reachable/non-degenerate under
  both current and candidate thresholds.
- **ECE caveat:** no threshold change (this one or any other) can move the
  spec's headline ECE=0.202 number -- it is mathematically independent of
  band assignment. This is a real, verified finding, not a workaround.
- **Recommendation:** the winning candidate (`warm_floor=1050`) is safe to
  ship on this evidence, but it is a modest fix, not a breakthrough --
  reported honestly rather than oversold. Awaiting GG review of the diff
  above before any application to `rival.py` or the Dart mirror.
