# Mindmeld — Semantic Daily Word Game

## Vision
A daily word-guessing game where players guess a secret word and an embedding model scores how semantically close each guess is (rank + "temperature"). Wordle-grade streak retention, Semantle-grade depth, productized for mobile with a Hinglish/Hindi edition no global competitor offers. Hybrid monetization: rewarded ads (hints) + IAP (ad removal, archive, streak freeze, themed packs).

## Commercial thesis
- Marginal cost per DAU ≈ $0: all ML is offline. No runtime model serving, no per-session inference cost — works at India ad eCPMs and global alike.
- Daily-puzzle format drives habitual return (streaks, share cards) → organic viral loop, zero paid UA needed to validate.
- Hinglish edition is the differentiated wedge for India; English edition rides global demand proven by Semantle/Contexto.

## Phase 1 scope (this build)
A playable, polished daily puzzle in Flutter (Android-first, iOS-compatible code) with English + Hinglish word lists. Ads and IAP are **stubbed behind a config flag** — UI hooks exist, no SDK integration yet.

### In scope
1. **Puzzle generator (Python, offline)**
   - Vocab: ~40–60k English words (frequency-filtered, profanity-filtered); ~10–15k Hinglish/Hindi-romanized words (curated seed list, expandable).
   - Embeddings: SBERT-family model for English (e.g. `all-MiniLM-L6-v2`); multilingual model (e.g. `paraphrase-multilingual-MiniLM-L12-v2`) for Hinglish so `khushi` ≈ `happiness` scores sensibly.
   - For each day's secret word: compute cosine similarity of every vocab word → emit ranked payload `{word: {rank, similarity}}`, quantized/compressed (gzip JSON or binary). Target <1.5 MB/day English, <400 KB Hinglish.
   - Generate N days ahead; secret-word schedule in a manifest. Secret words hand-curated for guessability (no obscure words).
2. **Payload hosting**
   - Static hosting (GCS bucket or GitHub Pages). App fetches `payloads/{lang}/{yyyy-mm-dd}.json.gz`. Bundle 7 days in the APK as offline fallback.
   - Secret word never transmitted in plaintext at a guessable key — payload keyed by date, secret revealed only on win/give-up (obfuscated field).
3. **Flutter app**
   - Screens: daily puzzle, guess history (sorted by rank, color temperature gradient hot→cold), win screen with share card (emoji-grid style, spoiler-free), streak/stats, settings (language toggle EN/Hinglish), how-to-play onboarding.
   - Guess input with fuzzy validation against vocab (reject non-vocab words gracefully).
   - Hint system: reveal a word at rank ~N (progressively closer). Each hint gated behind `RewardedAdStub` (config flag `ads_enabled=false` → hint free with fake 3s delay so the flow is testable).
   - IAP stubs behind `iap_enabled=false`: Remove Ads, Archive (play past days), Streak Freeze, Themed Packs (greyed "coming soon").
   - Local persistence (streaks, stats, current-day state) via shared_prefs/sqflite. No accounts in Phase 1.
   - Analytics events logged locally to a ring buffer (guess_made, hint_used, win, share_tapped) — exporter stubbed; wire Firebase in Phase 2.
4. **Hinglish quality gate**
   - Eval fixture set (~50 word pairs) asserting expected similarity orderings (e.g. `dost` closer to `friend` than to `paisa`). Generator CI fails if orderings break after model/vocab changes.

### Out of scope (Phase 2+)
AdMob/RevenueCat integration, accounts/cloud sync, leaderboards, "Convince the AI" mode, Hindi (Devanagari) edition, iOS store submission.

## Architecture
```
[Python generator (offline, cron/manual)]
   vocab + SBERT models → daily payloads (.json.gz) + manifest
        │ upload
        ▼
[Static hosting: GCS bucket / GitHub Pages]
        │ HTTPS fetch (with 7-day bundled fallback)
        ▼
[Flutter app] ── local state (sqflite) ── stubs: RewardedAdStub, IapStub, AnalyticsStub
```

## Repo layout
```
mindmeld/
  generator/        # Python: vocab build, embedding, payload emit, eval fixtures
    vocab/          # en.txt, hinglish.txt, profanity lists, secret-word schedule
    tests/
  app/              # Flutter
    lib/
      core/         # config flags, payload client, models
      features/     # puzzle, stats, settings, onboarding
      stubs/        # ads, iap, analytics
    test/
  payloads/         # generated output (gitignored except samples)
  spec.md
```

## Key decisions locked
- Flutter (single codebase, Play + App Store later).
- Similarity = precomputed lookup, never on-device or runtime inference.
- Rank-based feedback (1 = secret) + temperature label (Scorching/Hot/Warm/Cold/Freezing) — rank is the primary signal, similarity score secondary.
- One puzzle per language per day; same secret concept across languages where possible (translation-paired) for shared social moment.
- All monetization behind config flags so Phase 1 ships to internal testing without store-policy friction.

## Acceptance criteria
1. `python generator/build.py --days 14 --langs en,hi-en` emits valid payloads + manifest; eval fixtures pass.
2. Flutter app runs on Android emulator: fetches today's payload (or bundled fallback), full guess→feedback→win loop works in both languages.
3. Hint flow works end-to-end via stub; IAP screens render via stub.
4. Streaks persist across app restarts; share card generates correct spoiler-free text.
5. Widget tests for guess validation, rank coloring, streak logic; generator unit tests for payload schema + quantization round-trip.
6. README documents generator run, payload upload, app build.

## Risks
- **Hinglish vocab quality** — biggest content risk; start small/curated, grow via eval-gated additions.
- **Payload size on Indian networks** — quantize aggressively, gzip, bundle fallback days.
- **Guessability tuning** — secret words must be common nouns/concepts; playtest before widening vocab.
