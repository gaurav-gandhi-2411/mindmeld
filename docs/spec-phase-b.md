# Warmer (mindmeld): Phase B spec, restore and harden

Owner: GG. Executor: Claude Code (Opus 5.5 orchestrator, executor + verifier subagents, sequential).
Repos: `gaurav-gandhi-2411/mindmeld` (private → public in P6), `gaurav-gandhi-2411/mindmeld-payloads` (public, GitHub Pages CDN).
Live: https://playwarmer.vercel.app. Firebase/GCP: `warmer-prod-260813` (live), `mindmeld-c4bba` (legacy).
Date: 2026-11-01. Hard deadline: P3 complete before 2026-11-10 (GCP credit expiry).

## 1. Context (verified in Phase A)

- No daily puzzle since 2026-08-19. Root cause: payloads were only ever generated manually (`publish_all.py --days 68`) and ran out after 2026-08-18. No generator automation existed.
- Private-repo Actions blocked since ~2026-10-03. The 15-minute uptime cron alone consumes ~2,880 of 2,000 free minutes/month.
- Uptime check broken since 2026-07-25 (manifest lost `en`). It never checks today's date. Issue #12 has 1,003 duplicate comments.
- warmer-prod: no Firestore rules released (social features likely fully denied). Billing enabled. Web key has no referrer lock.
- c4bba Firebase Auth SCRYPT signer key is in plaintext in untracked `ops/runbooks/clean-break-migration.md:64`. `data/` and `ops/` are not gitignored.
- Generator defects: `publish.py:138` skips `apply_devanagari_patch`; HF models not revision-pinned; EN vocab contains offensive terms usable as guesses and plaintext hints; rank-50 collision on 8 hi-en days (believed).
- Only 68 secrets per language; any date after 2026-08-18 repeats an old puzzle.
- Main CI red since 2026-08-15 (`e2e-web-wasm` npm ci; suspected missing setup-node, Node ≥22.12).

## 2. GG decisions (all approved 2026-11-01)

| ID | Decision |
|---|---|
| D1 | Publish payloads 2026-10-31 → 2026-11-30 to mindmeld-payloads, with generator fixes. CC may merge after verifier passes. |
| D2 | Deploy repo `firestore.rules` to warmer-prod after emulator tests pass. |
| D3 | CC adds HTTP-referrer locks to both web keys via gcloud; verify real sign-in afterwards. |
| D4 | Revert warmer-prod to Spark (unlink billing) unless a Blaze-only dependency is found. |
| D5 | Make mindmeld public after prerequisites in P6. |
| D6 | Delete mindmeld-c4bba (30-day recovery) unless the reason for the "55b" undelete still applies. |
| D7 | Hinglish is a co-headline feature; GoatCounter analytics approved (implementation in a later phase). |

## 3. Non-negotiables

- Zero spend. No paid tiers, no new paid services, never set `ANTHROPIC_API_KEY`.
- Never print key material, password hashes, or user document contents. Never run `get-key-string` or `firebase auth:export`.
- Published payload dates are immutable once merged. Never regenerate or overwrite a published date.
- Sequential execution. One working tree per repo. Remove worktrees after merge. Report disk footprint at the end.
- Stop and report before any Vercel `--prod` deploy (not approved in this phase).
- Any "verified" claim needs evidence (command + output summary). Otherwise label it "believed".

## 4. Phases, acceptance criteria

