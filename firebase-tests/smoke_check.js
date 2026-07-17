/**
 * Post-deploy smoke check: fails loudly (non-zero exit) unless the live app
 * actually BOOTS, not just returns HTTP 200 for the shell HTML.
 *
 * scripts/check_uptime.py already covers the HTTP-level checks (app root,
 * CDN manifest, a real CDN payload) and is cheap enough to run every 15
 * minutes in CI. This script is the complement: it drives a real headless
 * Chrome load of the page and verifies the Flutter *engine* actually
 * mounted (its `<flt-glass-pane>` root element exists with a real size)
 * with zero pageerror/requestfailed against the app's own origin.
 *
 * NOTE on what this can't see: this app renders via CanvasKit (a `<canvas>`,
 * not readable DOM text), so — unlike a text-based "wait for 'Welcome to
 * Warmer'" check, which was tried first and never fires because
 * document.body.innerText is empty on this app — there is no cheap,
 * dependency-free way to prove a specific SCREEN painted. What this DOES
 * prove: the JS bundle loaded, the engine initialized without throwing, and
 * no own-origin asset 404'd. A silent async hang that leaves the engine
 * mounted but the widget tree never built would NOT be caught here; if you
 * suspect that failure mode, fall back to a manual cold_repro_reload.js run
 * and read the screenshot (same as every live-verify pass this project has
 * done to date).
 *
 * Run this after EVERY deploy, before considering the deploy done:
 *   node firebase-tests/smoke_check.js
 *   node firebase-tests/smoke_check.js https://playwarmer.vercel.app/
 *
 * Exit 0  = live URL returns 200 AND the Flutter engine mounted, zero
 *           pageerror/requestfailed.
 * Exit 1  = any of the above failed; treat the deploy as NOT done — do not
 *           report success, investigate (build logs, `vercel rollback`, or
 *           re-run the deploy) before moving on.
 */
const puppeteer = require('puppeteer-core');

const CHROME_PATH = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
// Named TARGET_URL, not URL: a module-scope `const URL` shadows the global
// URL class, which made the requestfailed handler below throw ("URL is not
// a constructor") and crash the whole check the first time ANY request
// failed — i.e. precisely when the own-origin filter was needed. Dormant
// until a benign non-origin failure occurred during a post-deploy run.
const TARGET_URL = process.argv[2] || process.env.LIVE_URL || 'https://playwarmer.vercel.app/';
const TARGET_ORIGIN = new URL(TARGET_URL).origin;
const BOOT_TIMEOUT_MS = 30000;
// Extra settle after the glass pane appears — mirrors this project's own
// cold_repro_reload.js INITIAL_WAIT_MS convention (the glass pane can exist
// before the first real frame paints).
const SETTLE_MS = 4000;

async function main() {
  const browser = await puppeteer.launch({
    executablePath: CHROME_PATH,
    headless: 'new',
    args: ['--window-size=900,1000', '--no-sandbox'],
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 900, height: 1000 });

  const pageErrors = [];
  const requestFailures = [];
  page.on('pageerror', (err) => pageErrors.push(err.message));
  page.on('requestfailed', (req) => {
    // Benign Firestore webchannel recycle events are expected noise even on
    // a healthy load (see PLAN.md prior live-verify notes) — only count
    // failures against the app's own origin as smoke-check failures.
    if (req.url().startsWith(TARGET_ORIGIN)) {
      requestFailures.push(`${req.url()} -- ${req.failure()?.errorText}`);
    }
  });

  let httpStatus = null;
  let booted = false;
  let bootError = null;

  try {
    const response = await page.goto(TARGET_URL, { waitUntil: 'networkidle2', timeout: 30000 });
    httpStatus = response ? response.status() : null;

    // flt-glass-pane (the Flutter web engine's root element) renders into a
    // shadow root, so its OWN offsetWidth/offsetHeight are always 0 — the
    // real signal is a sized <canvas> inside that shadow root (CanvasKit's
    // actual paint surface). Confirmed via a live DOM probe against this
    // app: the light-DOM element has zero size/children even ~8s after
    // load; canvas.width/height match the viewport once rendering starts.
    await page.waitForFunction(
      () => {
        const pane = document.querySelector('flt-glass-pane');
        const canvas = pane && pane.shadowRoot && pane.shadowRoot.querySelector('canvas');
        return !!canvas && canvas.width > 0 && canvas.height > 0;
      },
      { timeout: BOOT_TIMEOUT_MS },
    );
    await new Promise((r) => setTimeout(r, SETTLE_MS));
    booted = true;
  } catch (err) {
    bootError = err.message;
  }

  await browser.close();

  const failures = [];
  if (httpStatus !== 200) failures.push(`HTTP status was ${httpStatus}, expected 200`);
  if (!booted) failures.push(`app did not boot within ${BOOT_TIMEOUT_MS}ms: ${bootError}`);
  if (pageErrors.length) failures.push(`${pageErrors.length} pageerror(s): ${pageErrors.join(' | ')}`);
  if (requestFailures.length) {
    failures.push(`${requestFailures.length} requestfailed (own origin): ${requestFailures.join(' | ')}`);
  }

  console.log(`URL: ${TARGET_URL}`);
  console.log(`HTTP status: ${httpStatus}`);
  console.log(`Booted: ${booted}`);
  console.log(`pageerror count: ${pageErrors.length}`);
  console.log(`requestfailed (own origin) count: ${requestFailures.length}`);

  if (failures.length) {
    console.log('\nFAIL:');
    for (const f of failures) console.log(`  - ${f}`);
    process.exit(1);
  }

  console.log('\nPASS: app is live and booted cleanly.');
  process.exit(0);
}

main().catch((e) => {
  console.error('smoke_check.js crashed:', e);
  process.exit(1);
});
