# Warmer — Close-Out

## Goal
Bring Warmer to a genuinely finished, launch-ready state: all work committed and merged, no "coming soon" surfaces, the last human-verifiable checks done, and a clean final launch checklist. Explicitly out of scope: features that need real player data to design well.

## Current state (already done, do not redo)
Full game loop, social/groups, notifications, two live packs (Bollywood, Cricket), rebrand + calm-minimal aesthetic (WCAG AA, both modes), first-session onboarding hook with funnel analytics, security pass (moderation, Firestore rules, data deletion), uptime monitoring with a proven alert loop, WASM-stub remediation + wasm CI lane, byte-verifying hardened deploy, analytics live, known-limitations ledger, and a field-leading published Hinglish model + public benchmark.

---

## WORKSTREAM 1 — Repo hygiene (FIRST; highest risk of loss)
1. Inventory every uncommitted change in the working tree and every unmerged branch. Report what exists before changing anything.
2. Commit the outstanding analysis artifacts (consolidated metrics report, LLM-consensus ceiling report, PLAN.md checkpoint) and the proven `deploy-warmer.ps1` fix if not already in.
3. Merge `feat/hinglish-finetune` (and any other live branch) into `main` — resolve conflicts, run the full suite on the merge commit, confirm both CI lanes (DDC + wasm) green.
4. After merge: byte-verify the live deployment still matches `main`, and confirm no production behaviour changed unintentionally.
5. End state: working tree clean, no unmerged feature branches, `main` == deployed.

## WORKSTREAM 2 — Close the "coming soon" surfaces
Nothing user-facing should say "coming soon" at launch.

### 2a. Puzzle archive
Let players play past dailies. Reuse the existing pack/puzzle machinery. Archive plays must NOT affect the daily streak or daily stats (same isolation the packs already have — prove it with a test). Sensible list UI (date, solved state), reachable from the primary surface.

### 2b. Streak freeze
Complete the partially-scaffolded mechanic (`consumeStreakFreeze` exists). Decide and implement the earning rule (recommend: a small number granted, e.g. earned every N-day streak, capped) — no purchase/IAP. Clear UI: how many you hold, when one is consumed, and an explicit indication that a missed day was covered. Must be correct across timezone boundaries; test day-rollover behaviour.

### 2c. Rival polish (LIGHT ONLY)
Give the rival a name and a small amount of personality (a few reaction lines at key moments — overtaken, close finish, loss). Do NOT build rival leaderboards, personas, or progression: there is no evidence yet that players engage with the rival, and elaborate systems for an unvalidated feature are waste. Keep it cheap and cuttable.

### 2d. Packs
- Build ONE new pack: **Indian Food** — broadest India appeal, proven content pipeline. Follow the established recipe exactly: ~25 common-noun secrets (NO proper nouns), theme in the clue not the secret, embedding-validate every secret (reject dominant-non-food-sense collisions), semantic-neighbour audit on all clues, EN + natively-written Hinglish clues, no duplicates against daily/Bollywood/Cricket, distinct visual accent harmonised with the muted palette.
- **Delete the Nature and Space stubs entirely** — no "coming soon" tiles at launch. They can be added later as pure content drops.
- STOP POINT: print the proposed Indian Food secrets + clues for review before baking.

## WORKSTREAM 3 — Human-verifiable checks (prepare, then hand to GG)
CC's browser automation cannot drive Flutter/CanvasKit interactively. Prepare a short, precise manual checklist for GG with exact steps and expected results, covering at minimum:
- Warm band now actually appears in Hinglish play (the warm_max 900→1050 fix changed what every player sees).
- `junoon` / `registan` read sensibly as guesses.
- Archive, streak freeze, and the new pack work in real play.
- Onboarding → graduation → daily flow on a genuinely fresh profile.
Everything else must be automated/verified by CC.

## WORKSTREAM 4 — Final launch readiness
1. Run the full launch-check gates; report each with evidence.
2. Confirm: uptime monitor active and alerting; analytics events firing (onboarding funnel + daily play); Firestore rules deployed; production DB free of test data; known-limitations ledger current.
3. Confirm every "coming soon" string is gone (grep-clean).
4. Full suite green (Flutter + generator + emulator + both e2e lanes); deploy byte-verified; cold-profile AND existing-user harness pass.
5. Produce a final **launch checklist** for GG listing only the things that genuinely require a human: the GA4 DebugView confirmation, GitHub Issues notifications toggle, and the App Check reCAPTCHA key setup (monitor mode only — do not enforce until real traffic validates).

## Explicitly deferred (document as post-launch roadmap, do NOT build)
- **Any-word guessing** (on-device embedding model): needs a browser-runnable quantised model; heavy; better scoped after real usage.
- **Post-game semantic map** and **LLM content pipeline**: genuine enhancements, not launch blockers.
- **Hinglish model further gains**: both remaining levers (L4 distillation, L6 commonsense data) are data-hungry; the standing best source is real player guess data.
Record these in the roadmap section of the ledger so they're a triaged list, not forgotten ideas.

## Acceptance criteria
1. Working tree clean; all branches merged; `main` == deployed; both CI lanes green.
2. Archive and streak freeze shipped and tested (daily streak provably unaffected by archive play; streak-freeze correct across day rollover).
3. Rival has a name + light reactions; no heavy rival systems built.
4. Indian Food pack live (GG-reviewed content, all gates passed); Nature/Space stubs deleted; zero "coming soon" strings remain.
5. Full suite green; deploy byte-verified; cold + existing-user harness pass.
6. Manual checklist delivered to GG (short, exact steps, expected results) covering only what automation genuinely cannot do.
7. Deferred items recorded as a roadmap, not silently dropped.

## Risks
- **Streak-freeze correctness** — timezone/day-rollover bugs here silently destroy player streaks; test hard.
- **Archive polluting daily stats** — must be isolated exactly like packs; prove with a test.
- **Scope creep on the rival** — keep it light; it is unvalidated.
- **Merge drift** — a long-lived branch merged late can silently change production; byte-verify after merge.