### P0: Local hygiene (no production effect)
- Primary checkout → `main` at origin. Re-verify the eval/embedding-separation WIP is byte-identical to main, then discard it.
- `.gitignore`: `data/firestore_export*`, any `*auth*export*`, `*.hash*` exports.
- Redact SCRYPT signer key line in the runbook (replace with a pointer to Firebase console > Authentication > Password hash parameters). Correct the "c4bba deleted" status line. Add a missing step: "deploy firestore.rules". Commit the runbook on a PR.
- Search for auth export files containing password hashes in: the repo, `C:\Users\gaura\ml-projects\`, `Downloads`, `%TEMP%`. Report paths only. Do not open or delete them.
- **Accept:** `git check-ignore` proves the export dir is ignored. `git grep` finds no signer key on any branch.

### P1: Restore the daily puzzle (D1)
- Generator fixes first, each with a test: Devanagari patch in `publish.py`; pin HF `revision` for both models (cache key includes revision); expand blocklist (EN: a maintained list such as LDNOOBW, plus hi-en slurs) applied to both guessable vocab and hints; verify the rank-50 collision with a failing test, fix if confirmed.
- Generate ONLY 2026-10-31 → 2026-11-30, both languages, in a temp dir. Restore `en` in the manifest.
- Verifier: every new file decodes; the answer is in vocab; ranks are unique and contiguous; no blocklisted word in vocab or hints; no published date (≤ 2026-08-18) is modified (byte diff = 0 for existing files).
- PR on mindmeld-payloads. Merge after verifier passes. Confirm 200 from Pages for 10-31, 11-01, 11-30 in both languages, plus a headless load of playwarmer.vercel.app showing a puzzle.
- **Accept:** a live puzzle is rendered (screenshot) and all checks above pass.

### P2: Firestore rules (D2)
- Run the firebase-tests emulator suite against `firestore.rules`. Confirm rules cover all live collections (users, groups/*/days, results, codes).
- `firebase deploy --only firestore:rules --project warmer-prod-260813`.
- **Accept:** release visible via API; an authorised test path passes in the emulator; unauthenticated write denied in prod.

### P3: Keys and billing (D3, D4); deadline 2026-11-10
- Inventory Blaze-only usage on warmer-prod (Cloud Functions, Storage beyond free, scheduled exports, Extensions). If none, unlink billing. If any, stop and report.
- Referrer locks on both web keys: `playwarmer.vercel.app/*`, `warmer-prod-260813.firebaseapp.com/*`, `localhost:*`. Check Vercel preview domains are needed; add only if used.
- Auth providers: count users per sign-in provider on warmer-prod using an Admin SDK listing that prints provider IDs only. Report the number of email/password users. Remediation is GG's decision later.
- **Accept:** `api-keys describe` shows referrers; headless sign-in on the live site succeeds; billing state shows disabled.

### P4: Monitoring (in public mindmeld-payloads)
- New workflow, hourly: for both languages check UTC yesterday/today/tomorrow return 200 and decode. Runway warning when fewer than 14 future days are published.
- One alert issue, opened on failure, auto-closed on recovery, no comment spam.
- Disable mindmeld's 15-min `uptime-check`. Close #12 with a summary comment (text shown to GG before posting).
- **Accept:** a forced-failure test (bad date) opens the issue; recovery closes it.

### P5: Decommission c4bba (D6)
- Find the "55b" incident/rule and report why c4bba was undeleted. If the reason still applies, stop.
- Confirm zero references in the live bundle, main, and Vercel env. Then `gcloud projects delete mindmeld-c4bba`.
- **Accept:** project state DELETE_REQUESTED; recovery deadline reported.

### P6: Public cutover (D5)
- Prerequisites: P0, P3 done; full-history secret scan re-run clean except the referrer-locked web keys; LICENSE (MIT) plus `THIRD_PARTY.md` (MiniLM Apache-2.0, l3cube base CC-BY-4.0, wordfreq licence); README stale claims corrected (old hi-en model name, "9x separation", "−0.003 → 0.813" → like-for-like 0.435 → 0.704, vocab counts).
- `gh repo edit --visibility public --accept-visibility-change-consequences`.
- Enable Dependabot alerts, secret scanning, push protection, and branch protection on main (required checks).
- **Accept:** API shows public + protections; Actions jobs start (no billing message).

### P7: CI repair, fallback, PR backlog
- Fix `e2e-web-wasm` (add setup-node with a pinned version). Fix the stale test (`143 == 118` → derived count). Stop the test suite from rewriting tracked files.
- B2: if today's payload is missing, load the latest available one and label it ("Puzzle from <date>"). Never show a blank error. Widget + unit tests.
- Resolve PRs #19, #21, #24, #29, #30 (rebase, merge if green). Remove the extra worktree after #24.
- Merge authority: CC may merge mindmeld PRs with all required checks green. **Stop before any Vercel prod deploy** and ask GG.
- **Accept:** main CI green; B2 merged; deploy pending GG approval.

## 5. Out of scope for this phase (next spec)

- Secret pool ≥365 curated secrets per language, with a simulated-solver solvability eval and LLM-consensus quality review; automated generator workflow. Must land before ~2026-11-23 (P4 runway warning).
- Server-side rank lookup to hide answers (free-tier Vercel function), needed before leaderboards matter.
- Growth features: WhatsApp share, streaks, archive, per-puzzle OG image, GoatCounter, themed Hinglish days.
- npm (47) and pip (40) vulnerability remediation beyond what Dependabot merges.

## 6. Reporting

Per phase: what was done, evidence, numbers, what changed, what remains, verified vs believed. Stop after each phase only on a failed acceptance criterion or a stop condition. Otherwise continue. Final: disk footprint, worktrees created/removed, scratch removed.
