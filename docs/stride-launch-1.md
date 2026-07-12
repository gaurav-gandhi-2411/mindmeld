# STRIDE Threat Model — Launch Pass 1

Scope: per `CLAUDE.md` rule 98 ("threat-model any change touching auth, money, or PII: a
15-minute STRIDE pass, written down"), applied proportionately to Warmer's actual
surface — a free, casual friend-group word game with Firebase anonymous auth + Firestore,
no payments, no health data. This is a launch-readiness pass triggered by `/launch-check`
gate 3, not an enterprise security audit. Every claim below cites the file/line it's based
on; residual risks already accepted are cited from `docs/known-limitations.md` rather than
re-derived.

Surfaces covered, as requested: (a) Firebase anonymous auth + Firestore identity model,
(b) the leaderboard/results write path (`groups/{groupId}/days/{date}/results/{uid}`),
(c) group membership/join-by-code flow, (d) the data-deletion path
(`SocialService.deleteMyData()`).

Sources read for this pass: `firestore.rules` (full file), `docs/known-limitations.md`,
`app/lib/social/social_service.dart`, `app/lib/social/social_client.dart`,
`app/lib/social/name_sanitizer.dart`, `app/lib/social/moderation_blocklist.dart`,
`firebase-tests/rules.test.js`, `PLAN.md`'s "maxGuesses tuning + security/hardening pass"
section.

## Trust model (stated once, applied throughout)

Every player is an anonymous Firebase Auth identity (`signInAnonymously`, see
`social_service.dart:301-312`). There are no passwords, emails, or real-world identifiers
collected — `users/{uid}` stores only `displayName` (self-chosen, moderated) plus
notification prefs (`firestore.rules:6-8`). The trust boundary the rules and moderation
are actually designed around is stated explicitly in the rules file header: "friend-group
social trust... a user forging their own client-reported score is an accepted MVP risk,
not a hole these rules try to close" (`firestore.rules:14-17`). This STRIDE pass evaluates
against that stated boundary, not an adversarial-stranger threat model — inventing
bank-grade threats for a casual game with no stakes would be disproportionate.

---

## Spoofing

**Risk:** could an attacker impersonate another player or forge which uid a write comes
from?

- Firestore rules make this structurally impossible for every write path examined:
  `users/{uid}` create/update requires `request.auth.uid == uid` (`firestore.rules:102-103`);
  `results/{uid}` create requires `uid == request.auth.uid` AND
  `request.resource.data.uid == request.auth.uid` (`firestore.rules:216-217, 223`); group
  join/self-removal updates are structurally self-only (`isJoinUpdate()`/
  `isSelfRemovalUpdate()`, `firestore.rules:170-187`). A result's `displayName` field must
  also match the writer's own `users/{uid}.displayName` (`firestore.rules:224-225`),
  closing a forged-name-in-leaderboard vector — verified tested in
  `firebase-tests/rules.test.js:324-331` ("displayName must match your own profile (no
  forging)").
- Anonymous-auth identity itself can be reset by clearing browser storage (mints a new
  uid), but that only lets someone spoof "a new player," never take over an existing
  identity or forge writes as someone else — no session/token theft surface exists beyond
  standard Firebase Auth token handling, which is out of this app's control surface.
- **Residual/accepted:** none new. This category is well-covered by the existing rules
  and their tests.

## Tampering

**Risk:** could a player alter data they don't own, or rewrite their own past record?

- Non-owner tampering is denied by the same uid-equality rules as Spoofing above.
- Same-owner tampering (rewriting your own result after seeing the leaderboard) is denied
  by CREATE-ONLY semantics: `allow update: if false` on `results/{uid}`
  (`firestore.rules:239`), tested at `firebase-tests/rules.test.js:356-363` ("a result is
  CREATE-ONLY — overwriting your own result fails"). Group name/code/createdBy are pinned
  immutable across join/leave updates (`firestore.rules:191-193`).
  `codes/{code}` is immutable after creation (`allow update, delete: if false`,
  `firestore.rules:135`, tested at `rules.test.js:230-232`).
- Field-level tampering (out-of-range scores, extra smuggled fields) is bounded: 1–200
  guesses, ±200 score, enum-constrained `outcome`/`lang`
  (`firestore.rules:226-236`), and a `keys().hasOnly([...])` allow-list on every
  create/update path closing the "smuggle an extra top-level field" gap found in the
  2026-07-11 re-audit (`firestore.rules:94-101, 154-156, 220-222`).
- **Accepted residual (cited, not new):** a user can still self-report a fabricated
  win/score within the bounded ranges — `docs/known-limitations.md` entry 5
  ("Self-reported leaderboard scores (client trust)"). The payload's secret is only
  soft-obfuscated against a determined debugger user — entry 6 ("Soft payload
  anti-cheat"). Both are explicitly accepted for a friend-group, no-stakes game.

## Repudiation

**Risk:** could a player deny having taken an action, or could the system fail to
attribute an action to its actor?

- Low relevance for this product — there is no dispute-resolution or moderation-action
  workflow where "who did this" needs to be provable to a third party (no in-app
  reporting/banning system exists to audit against). `finishedAt` is server-timestamped
  (`request.time`, never backdatable — `firestore.rules:237`), so at minimum every result
  has a trustworthy server-side write time even though its content is self-reported.
  Firebase's own Firestore audit logs (infra-level, not app-level) exist independent of
  this app's code.
- **No new gap identified.** Not pursuing further — proportionate to a game with no
  moderation-appeals or financial-dispute surface.

## Information Disclosure

**Risk:** could a player see another player's or another group's data they shouldn't?

- `users/{uid}`: `get` is open to any signed-in user but requires already knowing the
  target uid (`firestore.rules:90`); `list` is denied entirely (`firestore.rules:91`), so
  the user collection can never be enumerated/browsed. A uid is only ever learned via a
  group's `memberUids` — never independently discoverable.
- `groups/{groupId}`: `get` is open to any signed-in user holding the groupId (not
  membership-gated) — the rules file itself flags this explicitly as a documented,
  accepted consequence: "the member roster (uids) and, transitively... their display
  names are visible to anyone with a join link/code, whether or not they ever join"
  (`firestore.rules:142-150`). `list` (queries) IS membership-gated, so groups cannot be
  enumerated at large (`firestore.rules:152`, tested at `rules.test.js:238-243`).
  Accepted because groupId is only ever learned via an unguessable code lookup or
  existing membership, and the doc holds no puzzle/spoiler content.
- `codes/{code}`: `get` (single-doc resolve) is open to any signed-in user
  (`firestore.rules:125`), but `list` is denied (`firestore.rules:126`) — codes can't be
  enumerated/brute-forced via a query, only resolved one at a time if you already have the
  exact string. Given codes are the join mechanism (effectively a bearer credential), the
  real defense against guessing is code-space size/entropy — this pass did not verify the
  code generator's entropy/length (out of the file set assigned); flagged below as a
  candidate follow-up, not a confirmed gap.
- `results/{uid}` (leaderboard/scores): `get`/`list` require group membership
  (`isMember()`, `firestore.rules:205`), tested for both the positive case
  (`rules.test.js:364-366`) and the negative case — a non-member is denied
  (`rules.test.js:367-370`, "spoiler-safety at the rules layer"). The doc's own data model
  never stores guesses or the secret word (`firestore.rules:10-11` header comment), so
  even a membership breach couldn't leak puzzle spoilers — spoiler-safety is enforced
  structurally by what's never written, not just by access control.
- **Accepted residual (cited):** the groups/{groupId} get-by-id exposure above is the
  rules file's own documented trade-off, not new. Homoglyph/impersonation coverage in
  display names is best-effort — `docs/known-limitations.md` entry 10.

## Denial of Service

**Risk:** could a player degrade the service for others or rack up abusive volume?

- No player-controlled fan-out exists: a result write is one document per group per day,
  create-only (denied on retry) — there is no loop or bulk-write primitive exposed to a
  malicious client beyond "create your own group" and "create your own result," both
  already bounded to one row per key.
- No rate limiting exists in `firestore.rules` today (confirmed — no `request.time`-based
  throttling, no per-uid write-count caps anywhere in the file) — this matches the
  `/launch-check`'s callout verbatim. See "Rate/abuse surface" section below for the
  concrete assessment of whether this matters given what's actually writable.
- App Check is wired at both Firebase init call sites (`ensureAppCheckActivated()` called
  from `social_service.dart:257, 268`) but left in metrics-only/unenforced mode pending a
  manual reCAPTCHA site-key registration step — cited, not re-derived, from
  `docs/known-limitations.md` entry 11. This is the primary planned DoS/bot mitigation for
  this product and is a known pending gap, not a silent one.
- **Accepted residual (cited):** App Check monitor-mode (entry 11).
- **New observation (see Rate/abuse surface section below):** the *absence* of Firestore
  rate limiting is real, but the actual abuse surface it would guard is narrow given the
  one-row-per-key write shape — detailed below rather than restated here.

## Elevation of Privilege

**Risk:** could a regular player gain group-admin, cross-group, or system-level
capabilities they shouldn't have?

- There is no privilege tier in this product's data model — no `isAdmin`/`role` field
  exists on any document read in this pass, no group-owner-only capability beyond
  `createdBy` (an informational field, not a permission gate — group creation, join, and
  self-removal all use the same uid-equality rule regardless of who created the group).
  A "moderator"/"admin"/"staff"/"official"/"system" *display name* cannot be claimed by an
  ordinary user (blocked by `moderation_blocklist.dart`'s `reservedWords` list,
  `moderation_blocklist.dart:34-43`), preventing social-engineering impersonation of
  authority that doesn't otherwise exist server-side.
- Default-deny closes the class entirely for anything not explicitly matched: `match
  /{document=**} { allow read, write: if false; }` (`firestore.rules:257-258`).
- **No new gap identified.** There is no privilege boundary to escalate across in this
  product today.

---

## Rate/abuse surface (launch-check callout)

The launch-check flagged "zero rate limiting found in firestore.rules" as a gap to
specifically address. Assessed against what a malicious/scripted client can actually do,
write-path by write-path:

1. **Guess submission is NOT a Firestore write at all.** Confirmed by reading
   `app/lib/social/social_client.dart` and `social_service.dart` in full: the only
   Firestore write related to gameplay outcome is `writeResultToAllGroups()`
   (`social_service.dart:476-513`), which fires exactly once per finished puzzle and
   writes one document per group the player belongs to (`social_client.dart:264` /
   `writeResult`). `guessesUsed` is a bounded scalar *field* on that single result
   document (`firestore.rules:227-229`, range 1–200), not a stream of per-guess writes —
   gameplay/guessing itself is entirely local/client-side with no network round-trip per
   guess. **This means "guess submission rate limiting" is a non-issue as stated in the
   launch-check** — there is no per-guess write to rate-limit in the first place.
2. **Result writes are self-throttling by design.** `results/{uid}` is CREATE-ONLY per
   `(groupId, date, uid)` (`firestore.rules:216, 239`) — a script cannot write more than
   one result per group per day for a given uid; every retry after the first is denied,
   not merely discouraged. There is no volume to rate-limit beyond "one write succeeds,
   the rest 403."
3. **Group/code creation has no cap.** A scripted anonymous-auth client CAN mint unlimited
   uids (each a fresh `signInAnonymously()` call) and unlimited `groups/{groupId}` +
   `codes/{code}` documents, one pair per script iteration — this is the one genuinely
   uncapped write path in the rules file. Impact is Firestore storage/cost growth and
   junk-group clutter, not a data-integrity or privacy breach (an attacker gains no
   access to any other user's data by doing this). This is a real, previously-undocumented
   gap — **new finding**, see below.
4. **Profile writes (`users/{uid}`) have no per-uid throttle** either, but are capped in
   *effective* blast radius: one document per uid, `update`/`create` just overwrite the
   same doc — no fan-out, no growth vector beyond field-size limits already enforced
   (`fcmToken` ≤4096 chars, `firestore.rules:71`).

**Verdict:** the launch-check's "zero rate limiting" observation is factually correct, but
the practical exposure is narrow: guess-level abuse is a non-issue (no write exists to
abuse), and result-level abuse is already capped to 1/day/group by the rules' create-only
constraint. The one real uncapped vector is **unbounded group/code document creation by a
scripted client** (item 3) — a resource-exhaustion/cost-growth risk (Firestore
read/write billing, junk data), not a confidentiality or integrity risk, since group docs
carry no sensitive content and rules already prevent cross-group data leakage. Mitigating
this properly needs either Firebase App Check enforcement (already wired, pending the
site-key registration in `docs/known-limitations.md` entry 11 — the natural first line of
defense once flipped from monitor to enforced) or a Cloud Function-based per-uid
creation throttle (real infra work, not a rules change, and not scoped for this pass).
**Recommendation:** treat App Check enforcement (entry 11) as the primary mitigation once
its manual prerequisite lands; do not build a separate rate-limiting mechanism ahead of
that unless abuse is actually observed (matches this doc's own "revisit if" pattern used
throughout `known-limitations.md`).

## Data-deletion path

Walking `SocialService.deleteMyData()` (`app/lib/social/social_service.dart:583-614`) step
by step against its own doc comment (`social_service.dart:546-565`):

1. **Best-effort: delete every past result doc.** `_client.deleteOwnResultsBestEffort(uid)`
   (`social_service.dart:593`) runs a `collectionGroup('results').where('uid', '==', uid)`
   query (`social_client.dart:357`) and deletes each match. Failures here are caught and
   logged, non-fatal (`social_service.dart:594-598`) — by design, since this specific step
   needs a one-time Firestore collection-group composite index provisioned in production
   before it can succeed at all, cited from `docs/known-limitations.md` entry 12 ("Data-
   deletion result-doc cleanup needs a one-time Firestore index"). Firestore rules permit
   this: `allow delete: if isSignedIn() && uid == request.auth.uid` on `results/{uid}`,
   deliberately NOT membership-gated so it still works after step 2 removes group
   membership (`firestore.rules:241-250`).
2. **Leave every group** (remove own uid from `memberUids`) via
   `removeSelfFromGroup()` for each group in `myGroups(uid)`
   (`social_service.dart:601-603`), permitted by `isSelfRemovalUpdate()`
   (`firestore.rules:182-187`).
3. **Delete the `users/{uid}` profile doc** (`social_service.dart:605`), permitted by
   `allow delete: if isSignedIn() && request.auth.uid == uid` (`firestore.rules:115`).
4. **Clear the locally-cached display name** (SharedPreferences,
   `social_service.dart:611-612`).
   Steps 2–3 failing is treated as `DeleteMyDataStatus.offline`
   (`social_service.dart:606-609`) — i.e. the UI is told deletion did NOT fully succeed,
   whereas step 1 failing alone still reports `success` (explicitly best-effort, per its
   own doc comment). This ordering (results → membership → profile) is intentional: the
   collection-group query in step 1 still sees valid membership context before it's
   removed in step 2.

**Confirm/deny complete:** the code path is complete and matches its documentation —
server-side profile, membership, and (best-effort) result-history removal, plus local
cache clearing, in a defensibly-correct order, with correctly differentiated
success/failure semantics for the best-effort vs. must-succeed portions. The ONE gap is
external to this code: entry 12's one-time production index, which is an infra/console
step (cannot be fixed by a code or rules change), and is already tracked with an explicit
manual-action owner. **No new gap found here** — this matches `docs/known-limitations.md`
entry 12 exactly; not restating it as new.

---

## Summary of findings

| Category | Verdict |
|---|---|
| Spoofing | Well-mitigated by uid-equality rules; no gap |
| Tampering | Well-mitigated by create-only + range bounds; residual is the accepted self-reported-score risk (`known-limitations.md` #5, #6) |
| Repudiation | Low relevance for this product; no gap |
| Information Disclosure | Well-mitigated; one already-documented, accepted trade-off (`groups/{groupId}` get-by-id exposure, #10 for homoglyphs) |
| Denial of Service | No per-guess write exists (confirmed); result writes self-capped at 1/day/group; **new finding: unbounded group/code creation by a scripted anonymous client** (cost/clutter risk, not data risk) — mitigate via App Check enforcement (#11) once its manual prerequisite lands, not a new mechanism |
| Elevation of Privilege | No privilege tiers exist in this product; default-deny closes the rest; no gap |
| Rate/abuse surface | Launch-check's specific worry (guess-level rate limiting) is a non-issue — guesses never touch Firestore. Real residual is bounded group/code creation volume, tracked above |
| Data-deletion path | Complete and correctly ordered; the one known gap (result-doc index) is already tracked in `known-limitations.md` #12, not new |

**Net new item from this pass:** unbounded `groups/{groupId}` + `codes/{code}` document
creation by a scripted anonymous-auth client has no Firestore-rules-level cap today. Low
severity (cost/storage growth, no data exposure), no evidence of active abuse, and the
existing plan (App Check enforcement once entry #11's manual prerequisite lands) is the
right-sized mitigation — recommend folding this into `docs/known-limitations.md` as a
follow-up entry alongside #11 rather than building bespoke rate-limiting ahead of an
observed need, consistent with this document's `known-limitations.md`'s own "why
accepted" / "revisit if" pattern.
