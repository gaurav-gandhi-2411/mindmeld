# spec.md — Warmer Launch Readiness + Aesthetic Pass (mindmeld, wave: launch-1)

## PM header (required)
- **Target user:** daily word-game players in India + Hinglish speakers globally; Wordle-habit demographic seeking a fresh daily ritual.
- **Pain point:** existing semantic-guess games are English-only, culturally Western, and give opaque feedback; no daily game speaks Hinglish/Bollywood/Cricket.
- **Success metric:** D1 retention ≥ 30% and ≥ 40% of DAU completing the daily puzzle within 4 weeks of launch.
- **Who pays:** free at launch; monetization candidates (themed pack purchases / ad-light) deferred — launch validates retention first.

## Objective
Take Warmer from "feature-complete" to "launchable" in one wave: apply the queued calm-minimal aesthetic (warm-paper #FAF8F4, terracotta #DD6B4D) AND clear the 7 launch-check failures recorded in the governance PLAN.md (`C:\Users\gaura\.claude\PLAN.md`, /launch-check mindmeld entry — read it first; it has evidence + prioritized fix order).

## Scope (two tracks, interleavable)

### Track A — Aesthetic pass (calm-minimal)
1. Tokens first (15b): extend `lib/core/design_tokens.dart` (WarmerTokens) to the full calm-minimal system — warm-paper surfaces, terracotta accent, ink text scale, spacing/radii. Components consume tokens only; the earlier dedup PR (#3) already cleaned stragglers — keep it that way.
2. Apply across all screens: game board, heat-band feedback, leaderboards, packs, onboarding, settings. Restrained motion; the heat-band interaction is the hero moment — make it feel premium.
3. Fix the design-reviewer's blocking findings from the launch-check in the same pass (they're paint-adjacent): WCAG contrast failures, unlabeled input, blank empty state, missing error-retry affordance.
4. Design-reviewer sign-off required before track A closes (mindmeld is T2). Screenshots per screen in PRs (15c — mechanical gate now enforces).

### Track B — Launch gates (from /launch-check evidence)
5. **STRIDE doc** (rule 98): Firestore holds real PII (auth identities, leaderboard names, FCM tokens) — 15-minute written pass covering authn/z rules review (Firestore security rules audited against least-privilege), rate/abuse surface (guess submission, leaderboard writes), and data-deletion path.
6. **Perf budget**: meet the ratified budget (own-domain JS ≤ 1000 KB; LCP tracked ≤ 3000ms, target ≤ 2500ms post-pass — this wave is the "post-pass" trigger). Measure with Lighthouse, artifact to reports/ per 65b. Flutter-web levers if over: deferred loading, icon tree-shaking, CanvasKit vs HTML renderer trade-off (evaluate, decide, document — HTML renderer may fix the LCP story entirely for a mostly-2D UI; that's the riskiest/highest-leverage assumption, test it FIRST per rule 77).
7. **Rollback exercised once**: document + actually perform a rollback of a trivial deploy via deploy-warmer.ps1 (deploy N, roll back to N−1, verify, roll forward). Runbook section from the evidence.
8. **Runbook**: docs/runbook.md — deploy, rollback, Firebase console checks, FCM issues, payload-repo sync (mindmeld-payloads), known gotchas from PLAN.md.
9. **E2E in CI**: the launch-check found E2E tests exist but aren't CI-wired. Wire the happy path (load → guess → heat feedback → complete) into CI. Note: mindmeld's plan tier blocks branch-protection APIs — CI runs and reports even if it can't be a *required* check; document the gap.

## Constraints
- Repo = mindmeld (private, stays private). Branch per 35 (`wave-launch-1-*`), PRs per 70a — merges will be human (no protection on this plan tier); open as DRAFT.
- No gameplay/tuning changes in this wave (maxGuesses, embeddings are settled) — paint and gates only. Anything discovered gets logged, not fixed inline.
- All numbers reported with provenance (65b).

## Exit criteria
/launch-check mindmeld re-run at wave end: 8/8 pass (or failures reduced to explicitly-accepted, documented exceptions). That re-run is the wave's acceptance test.
