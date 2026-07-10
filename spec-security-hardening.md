# Warmer — maxGuesses Tuning + Security/Hardening Pass

Two launch-readiness workstreams in one pass: (1) fix the guess-budget formula the eval flagged, (2) a real security + hardening audit before the app goes in front of strangers.

---

## PART 1 — maxGuesses tuning (eval-gated)

### The finding (Dimension 5)
Current `maxGuesses = par + 6` (fixed offset) yields median simulated win-rate **92%**, only 10.9% of puzzles in the target 75–85% band. Low-par puzzles are trivially winnable (par 6 → 12 guesses). The budget should scale WITH par, not add a constant.

### Fix
- Reformulate `maxGuesses` to scale with par (e.g. `round(par × k)` or a blend), with a sensible floor so very-low-par puzzles still give reasonable room (don't make short puzzles brutal — the earlier UX lesson).
- **Tune k against the Dimension 5 win-rate simulation** — don't guess the formula, iterate it in the harness until median simulated win-rate lands ~78–82% with the bulk of puzzles in 75–85%. Report the chosen formula + resulting distribution.
- Keep it forgiving enough that a competent player wins most days (score, not win/lose, is the flex) — target median ~80%, not lower.
- Regenerate all payloads (daily + Bollywood + Cricket, both langs) with the new maxGuesses; gates pass; byte-reproducible.

### Caveat to honor
Win-rate is a SIMULATION (embedding-guided synthetic players); real human rates will differ. Treat the target as a model estimate to validate with real players post-launch — don't over-tighten on the model alone.

### Part 1 acceptance
1. New maxGuesses formula scales with par + floor; chosen k reported.
2. Dimension 5 re-run: median simulated win-rate ~78–82%, majority in 75–85%; distribution reported.
3. Payloads regenerated; all gates pass; EN + hi-en both.
4. Live spot-check: a low-par puzzle no longer gives an absurd budget; a normal puzzle feels fair.

---

## PART 2 — Security + hardening pass

Scope is realistic launch-security for a consumer game, not enterprise pen-testing. Priorities below.

### 2.1 User-generated content: validation + moderation (highest priority)
Display names and group names are user-chosen and shown to OTHER players in leaderboards — the main untrusted-input surface.
- **Sanitize at write time:** enforce length (already in rules), strip control chars, zero-width, and RTL/bidi-override characters; normalize unicode; reject/replace homoglyph abuse.
- **Injection-sink audit:** Flutter web renders the main UI to canvas (mitigates classic DOM XSS), but VERIFY user content never reaches a dangerous sink — FCM notification title/body, any HTML surface, url_launcher targets, deep-link construction, analytics params, or the GitHub-Action/Admin-SDK path. Confirm each sink treats names as data, not markup/URL.
- **Moderation:** a profanity/abuse blocklist (EN + Hinglish) on display names and group names, applied at write time with a friendly rejection. Block impersonation-flavored reserved words (admin, official, moderator). This is content shown to strangers — it needs a filter.
- Enforce what can be enforced in Firestore rules (length/charset); do the richer moderation client-side at write with a server-consistent list.

### 2.2 Firestore rules re-audit
- Re-review ALL rules since the 6a review — especially the NOTIFICATION fields added to `users/{uid}` (fcmToken/notifLang/timezone/notifPendingAction): confirm a user can only write their OWN, fields are type/'value-constrained, and no unintended field writes are allowed.
- Confirm packs added no new collections needing rules (pack progress is local/SQLite, not Firestore — verify).
- Re-confirm: no collection falls through to default-allow; the codes/{code} squatting note; create-only on results still holds.
- Add/expand emulator rule tests for the notification-field writes.

### 2.3 App Check (abuse prevention — the main lever)
Anonymous auth lets anyone mint accounts freely → scripted abuse of Firestore/FCM (fake leaderboard members, group spam, token spam) is currently unmitigated (App Check confirmed DISABLED earlier).
- Wire Firebase **App Check with reCAPTCHA v3** (web) into the client.
- Enable in **monitor mode first** (measure, don't block) to avoid false-positive lockouts of real users, then move to enforcement once metrics look clean.
- MANUAL (GG): create the reCAPTCHA v3 site key + register it in Firebase console App Check; CC provides exact steps and wires the SDK. Do NOT enforce-block until monitored.

### 2.4 Secret & credential handling audit
- Confirm `FIREBASE_SERVICE_ACCOUNT` (full admin cred) exists ONLY as a GitHub secret, is never echoed in workflow logs, and is not committed anywhere in history (git log scan).
- Scan the repo/history for any accidentally committed private keys / service accounts / RevenueCat secret keys.
- Explicitly NOTE (so no one "fixes" a non-issue): the Firebase WEB config and the VAPID PUBLIC key are meant to be client-public — they are not secrets and must stay in the client.

### 2.5 Dependency vulnerabilities
- Run `npm audit` (SW build, puppeteer harness, firebase-admin sender script), `dart pub` outdated/audit, and a Python audit (pip-audit) on the generator. Fix criticals/highs; report anything deferred with reason.

### 2.6 Privacy / data deletion (Play + GDPR)
- Confirm the privacy policy is accurate post-notifications/packs (data collected: anon uid, display name, FCM token, timezone, analytics).
- **Data deletion path:** anonymous users have Firestore docs (users/, group memberships, results). For Play data-safety/GDPR, provide a deletion mechanism — at minimum an in-app "delete my data" that removes the user's Firestore docs + local state, or a documented request path. Confirm what's feasible and implement the simplest compliant option.

### 2.7 Accepted-risk ledger (document, don't fix)
- Self-reported leaderboard scores (client-trust; server validation deferred to Cloud Functions).
- Soft payload anti-cheat (secret hash-keyed + XOR reveal; extractable by a determined user — fine for casual).
State these explicitly so they're conscious decisions, not blind spots.

### Part 2 acceptance
1. Display/group names sanitized + moderated at write (length, charset, bidi/zero-width strip, profanity EN+Hinglish, reserved-word block); friendly rejection; tests.
2. Injection-sink audit done; report each sink (notification, URL, HTML, analytics, Admin-SDK) confirmed safe.
3. Firestore rules re-audited incl. notification fields; emulator tests expanded; no default-allow; report.
4. App Check wired (reCAPTCHA v3, web) in MONITOR mode; manual console steps listed for GG; not enforcing yet.
5. Secret audit clean (service account only in GH secret, not in history/logs; no private keys committed); web-config/VAPID-public noted as intentionally public.
6. Dependency audits run; criticals/highs fixed or deferred-with-reason.
7. Data-deletion mechanism implemented (in-app or documented); privacy policy confirmed accurate.
8. Accepted-risk ledger written.
9. All tests green; live-verify nothing broke (cold + existing-user harness); commit, push, deploy.

## Manual steps (GG)
- App Check: create a reCAPTCHA v3 site key, register it in Firebase console → App Check, keep it in MONITOR (not enforce) mode initially. CC provides exact steps.

## Risks
- **App Check false-positives** — enforcing too early can lock out real users; monitor-first is mandatory.
- **Moderation over-blocking** — a too-aggressive profanity list rejects legit names (esp. Hinglish false-positives); tune conservatively.
- **Scope creep** — this is realistic launch-security, not a full audit; keep server-side score validation and deep pen-testing out of scope (ledger them).
