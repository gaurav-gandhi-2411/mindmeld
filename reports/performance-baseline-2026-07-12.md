# Warmer (playwarmer.vercel.app) — Performance Baseline

Measured 2026-07-12, Lighthouse 13.4.0 CLI, desktop preset, headless Chrome, cold load.
Raw artifacts: `lighthouse-playwarmer-baseline.report.json`, `lighthouse-playwarmer-baseline.report.html` (same directory).

**Caveat:** this is a Flutter CanvasKit web app (canvas-rendered, not DOM-rendered). Lighthouse's Lantern network-dependency simulation threw `LanternError: NO_LCP` on this run (non-fatal — the run still completed and reported observed-trace metrics below), which is a known limitation of Lighthouse's LCP heuristics against canvas-based apps: there is no traditional "largest contentful DOM element" to key off. Treat the LCP number as directionally useful, not precise.

## Core Web Vitals (observed, from trace)

| Metric | Value | Rating |
|---|---|---|
| Performance score | 0.69 | — |
| LCP | 2864 ms | Needs improvement (<4s, >2.5s) — see caveat above |
| TBT | 221 ms | Needs improvement (just over the 200ms "good" line) |
| CLS | 0 | Good (<0.1) |
| FCP | 934 ms | Good (<1.8s) |
| Speed Index | 2797 ms | Needs improvement (<5.8s, >3.4s... actually within "good" by SI's own threshold, flagged here for visibility) |

## Payload

| | |
|---|---|
| Total page weight | 2838.2 KB |
| Total JS transferred | 1139.3 KB |

Top resources:
- `main.dart.js` (own domain) — 928.0 KB
- `canvaskit.wasm` (gstatic CDN, likely browser-cached across sites using the same Flutter CanvasKit version) — 1613.4 KB
- `@revenuecat/purchases-js-hybrid-mappings` (jsdelivr CDN) — 182.9 KB
- `canvaskit.js` (gstatic CDN) — 24.3 KB

## Proposed rule-15e budgets (pending ratification)

| Budget | Proposed | Basis |
|---|---|---|
| Initial JS bundle (own domain: main.dart.js + flutter_bootstrap.js) | ≤ 1000 KB | current ~932 KB combined; CanvasKit/RevenueCat CDN assets tracked separately as third-party, not counted against this budget |
| LCP | ≤ 2500 ms | current 2864 ms — realistic near-term target to cross into "good"; re-measure after confirming Lighthouse's canvas-app LCP caveat doesn't invalidate the number |
| TBT | ≤ 200 ms | current 221 ms — small, achievable trim |
| CLS | ≤ 0.1 | current is 0; standard "good" threshold, no reason to tighten given canvas rendering makes near-zero CLS structural |
