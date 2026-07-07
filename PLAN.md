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
- [ ] **STOP POINT: GG review of secrets+clues** ← payloads must NOT be generated before approval
- [ ] (post-approval) build + publish Bollywood payloads; deploy web; cold-profile live verify
- [ ] Full suites green (generator pytest, app flutter test)

## Gotchas discovered

- `derive_salt(puzzle_date: date, lang)` takes a datetime.date — pack build needs a string-key variant, daily output must remain byte-identical.
- hi-en secrets are romanized-Hindi words line-paired with EN (`samunder`↔`ocean`); pack content follows the same format.
- Flutter SDK not on PATH: `C:\Users\gaura\sdks\flutter\bin`. Tests: `flutter test --concurrency=1`.
- Daily secrets already use: ocean/samunder, music/gaana, rain/baarish, family/parivar, dream/sapna … — avoid duplicating in pack (check full 60 before finalizing).
