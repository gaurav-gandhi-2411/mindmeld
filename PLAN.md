# PLAN — Phase 6c: Themed Packs (living tracker)

Spec: `spec-phase6c.md` (source of truth). Scope: pack SYSTEM + Bollywood flagship only; Cricket / Indian Food / Nature & Wild as content-drop stubs.

## Cross-side contract (generator ↔ app) — FROZEN

- **Payload namespace:** `{baseUrl}/packs/{packId}/{lang}/{NNN}.json.gz`, `NNN` = 1-based zero-padded 3 (`001`…`025`).
- **Pack payload JSON:** identical v3 daily schema PLUS `"pack": "<packId>"`, `"idx": <int>`; `"date"` carries the opaque key `"<packId>-<NNN>"` (Dart never DateTime.parses payload date — verified `models.dart`).
- **Salt:** pack payloads derive salt from the opaque key + lang via the same sha1 recipe (new helper; daily path stays byte-identical).
- **Pack manifest** (published `{baseUrl}/packs/manifest.json`, bundled fallback `app/assets/payloads/packs/manifest.json`):
  ```json
  { "v": 1, "packs": [ { "id": "bollywood",
      "title": {"en": "Bollywood", "hi-en": "Bollywood"},
      "tagline": {"en": "…", "hi-en": "…"},
      "free": true, "status": "live",
      "accent": "#E8B23A", "accentDark": "#8E1A2B",
      "icon": "film", "langs": ["en", "hi-en"], "count": 25 } ] }
  ```
  `status`: `live` | `coming_soon`; stubs have `count: 0`.
- **Pack lineup + identity:** bollywood (film icon, gold `#E8B23A` / crimson `#8E1A2B`, free, live) · cricket (green `#2E7D32`) · indian-food (turmeric `#E65100`) · nature-wild (teal `#00695C`) — the last three `coming_soon`, count 0.
- **Persistence:** new sqlite table (schema v4) `pack_progress(pack_id, idx, lang, guesses_json, hints_used, won, gave_up, revealed_hints_json, PK(pack_id, idx, lang))`. Pack play NEVER writes `stats` or `day_state`.
- **IAP:** `Entitlements.packs: Set<String>`; gateway `purchasePack(packId)` → RC product `mm_pack_{id}` / entitlement `pack_{id}`. Unlock rule: `pack.free || web (iapEnabledEffective==false) || entitlements.packs.contains(id)`.
- **Share card:** pack games render `Mindmeld · {PackTitle} #{idx} {langLabel} {emoji trail}`; daily format unchanged.

## Status

