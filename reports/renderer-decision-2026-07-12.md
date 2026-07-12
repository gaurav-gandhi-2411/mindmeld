# Renderer decision — launch-1 wave, riskiest assumption first (rule 77)

Spec §6 framed this as "CanvasKit vs HTML renderer" and asked for the cheap experiment to run
**before** any aesthetic work, since a renderer change would force visual QA to happen twice.

## Premise check (rule 99) — the framed choice doesn't exist

Verified empirically against the installed toolchain (Flutter 3.44.2, `flutter build web --help
--verbose`): there is **no `--web-renderer` flag at all**. Confirmed via Flutter's own docs and
tracking issue, not recalled from memory: the HTML renderer was deprecated in Flutter 3.24 and
**removed in Flutter 3.29** ([docs.flutter.dev/platform-integration/web/renderers](https://docs.flutter.dev/platform-integration/web/renderers),
[flutter/flutter#145954](https://github.com/flutter/flutter/issues/145954)). CanvasKit is not a
"choice" on this toolchain — it's the only renderer. This resolves the named risk immediately: no
build/measure cycle needed for that specific question.

## The real available lever: `--wasm` (Dart→WebAssembly compilation)

`--wasm` is a live, current, one-flag experiment on this toolchain (compiles Dart to WebAssembly
with a JS fallback for browsers without WasmGC, vs. the default Dart→JS compile). Same spirit as
the spec's ask (cheap, one-flag, test before committing to paint work), so tested it in its place.

### Method

1. Built current `main` twice from the same source (`app/`, commit `039344a`): once with the
   default JS target (already the committed production baseline, see
   `reports/performance-baseline-2026-07-12.md`), once with `flutter build web --release --wasm`.
2. Deployed the wasm build to an isolated, throwaway Vercel project (`web-dist-wasm-preview`,
   deleted after measurement) — never touched the real `playwarmer` production project.
3. **Functional verification first, not just build success**: Vercel's default deployment-
   protection SSO gate initially made the preview look "broken" (smoke_check reported boot
   timeout) — traced to a 302 redirect to `vercel.com/sso-api`, not a wasm problem. Used a
   protection-bypass share URL to get a real anonymous-user view, then re-ran a cold-profile
   puppeteer pass: onboarding rendered correctly, a guess (`ocean`) submitted and ranked correctly
   (`#4003 Cold 65.9%`), Themed Packs banner and rival strip rendered identically to the JS build.
   **Not covered by this pass**: Firebase Auth/Firestore social features, notifications, IAP —
   none of these were exercised under `--wasm` in this test. Flagged as a residual verification
   gap, not silently assumed fine.
4. Ran Lighthouse 13.4.0 (desktop preset, same tool version as the committed baseline) against the
   wasm preview via the same bypass URL.

### Results (numeric, both runs same Lighthouse version)

| Metric | JS (committed baseline) | `--wasm` | Delta |
|---|---|---|---|
| Performance score | 0.69 | 0.79 | **+0.10** |
| LCP | 2864ms | 2634.6ms | **-229ms** |
| FCP | 934ms | 958.8ms | +24.8ms (noise-level) |
| TBT | 221ms | **13.5ms** | **-207.5ms** |
| Speed Index | 2797ms | 2522.5ms | -274.5ms |
| CLS | 0 | 0 | unchanged |
| Total page weight | 2838.2 KB | 2421.0 KB | **-417.2 KB** |

Artifacts: `reports/lighthouse-wasm-experiment.report.{html,json}` (this commit).

### Against the ratified rule-15e budgets

- TBT ≤200ms: **was failing** (221ms) → **now passing** (13.5ms), by a wide margin.
- LCP ≤3000ms tracked ceiling: was passing (2864ms) → now passing with much more headroom
  (2634.6ms). LCP ≤2500ms **stretch target**: still short by 134.6ms — real, not closed by this
  lever alone. Not chasing further this wave (rule 113 — stop at the budget; the *tracked*
  ceiling is the hard requirement, the stretch target is aspirational). Revisit if a future pass
  has budget for deferred-loading work.
- Total page weight ≤1000KB (own-domain JS only, per the ratified budget's exact wording —
  CanvasKit/third-party CDN assets excluded): unaffected by this lever either way, already passing.

## Decision

**Adopt `--wasm` for all builds this wave and going forward.** Same CanvasKit renderer underneath
(unaffected either way, confirmed no visual difference across the two functional screenshots
captured) — so Track A's aesthetic-pass screenshots and design-reviewer sign-off can proceed on
this build target with no risk of a second visual-QA pass later. README's canonical deploy command
updated to include `--wasm` (see commit). The remaining LCP stretch-target gap and the untested
social/notifications/IAP paths under wasm are logged in `docs/known-limitations.md`, not blocking
this wave.
