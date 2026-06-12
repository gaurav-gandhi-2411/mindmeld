# Mindmeld — Semantic Daily Word Game

A daily word-guessing game: players guess a secret word and an embedding model scores how
semantically close each guess is (rank + temperature feedback). English + Hinglish editions.
All ML is offline — payloads are precomputed, so marginal cost per DAU is ~$0.

Phase 1 build: playable Flutter app (Android-first) + Python payload generator. Ads and IAP
are **stubs behind config flags** (`ads_enabled=false`, `iap_enabled=false`) — no SDK
dependencies. See [spec.md](spec.md) for full scope.

## Quick start — generator

```powershell
cd generator
uv sync
uv run python build.py --days 14 --langs en,hi-en --out ..\payloads
```

First run downloads two sentence-transformers models (~90 MB en, ~470 MB multilingual) and
embeds both vocabs (cached to `generator/.model-cache/`, so subsequent builds take seconds).
Output: `payloads/{lang}/{yyyy-mm-dd}.json.gz` + `payloads/manifest.json`.

```powershell
uv run pytest            # 160 unit tests + Hinglish eval gate
uv run python evals/run_evals.py   # eval fixtures standalone
```

## Payload format

Gzipped JSON per day per language. Anti-cheat design: the words map is keyed by
`sha1(word + salt)[:12]`, so the secret never appears in plaintext at a guessable key; the
reveal field `s` is XOR-obfuscated and decoded only on win/give-up. Similarities are
quantized to uint16 (round-trip error < 1e-4). Hint words exclude morphological variants of
the secret. Gzip is written with `mtime=0` so identical content produces identical bytes.

## Payload hosting

Payloads are published to the sibling repo
[mindmeld-payloads](https://github.com/gaurav-gandhi-2411/mindmeld-payloads), served via
GitHub Pages at `https://gaurav-gandhi-2411.github.io/mindmeld-payloads`. Any static host
works — the base URL lives in `app/lib/core/config.dart` (`payloadBaseUrl`).

```powershell
cd generator
uv run publish --days 30                        # build + commit + push (live)
uv run publish --days 30 --dry-run             # read-only: print what would happen
uv run publish --days 30 --langs en            # English only
uv run publish --days 30 --payloads-repo C:\other\path\mindmeld-payloads
```

The `publish` command:
1. Runs the build internally (no subprocess) into a temp directory.
2. Copies `en/`, `hi-en/`, and `manifest.json` into the payloads repo (overwrite; preserves
   `README.md`, `.nojekyll`, and any other unrelated files).
3. `git add -A` → commit (`chore: payload drop <first>..<last> (<langs>) [skip ci]`) →
   `git push origin main`. Skips commit/push if nothing changed.

The app bundles 7 days of payloads as assets (`app/assets/payloads/`) and falls back to them
on any fetch failure.

## Quick start — app

Requires Flutter ≥ 3.44 and an Android SDK.

```powershell
cd app
flutter pub get
flutter test --concurrency=1      # widget/unit tests
flutter build apk --debug
flutter test integration_test/app_test.dart -d <device>   # full guess→win loop, en + hi-en
```

## Web / PWA

Play in the browser: **https://gaurav-gandhi-2411.github.io/mindmeld-payloads/play/**
(installable PWA; same origin as the payloads, so no CORS surface).

```powershell
cd app
flutter build web --release --base-href=/mindmeld-payloads/play/ --no-web-resources-cdn
Copy-Item build\web\* ..\..\mindmeld-payloads\play\ -Recurse -Force   # then commit+push there
```

Web specifics: storage tries WASM sqlite (`sqflite_common_ffi_web`, IndexedDB) and falls
back to a `shared_preferences`-backed store on older browsers so the app never fails to
render; ads/IAP are force-disabled on web (`*EnabledEffective` getters); share uses the Web
Share API with clipboard fallback. Rewarded web ads via Google's Ad Placement API are a
Phase 4 item (`docs/web-monetization.md`).

## Results (honest numbers)

- **Payload sizes (gzipped):** en 776–778 KB/day (target < 1.5 MB); hi-en 146 KB/day
  (target < 400 KB).
- **Vocab:** en 55,000 words (wordfreq-derived, profanity-filtered, capped per spec);
  hi-en 10,439 (503 curated romanized Hinglish seeds + top English words — Hinglish list is
  a starter set, expandable via eval-gated additions).
- **Hinglish eval gate:** 60/60 active ordering fixtures pass. Honest caveat: 125 candidate
  assertions were written; ~45 first-round candidates failed because
  `paraphrase-multilingual-MiniLM-L12-v2` clusters romanized Hindi by script rather than
  meaning (e.g. `cos(dost, paisa)` > `cos(dost, friend)`). 5 linguistically-valid pairs that
  the model genuinely fails are kept in `generator/evals/fixtures_known_failures/` as
  documentation. Working fixture strategy: Hindi anchor → its English translation vs a
  semantically distant English word.
- **Tests:** generator 160/160; app 94/94 widget/unit; 2/2 emulator integration tests
  (full guess→feedback→win loop in both languages, bundled payloads).

## Repo layout

```
generator/   Python: vocab build, embeddings, payload emit, eval fixtures (uv project)
  vocab/     en.txt (generated), hinglish.txt (curated seed), profanity lists, secret schedules
  evals/     Hinglish ordering fixtures + runner (pytest-gated)
app/         Flutter: lib/core (config, codec, client, persistence), lib/features, lib/stubs
payloads/    generated output (gitignored except samples/)
```

## LLM usage

Built with Claude Code orchestrating executor/verifier subagents; architecture decisions,
spec, and curation reviewed by hand. Phase 2 (AdMob/RevenueCat, accounts, Devanagari
edition) is out of scope here — see spec.md.
