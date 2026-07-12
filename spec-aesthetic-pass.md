# Warmer — Aesthetic Pass (calm & minimal)

## Direction
Calm, modern, focused — the NYT-Games/Puzzmo lane, not garish game-y. The mechanic IS color (cold→hot), so the system is a **restrained, sophisticated heat scale used sparingly** against a warm-neutral canvas. Color appears only where it carries meaning (temperature feedback); everything else is quiet neutrals and generous whitespace. Ages well, feels premium, inviting to open daily.

This replaces the current Material-bright palette (blue/green/yellow/orange/red bands, purple accent) which reads loud and templated.

## Design tokens (LIGHT — locked)
```
Canvas          #FAF8F4   (warm paper, NOT clinical white)
Surface/card    #FFFFFF
Hairline        #ECE8E1
Text primary    #26231F
Text secondary  #8A857C
Text tertiary   #B4AEA4

Brand accent (terracotta)  #DD6B4D   — logo "er", submit action, active nav
```

### Heat scale (muted, semantic — LIGHT)
Used ONLY for temperature feedback (guess rows, pills, heat-trail, closeness indicators).
```
Freezing   base #6B89A8   tint bg #EDF0F2   text #45586B
Cold       base #7E9BB5   tint bg #EDF0F2   text #3F5163
Warm       base #D9AE6B   tint bg #F3EFE6   text #6E6653
Hot        base #E0895F   tint bg #FCF3EA   text #92601F
Scorching  base #D65F49   tint bg #FBF1EC   text #B9472F
```
Rule: temperature pills = soft tint background + deepest shade of the SAME family for text. Never black-on-color, never full-saturation fills.

## Dark mode (REQUIRED — needs its own scale, not inverted light)
Muted light tints muddy on dark. Derive a dark heat scale where each band stays distinguishable and legible on a near-black warm ground.
```
Canvas          #171614  (warm near-black, not pure #000)
Surface/card    #201E1B
Hairline        #302D29
Text primary    #F2EFE9
Text secondary  #9C968C
Brand accent    #E87A5C  (lifted terracotta for contrast on dark)
```
Heat bands on dark: lift luminance so Freezing→Scorching remain clearly ordered and legible (CC to derive; verify contrast ratios). Test the full ramp side-by-side before shipping.

## Typography & layout
- One clean sans (system stack or a single geometric/humanist face — do NOT introduce multiple families). Clear scale: display / title / body / caption / micro-label (uppercase, letterspaced, tertiary color — used for "TODAY'S CLUE" style labels).
- Generous whitespace, 12–22px radii (soft, not pill-round), 0.5px hairlines (not heavy borders), minimal shadows (prefer hairline + subtle elevation only where needed).
- Guess rows: word left, rank + temperature pill right; tinted row background by band.
- Accessibility: verify WCAG AA contrast for all text-on-tint combinations in BOTH modes. Temperature must ALSO be readable without color (the band label text is present — confirm colorblind-safe ordering; the rank number is the fallback signal).

## Scope — apply the system EVERYWHERE
Build it as a **design-token system** (single source of truth in code), then apply to:
1. **Daily puzzle screen** — clue card, guess input, guess rows, budget/closest indicators, rival strip, hint tiles.
2. **Win / loss / reveal screens** — including the heat-trail visualization.
3. **Share card** (text + PNG) — adopt the muted heat squares; this is the most-seen surface (every WhatsApp share), it must look like a coherent brand.
4. **Pack selector + pack puzzle list + pack play** — pack accents (Bollywood gold/crimson, Cricket green) RETUNED to sit harmoniously in the new muted system (currently they're saturated; mute them to match without losing distinctness).
5. **Friends / leaderboard**, **Stats**, **Practice/Archive**, **Settings**, **Onboarding**, **loading screen**.
6. **Nav bar**, empty states, error states, snackbars, dialogs.
7. **OG preview image** — restyle to the new palette.

## Non-negotiables
- Zero gameplay/behavior changes. This is visual only.
- The heat-rings LOGO is approved and stays (retune its colors to the new muted scale — same mark, harmonized palette).
- No regressions: all existing tests green; cold-profile + existing-user harness pass.
- Dark mode must be genuinely designed, not auto-inverted.

## Acceptance criteria
1. Design-token system implemented (single source of truth; no hardcoded colors scattered in widgets).
2. Light + dark modes fully specified and applied; dark heat scale purpose-derived, all bands legible and correctly ordered.
3. Every screen listed above restyled; no Material-default purple/bright bands remain anywhere (grep-clean).
4. Pack accents retuned to harmonize; Bollywood and Cricket still visually distinct from each other and from core.
5. Share card (text + PNG) and OG image adopt the new palette.
6. WCAG AA contrast verified for text-on-tint in both modes; report any failures fixed.
7. Temperature legible without relying on hue alone (label + rank present).
8. All tests green; live-verify via cold-profile harness (fresh user: onboarding→puzzle→win→share) AND existing-user; screenshots of every restyled screen in both modes attached to the report.
9. Commit, push, deploy.

## Risks
- **Dark-mode heat scale is the hard part** — muted bands can collapse into mud on dark; derive deliberately and eyeball the full ramp.
- **Pack accents** — muting them too far loses their distinct identity; keep them recognizable.
- **Scope creep into layout redesign** — restyle and polish, don't re-architect screens or change flows.
