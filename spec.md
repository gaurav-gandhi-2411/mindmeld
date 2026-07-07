# Mindmeld — Phase 6 Program: Social, Notifications, Packs, Languages

Four capabilities, built in dependency order. This spec fully details **6a (Social)** — the flagship and the foundation — and scopes **6b–6d** as the roadmap. Each later phase gets its own detailed spec when its turn comes.

Guardrail across all four: the solo daily loop must keep working fully with zero backend, offline, and signed-out. Every capability here is ADDITIVE — it never blocks or degrades core play.

---

## 6a — Social: group duel + daily leaderboards (FLAGSHIP, build now)

### Concept
Friends play the same daily secret and compare results on a private, per-group leaderboard shared via a WhatsApp-friendly link. "Aaj aap apne group mein #2 ho." This is the retention + virality engine.

### Auth — no login wall
- Silent **anonymous Firebase Auth** on first social action (not on app open). Solo play needs no account.
- Player sets a **display name** (leaderboard identity) when they first join/create a group. Editable. No email/password.
- Anonymous account also becomes the (optional) home for cross-device streak/stats sync later — out of scope for 6a, but the account is the anchor.

### Groups
- **Create group** → generates a short code + shareable link `playmindmeld.vercel.app/join/{code}` → share to WhatsApp. Creator names the group.
- **Join group** → open link (deep-link handled) or enter code manually.
- A player can belong to **multiple groups**; leaderboards are per-group.
- Group has a member list with display names.

### Daily leaderboard
- On finishing today's puzzle (win OR loss), the player's **result** writes to each of their groups for today: `{uid, displayName, outcome (win/loss), guessesUsed, par, scoreVsPar, lang, finishedAt}`.
- Group leaderboard view: today's members ranked (solvers first by fewest guesses / best score vs par; non-finishers shown as "not played yet" / "didn't get it"). Player's own rank highlighted.
- **Spoiler safety (critical):** the leaderboard shows scores/outcomes ONLY — never guesses, never the word. A member who hasn't played today must not be spoiled by seeing the board.
- Language: leaderboards are per-language-per-day (EN and HI-EN are different puzzles). A group can see both, clearly separated, or default to the viewer's language.

### Firestore data model
```
users/{uid}                     { displayName, createdAt, groupIds[] }
groups/{groupId}                { name, code, createdBy, memberUids[], createdAt }
groups/{groupId}/days/{date}/results/{uid}
                                { uid, displayName, outcome, guessesUsed, par,
                                  scoreVsPar, lang, finishedAt }
codes/{code}                    { groupId }   // for join-by-code lookup
```

### Security rules (must be reviewed before client wiring)
- A user may read a group's data only if their uid is in `memberUids`.
- A user may write ONLY their own `results/{uid}` doc, and only for a valid date; score fields constrained to sane ranges (guessesUsed ≥ 1, par > 0) in rules.
- A user cannot edit another member's result, cannot forge displayName on someone else's doc, cannot add themselves to a group without going through the join flow.
- Group creation/join writes constrained so a user can only add their own uid to `memberUids`.

### Anti-cheat posture (MVP, honest)
- Rules prevent tampering with OTHERS' scores and constrain your own to valid ranges. A determined user could still fake their OWN score by calling the client logic dishonestly. For a friend-group social game this is acceptable (social trust); full server-side validation via Cloud Functions is a later hardening step, noted not built.
- The secret is already hash-keyed in payloads; the leaderboard never transmits the answer.

### UX / degradation
- Entry points: "Play with friends" from home + a share/challenge CTA on the win/loss screen ("challenge your group").
- Signed-out or offline → solo play fully intact; social UI shows a gentle "connect to play with friends" state, never a blocker.
- Deep link `/join/{code}` → if first-time user, onboard → set name → join; if returning, straight to join confirm.

### Acceptance criteria (6a)
1. Anonymous auth provisions silently on first social action; solo play works with no account and offline.
2. Create group → code + link generated; join via link AND via code both work, including first-time-user deep-link path.
3. Multiple group membership; per-group daily leaderboards render ranked, own rank highlighted.
4. Finishing today's puzzle writes the result to all the player's groups; leaderboard updates.
5. Spoiler safety: a not-yet-played member sees no guesses and not the word anywhere in the social UI.
6. Security rules enforce: read only as member, write only own result in valid ranges, no editing others. Rules ship as a file + a test/emulator check.
7. All existing solo tests stay green; social is behind graceful degradation.
8. Live verify on playmindmeld.vercel.app: two browser profiles (two anon users) create/join a group, both play, both see the correct ranked leaderboard, spoiler-safe.

### Manual console steps (GG — CC will provide exact steps + the rules file)
- Firebase console: enable **Cloud Firestore**.
- Enable **Anonymous** sign-in under Authentication → Sign-in methods.
- Deploy the security rules CC generates (console paste or firebase CLI).

---

## 6b — Push notifications (build after 6a)

- **What:** "Today's Mindmeld is live" daily nudge; optional streak-reminder ("your streak ends tonight").
- **Approach:** Firebase Cloud Messaging (FCM) web push via the existing service worker; permission prompt UX (ask at a good moment, not on first load); a scheduled Cloud Function to fan out the daily notification.
- **Key decisions:** iOS web push requires an INSTALLED PWA on iOS 16.4+ — messaging must nudge iOS users to Add to Home Screen first. Android/desktop Chrome work directly. Respect permission denial gracefully; never nag.
- **Manual/cost note:** scheduled Cloud Functions require the Firebase **Blaze (pay-as-you-go)** plan. Generous free tier — effectively $0 at validation scale — but a card on file is required. Enable FCM.
- **Risk:** notification fatigue → strict frequency cap (one daily + optional streak reminder, both user-toggleable).

## 6c — Themed packs (build after 6b)

- **What:** curated themed daily sets — Bollywood, cricket, Indian food, geography, science — as selectable packs. Makes the stubbed **themed-packs IAP** real.
- **Approach:** reuses the entire generator/payload pipeline — each pack is a secret schedule + clues + embeddings, published as its own payload namespace. App gets a pack selector; free daily + premium packs behind IAP (native) / free during web validation.
- **Key decisions:** packs are additional puzzles, NOT a replacement for the core daily (scarcity preserved). Clue authoring per pack is the content lever (CC drafts, GG reviews — same as before).
- **Risk:** content quality per theme; start with 1–2 packs, expand on signal.

## 6d — Regional languages (build last)

- **What:** Tamil, Telugu, Bengali, Marathi editions (romanized), extending the India-language moat.
- **Approach:** generator pipeline reuse with per-language curated vocab, secret schedules, clues, and **eval fixtures** — plus the alias/normalization layer built for Hinglish.
- **Key risk (real):** the multilingual embedding model likely clusters romanized Dravidian/Indic scripts by SCRIPT not MEANING (the exact failure seen with Hinglish). Each language needs its own eval-gated fixture strategy and possibly a better model per language. Validate embedding quality on a small set BEFORE committing full content.
- **Sequencing:** one language at a time, eval-gated, starting with whichever shows the best embedding behavior in a quick probe.

---

## Program principles
- Solo core always works offline/signed-out; every capability is additive.
- Reuse the existing pipeline, hosting, and flags; minimize new surfaces per phase.
- Each phase ships green tests + a live two-condition verification before the next begins.
- Engagement stays Wordle-style (friends, ritual, bragging), never predatory.
