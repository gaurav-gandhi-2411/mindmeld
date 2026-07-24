# Statistical power analysis -- spec-model-excellence.md WORKSTREAM D item 12

Measurement only. No new benchmark secrets were authored as part of this report.

## Step 1 -- empirical CI-width-vs-n (measured, pool (c), 42 secrets, n<=42)

| k | median CI width | IQR | n draws |
|---|---|---|---|
| 20 | 0.2012 | [0.1624, 0.2312] | 200 |
| 25 | 0.1802 | [0.1579, 0.1992] | 200 |
| 30 | 0.1635 | [0.1484, 0.1777] | 200 |
| 34 | 0.1560 | [0.1456, 0.1655] | 200 |
| 38 | 0.1467 | [0.1390, 0.1535] | 200 |
| 42 | 0.1375 | [0.1346, 0.1442] | 30 |

## Step 2a -- MDE using the REAL observed L2+L5 effect (measured, k<=34 only)

| k | detection rate (>=80% target) | n sims |
|---|---|---|
| 20 | 23% | 150 |
| 25 | 29% | 150 |
| 30 | 32% | 150 |
| 34 | 27% | 30 |

## Step 2b -- MDE using calibrated-synthetic injection (measured, full k range)

Calibration (intensity per target effect size, at k=34):

| target effect size | calibrated intensity | calibration mean delta @k=34 |
|---|---|---|
| 0.04 | 0.08 | 0.0391 |
| 0.06 | 0.18 | 0.0645 |
| 0.1 | 0.35 | 0.1006 |

| k | detect@0.04 | detect@0.06 | detect@0.1 |
|---|---|---|---|
| 20 | 91% | 97% | 99% |
| 25 | 99% | 100% | 100% |
| 30 | 100% | 100% | 100% |
| 34 | 100% | 100% | 100% |
| 38 | 100% | 100% | 100% |
| 42 | 100% | 100% | 100% |

## Step 3 -- 1/sqrt(n) extrapolation beyond n=42 (EXTRAPOLATION, not measured)

Fitted C = 0.9002 (width(n) = C / sqrt(n))

| n | extrapolated CI width |
|---|---|
| 50 | 0.1273 |
| 60 | 0.1162 |
| 80 | 0.1006 |

## Step 4 -- conclusion

- Target effect size analysed: ~0.06
- Detection rate at k=34, calibrated-synthetic curve: 100%
- Detection rate at k=34, REAL observed effect: 27%
- Max detection rate, REAL observed effect, any tested k<=34: 32%
- Smallest k reaching 80% power (synthetic curve, OPTIMISTIC lower bound -- see caveat): 20
- CI-width-extrapolation crossing n (independent 3rd cross-check): 56.3 (~22 more secrets beyond 34)

**The two MDE curves disagree sharply at k=34: the calibrated-synthetic curve claims 100% detection power there, but the REAL observed L2+L5 effect (same 34 secrets) only detects 27% of the time -- the synthetic injection's uniform per-secret shift is a much cleaner signal than real per-secret heterogeneity, so the synthetic curve's 'k=20 is already enough' claim is treated here as an OPTIMISTIC LOWER BOUND, not an actionable target. The REAL curve itself never exceeds 32% detection across all tested k<=34 (no clear rising trend within the tested range, given real per-secret noise + limited sims), so it cannot pin down a 'crosses 80%' k either. The most defensible number here comes from a THIRD, independent cross-check: extrapolating the Step 3 1/sqrt(n) CI-width fit to find the n at which a ~0.06 point estimate's own CI width would plausibly clear zero (assuming the point estimate holds and the CI stays roughly symmetric) gives n~56 -- i.e. roughly 22 MORE secrets beyond the current 34, an EXTRAPOLATION-derived estimate distinct from either measured MDE curve above.**

The calibrated-synthetic curve is a documented computational-budget fallback (see module docstring) and, per the discrepancy above, should be read as an optimistic lower bound on secrets needed, NOT a reliable point estimate.

This is a measurement/recommendation for GG to weigh against the mechanical cost of authoring new benchmark secrets (domain tuple + 4 hand-picked EN words + no-leakage grep + two scrub-script passes + GG review of any new advisory rank-10 hits per secret) -- NOT something acted on in this task. No new benchmark secrets were authored here.
