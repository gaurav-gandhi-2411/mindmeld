# Accepted Risks — Launch Security Ledger

Written as part of the 2026-07 security-hardening pass (`spec-security-hardening.md`). Scope is
realistic launch-security for a consumer word game with a friend-group social layer — not an
enterprise threat model. These are conscious decisions with stated reasoning, not blind spots.
Each entry names what it is, why it's accepted, and what would change the calculus.

## 1. Self-reported leaderboard scores (client trust)

`groups/{groupId}/days/{date}/results/{uid}` documents (`outcome`, `guessesUsed`, `par`,
`scoreVsPar`) are written directly by the client with no server-side recomputation. Firestore
rules bound the values to sane ranges (1–200 guesses, ±200 score) and enforce create-only (no
revising a score after seeing the leaderboard), but a technically determined player could still
report a fabricated win for themselves.

**Why accepted:** the trust boundary is a friend group, not strangers — the "victim" of a faked
score is the cheater's own friends, who can already see it's implausible. Closing this requires a
Cloud Function to validate/write results server-side (verifying the guess sequence against the
day's real payload), which is real infrastructure work with no scoped ticket yet.

**Revisit if:** groups stop being friend-only (e.g. public/global leaderboards ship), or abuse
reports actually surface.

## 2. Soft payload anti-cheat (extractable secret)

The daily/pack secret is embedded in the payload as a hash-keyed, XOR-obfuscated field (`s`) —
enough to stop a casual "view source" spoiler, not enough to stop a determined user with a
debugger from deriving the secret before playing.

**Why accepted:** this is a casual single-player-against-a-model word game, not a competitive
integrity-critical system. The "cost" of cheating is spoiling your own puzzle for yourself; there's
no reward or leaderboard stake large enough to justify real DRM-grade obfuscation.

**Revisit if:** the game ever ships a stakes-bearing competitive mode (money, ranked ladders).

## 3. `npm audit` — 5 moderate transitive findings, deferred

`firebase-tests/` (the Firestore rules-emulator + puppeteer test harness — dev/test tooling, not
shipped code) has 5 moderate-severity transitive advisories via `firebase-tools` →
`@google-cloud/pubsub`/`gaxios` (GHSA-8988-4f7v-96qf unbounded memory allocation in
`@opentelemetry/core`; GHSA-w5hq-g745-h8pq buffer bounds check in `uuid`).

**Why accepted:** the only available fix (`npm audit fix --force`) downgrades `firebase-tools`
from `^15.22.4` to `14.23.0` — a regression, not a forward patch. Below the critical/high bar, and
this package never runs against production traffic (local emulator + puppeteer only).

**Revisit if:** `firebase-tools` ships a patch release that clears these without a downgrade.

## 4. `pip-audit` — torch CVE-2025-3000, no fix available, deferred

`torch` (a `sentence-transformers` dependency in `generator/`) has GHSA-rrmf-rvhw-rf47 /
CVE-2025-3000 (memory corruption via `torch.jit.script` on attacker-controlled input). GitHub's own
severity rating is LOW (the "critical" language circulating is a disputed VulDB classification);
OSV lists no fixed version — it affects all releases through current.

**Why accepted:** the generator only calls `sentence-transformers` to embed a fixed, curated
internal vocabulary — it never calls `torch.jit.script` on untrusted/attacker-controlled input.
The vulnerable code path isn't reachable from anything this project does with torch.

**Revisit if:** a fixed torch release ships, or the generator ever scripts a model against
user-supplied text.

## 5. Flutter Firebase SDK family — one major version behind

`firebase_core`/`firebase_auth`/`cloud_firestore`/`firebase_analytics`/`firebase_crashlytics`/
`firebase_messaging` are all one major version behind current stable (e.g. `firebase_core`
3.15.2 → 4.11.0 available). No specific CVE evidence found for the pinned versions — this reads as
routine JS-SDK-modularization API churn, not an unpatched exploit.

**Why accepted:** all six packages must move as a coordinated set (they share Firebase's
underlying JS SDK generation) — a live-tested major bump is a dedicated regression-testing task,
not a drive-by dependency patch inside a security pass.

**Revisit:** schedule a coordinated major-version bump + full regression pass as its own tracked
work, not blocking launch.

## 6. Homoglyph/Unicode normalization — best-effort, not exhaustive

`app/lib/social/name_sanitizer.dart` strips control/zero-width/bidi-override characters
unconditionally, and folds a small hand-written Cyrillic/Greek→Latin confusables map before
blocklist matching (covering the realistic "аdmin" impersonation vector). It does **not**
implement full Unicode NFC/NFKC normalization or the complete TR39 confusables table.

**Why accepted:** no unicode-normalization package was already a dependency, and pulling in a new
heavy dependency for exhaustive confusables coverage is disproportionate to the actual threat
(impersonating a handful of reserved words) versus the realistic risk (a legitimate non-Latin-
script display name getting mangled by an over-aggressive normalizer).

**Revisit if:** real abuse reports show homoglyph evasion beyond the reserved-word impersonation
case already covered.

## 7. Data-deletion result-doc cleanup needs a one-time Firestore index

`SocialService.deleteMyData()`'s collection-group query over `results.uid` (to delete a user's
past leaderboard results across every group) requires a one-time Firestore console composite
index on first production use. Until that index exists, this specific step fails (caught/logged,
does not block the rest of the deletion — profile doc + group membership + local cache are
deleted regardless).

**Why accepted, not a code fix:** Firestore collection-group indexes are a console/infra step, not
something a `firestore.rules`/client change can provision.

**Action needed (GG, manual, before or shortly after launch):** create the composite index the
first time `deleteMyData()` triggers the "index required" error — Firestore's own error message
includes a direct console link to create the exact index needed.

## 8. Privacy policy contact address — still a placeholder

`docs/privacy-policy.md` still has `PLACEHOLDER_EMAIL` in the contact/deletion-request sections.

**Action needed (GG, before public launch):** replace with a real, monitored contact address.

## 9. `.gitignore` secret-pattern hardening (closed during this pass)

No entries previously excluded `.env`, service-account-shaped JSON, or `.pem` files —
defense-in-depth gap, not a live leak (full git-history scan found zero committed secrets). Closed
2026-07 by adding `.env`, `.env.*`, `*serviceAccountKey*.json`, `*firebase-adminsdk*.json`, `*.pem`
to `.gitignore`.
