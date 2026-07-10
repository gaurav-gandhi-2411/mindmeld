# Warmer — Rename + Identity + UX Pass

## Why this phase
The product is renamed from Mindmeld to **Warmer** — a name that teaches the mechanic ("you're getting warmer"). This phase does three things in one pass: (1) rename everything, (2) apply a new heat-rings visual identity consistently, (3) fix the UX debt the "couldn't find Bollywood" issue exposed — packs are buried and core screens need polish. Canonical domain stays `playwarmer.vercel.app` (free) for now; `.com` deferred until validated.

## The name
**Warmer.** Handle: `playwarmer`. Tagline direction: "The daily word game where closer means warmer."

## Visual identity — heat rings
The mark: concentric rings in the game's temperature-band palette closing to a hot center — cold blue outer → cyan → amber → red-hot center dot. It IS the mechanic (closing in, getting warmer). Palette (locked):
- Cold/outer: `#2563EB`
- Cool: `#06B6D4`
- Warm: `#F59E0B`
- Hot/center: `#EF4444`
- Wordmark accent ("er"): `#F97316`
- App-tile ground (dark): `#0F172A`

Favicon behavior: at 32px use 3 rings + center; at 16px simplify to blue ring + amber ring + red dot for legibility.

Wordmark: lowercase `warmer`, "warm" in primary text color, "er" in `#F97316`, with the heat-rings icon to its left.

## Scope — three workstreams

### 1. Rename mindmeld → warmer (thorough, correctness-gated)
- App title, PWA manifest (name/short_name/theme), package/bundle references, share-card text ("Warmer #N"), OG/meta tags, onboarding copy, README, docs, in-app strings.
- Config/analytics: keep the existing Firebase project (`mindmeld-c4bba`) — do NOT rename the Firebase project (high-risk, no benefit); only user-facing strings change. Note in README that the project ID stays mindmeld-c4bba internally.
- **Service worker cache name** must change with the rename (or be versioned) so returning users don't get stranded on a stale-named cache — but MUST NOT strand existing users; verify a user with old cached state migrates cleanly.
- **Local storage / DB keys**: if any persisted key is namespaced on "mindmeld", migrate it so existing players keep streaks/stats/progress. If migration is impractical, document exactly what an existing user loses (should be nothing critical).
- Payloads repo/paths: the game payloads + pack payloads keep working; update only display strings, not payload URLs (avoid breaking hosting). If any user-facing URL/string references mindmeld, update it.
- HARD GATE: after rename, the app must load cleanly on BOTH a cold first-time profile AND an existing-user profile with old cached state — verified via the cold-profile headless harness. Renames are where stale-cache/ID-mismatch bugs live.

### 2. Apply the heat-rings identity everywhere
- App icon (adaptive, all densities), favicon (32 + 16 variants per above), header/nav branding, loading screen, onboarding hero.
- **OG share-preview image**: a proper 1200×630 preview card (heat-rings + "Warmer" + tagline) so shared links render a real card, not a bare URL — this is a virality lever. Wire OG/Twitter meta to it.
- Replace the old purple "M" identity throughout; nothing should reference the old logo.
- Core temperature palette applied deliberately across the app (the bands already use it; make the whole UI coherent with it).

### 3. Fix pack discoverability + core-screen polish
- **Packs must be prominent** — the flagship Bollywood pack was buried under a card atop the Practice tab; the reason GG couldn't find it. Give packs real placement: a clear entry from the primary play surface (a "Packs" strip/section or a dedicated, obvious tile) so a new pack is impossible to miss. Coming-soon packs (Cricket/Indian Food/Nature) visible as teasers.
- **Polish the core loop screens** — daily puzzle, win/loss, share, leaderboard, pack selector: consistent spacing, type scale, and temperature-palette usage; the heat-rings motif echoed where natural (e.g. the closeness/temperature indicator).
- Keep all existing behavior intact (bounded guesses, rival, reveal, streaks, social, notifications) — this is a visual/navigational pass, not a gameplay change.

## Acceptance criteria
1. Zero user-facing "mindmeld" strings remain (grep clean); app title, manifest, share text, OG tags all say Warmer/playwarmer. Firebase project ID intentionally unchanged (documented).
2. Heat-rings identity applied: app icon, favicon (32+16), header, loading, onboarding, OG preview image; old purple "M" fully removed.
3. OG share-preview renders a real card when the URL is shared (verify meta + image reachable).
4. Packs are prominently discoverable from the primary play surface; Bollywood is obvious, not buried; coming-soon packs teased.
5. Core screens polished and visually coherent with the temperature palette; no regressions to gameplay/social/notifications.
6. Rename correctness: cold first-time profile loads clean AND existing-user profile with old cached state loads clean with streaks/stats/pack-progress intact (or documented loss = none critical). SW cache-name change doesn't strand returning users.
7. All existing tests green; add tests for any storage-key migration and for the pack-discoverability entry.
8. Live-verify via cold-profile harness on playwarmer.vercel.app: fresh user sees Warmer branding + finds Bollywood easily + plays a puzzle; returning-user (old cache) still works with history intact; shared-link OG card resolves.

## Manual step (GG)
- None required for the vercel.app domain. (If we later move to a custom domain, that domain must be added to Firebase Auth authorized domains — the pre-deploy guard already checks this.)

## Risks
- **Rename stale-cache / ID-mismatch** — the prime risk; cold + existing-user harness runs are the gate.
- **Storage-key migration** — don't wipe existing players' streaks/progress; migrate or prove nothing critical is lost.
- **Scope** — this is rename + identity + discoverability + polish; do NOT change gameplay or add features.