- [x] 6b pushed; HEAD=origin/main=85979bc → spec committed 8b4e064
- [x] Executor A done: packs.py, build_packs.py (`uv run build-packs --packs all --langs en,hi-en --out ../payloads --strict-sizes`), publish syncs packs/ tree, 4-pack scaffolding, pytest 336 passed + 8 pack-gate skips (activate with content), ruff clean on touched files. NOTE: publish.py does NOT invoke build-packs — pack publish = run build-packs into the dir publish syncs from (orchestrate at drop time).
- [x] Bollywood content files written (packs/bollywood/*), hinglish.txt +11 words, hi-en-aliases.txt +14 entries, eval fixtures P01–P11. Generator suite GREEN: 349 passed, 6 skipped (empty stubs). Spoiler gate caught 5 subtle leaks during authoring (agar~pyar, paas~maa, her⊂mother, the⊂mother, one~song) — all reworded; audit script confirms 0 leaks across all 50 clues.
- [x] Executor B done: Flutter pack system (catalog, selector, pack play, persistence v4, IAP, share, identity). flutter test 376/376, analyze clean. Committed 83d98a8 (generator) + b3e75c4 (app), pushed.
- [x] Bollywood content validated over 3 embedding rounds. FINAL 25 pairs (EN/hi-en):
  romance/pyaar, hero/hero, villain/villain, dance/naach, song/geet, mother/maa, drama/natak,
  tears/aansoo, dialogue/dialogue, destiny/kismat, promise/vaada, revenge/badla, police/police,
  honor/izzat, sacrifice/qurbani, story/kahani, twist/twist, star/sitara, anger/gussa,
  fight/ladai, gossip/gossip, audience/audience, youth/jawaani, ticket/ticket, award/award.
  REJECTED (model misreads romanization): dil→Turkish "language", dua→Italian "due", jalan→Malay
  "road", milan→city, dushman .29, dhadkan .29, pooja .28, dulhaniya .22, intezaar .16, dosti .36,
  yaari .33, barsaat .39, saawan, dhun; EN `interval` (math neighborhood). Code-mixed EN secrets
  (hero, villain, dialogue, twist, gossip, police, audience, ticket, award) verified dense in BOTH vocabs.
  11 hinglish.txt additions needed: natak, geet, aansoo, kismat, badla, vaada, qurbani, kahani,
  sitara, ladai, jawaani — eval fixtures P01–P11 pre-validated 11/11 PASS (thinnest: ladai .435>.398).
  Aliases to add: naatak, ansoo/aansu/ansu, kismet/qismat, waada (NOT wada/vada — food collision),
  kurbani, kahaani, sitaara, ladaai/larai, jawani, nach, pyar, ghussa, izat, ma.
- [x] **STOP POINT cleared 2026-07-09**: GG approved content WITH edits. Applied: 3 GG rewords (EN #5/#16/#23), item-song kept only on #4 (hi-en #23 reworded), whistle/seeti + front/first row + first show de-duplicated (#2/#9/#22/#24). Semantic-neighbor audit over all 50 clues reworded 5 more: lyrics→#5 hi-en, line→#9 both, giraftaar→#13 hi-en, Overacting→#7 EN, Picture→#16 hi-en; EN #19 moved off the seventies archetype (collision with new #23). 13/50 clues changed total.
- [x] Payloads baked + published: 25×2 payloads + packs manifest, all under size targets (--strict-sizes), byte-reproducibility gate PASS after fixing hash-seed-dependent alt-map ordering in payload.py (5b7ddd6 — hi-en payloads were non-reproducible cross-process; regression test added). Pages commit fda0bba.
- [x] Web app deployed to playmindmeld.vercel.app (registrant + auth-domain guards OK, SW mindmeld-precache-68baf9ba2a5d verified live).
- [x] Cold-profile live verify on playmindmeld.vercel.app — ALL PASS (15 cold runs, screenshots reviewed): V1 selector gold→crimson Bollywood identity + 3 coming-soon tiles; V2 EN #1 start-to-win (wedding #889 Warm → movie #375 Hot → romance win); V3 hi-en win (shaadi → pyaar) with localized tagline; V4 share text `Mindmeld · Bollywood #1 (English) 🟨🟧⭐ / 3/15 · Par -6`; V5 pack win leaves Stats at Played 0/Streak 0 and daily unplayed, then daily win works normally. Zero pageerror/requestfailed across all runs. (Pages publish was delayed ~35 min by a GitHub Actions partial outage — queue only, no action needed.)
- [x] Full suites green: generator 350 passed / 6 skipped, flutter 376/376, ruff clean.

## Known issues (found during 6c live verify, NOT 6c regressions)

- [x] **P1 — daily win screen "Back" is a dead end for the rest of the day** — FIXED. `main.dart`'s tabbed Scaffold (NavigationBar + IndexedStack) is now always the home surface; only the index-0 child swaps between `_WinShell`/`_LossShell` and the live `PuzzleScreen`. Restart/lang-switch routing moved to `_AppShellState._deriveResultRouting`. `PuzzleScreen._load()`'s already-finished-state `onWin`/`onLoss` redirect is now scoped to pack mode only (daily mode's routing is owned exclusively by the app shell, keeping `onWin`/`onLoss` idempotent across remounts — that idempotency gap was the actual root cause of the bounce-back). Commits 5eb4869 (fix) + 1870a9c (tests: `app/test/daily_win_navigation_test.dart`, 6 cases). flutter test 382/382 (376 baseline + 6 new), analyze clean.

- [x] **Follow-up — StatsScreen stale after same-session win** — FIXED (2e596b0). Exposed by the P1 fix (Stats became reachable post-win and showed boot-time Played 0/Streak 0). Persistence was proven fine live (win → reload → 1/1); root cause: `StatsScreen._load()` ran only in initState while eagerly mounted in the IndexedStack. Now reloads on tab activation (`active: _navIndex == 2`) and lang change. flutter test 384/384.
- [x] **Follow-up sweep — other eagerly-mounted tabs** — DONE. SocialHomeScreen (Friends) had the same bug: `_groups` loaded once in initState, never refreshed on tab reactivation despite having manual pull-to-refresh. Fixed (a12b806): `active: _navIndex == 4` + `didUpdateWidget` reload on false→true (no lang trigger needed — group list isn't lang-scoped). ArchiveScreen (Practice) investigated and confirmed NOT affected: it's a `StatelessWidget` whose `_availableDates()` is a pure function of `DateTime.now()` with no persisted read, so it already recomputes fresh on every parent rebuild — no change made. GroupLeaderboardScreen (pushed route, not an IndexedStack tab) confirmed already fresh per-open (new instance + no service-layer caching) — regression test added to lock this in rather than a code change. Tests: f304a84, flutter test 386/386.
- [x] **Both P1 fixes + the Social sweep live-verified on production 2026-07-10** (cold profile, build 2cfd2a7a259a): daily win → nav bar present on win screen → Back lands on finished board and stays → Stats tab shows Played 1/100%/Streak 1/Best 1 same-session → Practice, Friends, Themed Packs → Bollywood list all reachable. Two-profile Friends flow (join-by-deep-link `/join/{code}`): Alice creates group "TestSquad" (1 member) → Bob joins via deep link and wins the daily in a separate cold profile → Alice's Friends tab, reactivated (no manual refresh), shows "2 members"; freshly-opened leaderboard shows Bob "Won in 1 (-7 vs par)". Zero pageerror/requestfailed across all runs (a handful of benign Firestore webchannel `net::ERR_ABORTED` recycle events, writes confirmed completed regardless).

## Gotchas discovered

- `derive_salt(puzzle_date: date, lang)` takes a datetime.date — pack build needs a string-key variant, daily output must remain byte-identical.
- hi-en secrets are romanized-Hindi words line-paired with EN (`samunder`↔`ocean`); pack content follows the same format.
- Flutter SDK not on PATH: `C:\Users\gaura\sdks\flutter\bin`. Tests: `flutter test --concurrency=1`.
- Daily secrets already use: ocean/samunder, music/gaana, rain/baarish, family/parivar, dream/sapna … — avoid duplicating in pack (check full 60 before finalizing).

---

# PLAN — Warmer rename + heat-rings identity + pack discoverability (complete)

Spec: `spec-warmer-rename.md` (source of truth). Autonomous single-pass run, live-verified 2026-07-10.

## Status — DONE, all 6 workstreams + both hard gates live-verified

- [x] **Rename**: manifest/index.html/in-app strings/notifications/README/docs/Android label/iOS display name → Warmer, `playmindmeld.vercel.app` → `playwarmer.vercel.app`. Deliberately unchanged (infra, zero user surface): Firebase project `mindmeld-c4bba`, Dart package name `mindmeld` (100+ `package:mindmeld/` imports), Android/iOS bundle ids, `mindmeld.db` sqlite filename, `mindmeld-payloads` GitHub Pages CDN path, generator `pyproject.toml`. Commit eccb6e7.
- [x] **Identity**: new `scripts/make_app_icon.py` (heat-rings rings-on-dark-ground, two masters — opaque tile + transparent fg for adaptive-icon compositing), rewritten `make_web_icons.py` (32/16px favicons, dark-ground maskable), new `make_og_image.py` (1200×630 card), `HeatRingsMark`/`WarmerWordmark` Flutter widgets (`app/lib/features/branding/heat_rings_mark.dart`) wired into the app-shell loading screen, onboarding hero, and daily PuzzleScreen AppBar. Theme `colorSchemeSeed` moved from the old purple `0xFF6200EE` to the wordmark accent `0xFFF97316`. `flutter_launcher_icons` regenerated Android mipmaps/adaptive icon from the new masters.
- [x] **Discoverability**: `PacksEntryBanner` (shared widget, `compact` variant) pinned to the top of `PuzzleScreen`'s primary daily surface — the fix for "couldn't find Bollywood" (previously only reachable via a card buried under the Practice tab, which still keeps its own entry too).
- [x] **Tests**: `packs_entry_banner_test.dart` (3 cases: banner shown/hidden by mode, tap navigates), `storage_rename_migration_test.dart` (2 cases: a `mindmeld.db`-named file's data survives a fresh `SqliteStore` instance; `PrefsStore` keys never literally contained "mindmeld" so nothing needed migrating). flutter 391/391 (was 386), generator 350/6-skip unaffected.
- [x] **Deploy**: Firebase Auth authorized domains updated (added `playwarmer.vercel.app`, kept `playmindmeld.vercel.app`) via `check_authorized_domains.py`'s documented PATCH remediation. Built + deployed to Vercel; **Vercel project renamed** `playmindmeld` → `playwarmer` (`vercel project rename`) then `playwarmer.vercel.app` explicitly added as a first-class project domain (`vercel domains add` — a plain `vercel alias set` was NOT enough, it stayed gated behind SSO deployment-protection since only registered project Domains are exempt). `playmindmeld.vercel.app` still resolves (same deployment, not just a redirect).
- [x] **Live-verify (cold-profile puppeteer, `firebase-tests/cold_repro_reload.js` + new `--profile-dir` flag for persistent-profile "returning user" runs)**:
  - Gate A (fresh user): onboarding shows heat-rings mark + "Welcome to Warmer"; daily puzzle screen shows the Themed Packs banner impossible-to-miss at the top; tapping it shows Bollywood live (0/25) + Cricket/Food/Nature teased "Coming soon"; played a real guess (`caterpillar` → Scorching 81.2%) then won (`butterfly`, 2 guesses) — share card correctly reads "Warmer #29 (English) … playwarmer.vercel.app".
  - Gate B (existing user): same profile, **brand-new Chrome process** (full restart, not just reload) reusing the persisted userDataDir — win screen restored instantly, Stats still shows Played 1/Win% 100/Streak 1/Best 1, zero `pageerror`/`requestfailed`. SW cache-name rotation (`mindmeld-precache-*` → `warmer-precache-*`) is safe by construction: the existing `activate` handler already evicts any cache not matching the current name on every deploy (this already happened on every prior deploy too), and streaks/stats/pack-progress live in IndexedDB/localStorage — a different browser storage mechanism than Cache Storage, untouched by the SW rename.
  - Shared-link OG card: `curl` confirmed `og:image`/`twitter:image` meta resolve to `https://playwarmer.vercel.app/icons/og-image.png` (200, image/png, 21,586 bytes).

## Gotchas discovered

- Flutter's `flutter build web` does NOT copy arbitrary files from `app/web/` into the build output (documented in `make_web_sw.py`'s existing `_copy_vercel_config` comment) — EXCEPT it copies the whole `icons/` directory wholesale and the literal `favicon.png` filename. New assets (favicon-16.png, og-image.png) were placed inside `app/web/icons/` for exactly this reason, and confirmed present in `app/build/web/icons/` after a real build rather than assumed.
- Vercel deployment-protection (`ssoProtection.deploymentType: "all_except_custom_domains"`) exempts registered project *Domains* but NOT ad-hoc `vercel alias set` targets — an aliased-but-unregistered `*.vercel.app` name still 302s to `vercel.com/sso-api`. Fix: `vercel domains add <domain>` (no project arg, uses the linked project) registers it as a real domain.
- `VAR=value cmd "$VAR"` on one bash line does NOT expand `$VAR` to the prefix-assigned value (prefix assignments only affect the child env, not same-line word expansion) — silently produced an empty `--profile-dir` arg and a fresh temp profile every run. Fix: `export VAR=value` as its own statement first.

---

# PLAN — Cricket pack (content drop) — STOP POINT, awaiting GG review

Spec: `spec-cricket-pack.md` (source of truth). Content-only drop — pack SYSTEM unchanged.

## Status

- [x] **Draft complete, 2026-07-10**: 25 secrets + EN/Hinglish clues authored to `generator/packs/cricket/{secrets,clues}_{en,hi-en}.txt`. All 25 hi-en secrets are code-mixed English (identical spelling to EN) — every native-Hindi alternative tested (naara, shatak, chakka, haar, wapsi, bheed, vijeta, mukabla, takkar, jeeta, josh) failed embedding validation (multilingual model clusters short romanized tokens by phonetics, not meaning — same failure class Bollywood found for dil/dua).
- [x] 6 vocab additions to `vocab/hinglish.txt` (wicket, umpire, bowler, fielder, finalist, chant — missing from the auto-included top-10k English words), eval-gated via new fixtures P12–P17. Thinnest margin: bowler 0.622 vs 0.232 (far more comfortable than Bollywood's thinnest, ladai at 0.435 vs 0.398).
- [x] Exact-alias spoiler gate (`tests/test_clue_spoiler_gate.py -k cricket`): 0 leaks, both languages, after 3 rounds of fixing the `bat` clue (a 3-letter secret is a Levenshtein-distance-2 minefield — "ball", "wait", "both" all tripped the morphological-variant check before landing on a clue built entirely from 4+ letter words).
- [x] Semantic-neighbor audit (ad-hoc script, not checked in — embeds every clue content-word and flags >0.40 cosine similarity to its own secret): reworded wicket (removed "batsman", 0.727→0.429 via "pavilion"), stadium (seats→voices), chant (sing/gaate→repeat/dohraate), score/aankdha (number→tally/aankdha), helmet (removed the chin-strap description cluster). hi-en flags mostly grammatical-word noise (mein/tha/sab/karta score artificially high in the multilingual model) — reviewed and left as-is after confirming no real content-word leaks remain beyond the ones fixed.
- [x] Full generator suite green: 358 passed / 4 skipped (was 350/6), eval fixtures 77/77 (was 71/71).
- [x] Zero duplicates vs the 60 daily secrets or 25 Bollywood secrets, both languages (programmatic check, not just eyeballing).
- [x] **GG-approved 2026-07-10 with 3 changes**, applied then baked:
  1. Cut `century` (theme-diluted, embedded toward "100 years" not "100 runs") → replaced with `spin` (the bowling art). Validated per GG's own acceptance bar: no spin-class/spin-doctor collision in the top-15 neighbors (generic "rotation" sense — spins/spinning/spun/spinner/rotational — not gym-class or political-spin). Already dense in both vocabs, zero additions needed. New clues: EN "Flighted invitingly, then bites and darts away late" / hi-en "Upar se lehrata hua aata hai, phir achanak kat ke nikal jaata hai" — both passed the spoiler gate after one round (hi-en's first draft used "mein", Levenshtein-2 of "spin", swapped out) and the neighbor audit clean (top score 0.286/0.368, well under the 0.40 review bar).
  2. Kept `appeal` as instructed.
  3. Reworded boundary (EN "Racing flat along the turf, four runs without ever leaving the grass", hi-en "Zameen se chipki gendh, char run, ghaas chhode bina seedha paar") to de-dupe "rope" with `six`'s clue — GG's own text includes "four runs"/"char run" literally; neighbor-audit re-run confirms `runs` itself scores only 0.238 against `boundary` (below the 0.40 flag bar) so the literal word does not register as a semantic-neighbor risk by the audit's own metric, despite spec's general caution against it — noted, not overridden (GG's explicit text, applied verbatim).
- [x] **Baked and published 2026-07-10**: `build_packs.py --packs all --langs en,hi-en --out ../payloads --strict-sizes` (note: ran with `--packs all`, not just `cricket` — a partial `--packs cricket` build writes a manifest scoped to ONLY cricket, silently dropping bollywood/indian-food/nature-wild from the published manifest; caught before publishing). All 50 payloads (25×2 langs) within size targets (en ~777-780KB, hi-en ~152-153KB, matching Bollywood's profile). Byte-reproducibility: full rebuild into a scratch dir, `diff -rq` byte-identical — PASS. Published to `mindmeld-payloads` repo (commit `04fd0ca`, pushed) + synced `app/assets/payloads/packs/manifest.json` bundled fallback.
- [x] `generator/packs/packs.json` cricket status flipped `coming_soon` → `live` (free stays `false`, matching original 6c scaffolding — irrelevant on web since IAP is force-disabled there).
- [x] Visual identity: **zero new code needed** — the pack system is already fully generic. `packIconForKey('cricket')` already mapped to `Icons.sports_cricket` (app/lib/core/packs.dart, from original 6c scaffolding); pack tile gradient, puzzle-screen `ColorScheme.fromSeed(seedColor: pack.accent)` theming, and AppBar title all read `pack.accent`/`pack.accentDark`/`pack.iconData` generically — Cricket's green `#2E7D32`/`#1B4D20` + cricket-bat-and-ball icon apply automatically now that `status: live`. Distinct from Bollywood's gold `#E8B23A`/crimson `#8E1A2B` + film icon by construction.
- [x] Fixed 3 tests broken by Cricket going live (all were asserting the old "only Bollywood is live" lineup): `generator/tests/test_packs.py` (split `test_other_packs_are_coming_soon_and_paid` into a cricket-live test + a remaining-two-coming-soon test), `app/test/pack_catalog_test.dart` (same split), `app/test/pack_selector_screen_test.dart` (coming-soon chip count 3→2, the "tapping coming_soon does nothing" test was tapping Cricket specifically — retargeted to Indian Food — added a new "tapping Cricket opens the puzzle list" test mirroring Bollywood's).
- [x] Updated `packs_entry_banner.dart`'s compact copy ("Play Bollywood — more packs coming soon" → "Bollywood & Cricket live — more packs coming soon") — stale now that Cricket is live too.
- [x] Full suites green: generator 359 passed/4 skipped (was 350/6 pre-Cricket: +2 spoiler-gate cases activating for cricket-en/hi-en, +1 net from splitting the pack-status test into two), eval fixtures 77/77 (was 71/71, +6 P12-P17; `spin` needed no addition/fixture — already dense in both vocabs), flutter 393/393 (was 391/391 pre-live-flip, +2: cricket-catalog test, cricket-tile-tap test).
- [ ] Live-verify via cold-profile harness on playwarmer.vercel.app; deploy.

## Deviations from spec's own quality-bar table (intentional, reported at review)

- Dropped `victory`/`jeet` — spec's own example secret, but **already a daily secret** in both languages (vocab/secrets_en.txt and secrets_hi-en.txt both have it at the same schedule line). Spec's constraint #34 ("None duplicating the 60 daily secrets") overrides its own example.
- Spec's example boundary clue ("Four runs the easy way...") contains "runs" — spec's own item 4 explicitly names "runs in the boundary clue" as the semantic-neighbor mistake to avoid. Did not copy it; wrote an original clue instead.
- `century` and `appeal` kept despite imperfect neighborhoods (century embeds toward "100 years" not "100 runs"; appeal embeds toward the legal-appeal sense) — both still produce a *coherent* gradient (not the "no signal at all" failure mode of over/googly/yorker), and both are in the spec's own explicitly-endorsed safe list. Flagged for GG's judgment call, not silently kept.

## Gotchas discovered

- `embed_vocab`'s cache keys on a SHA-1 of the sorted vocab list — adding even one word to a candidate batch forces a full uncached re-embed of the whole batch (fine for small ad-hoc test batches, ~10s; would NOT want to do this against the full 55k/10.4k production vocab repeatedly).
- `_is_morphological_variant` (payload.py) uses `levenshtein(candidate, secret) <= 2` with no length-relative scaling — brutal for 3-letter secrets (`bat`, `six`) since huge swaths of common short words fall within edit-distance 2. Worth remembering before picking short secrets for future packs.
- Clue *prose* (unlike secrets) never needs vocab/embedding validation — only the secret word itself must be in-vocab. Free to use rich native Hindi phrasing (wapsi, maidan, khamosh) in Hinglish clues even though those exact words failed AS secret candidates.
