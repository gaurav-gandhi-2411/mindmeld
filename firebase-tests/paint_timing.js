/** Measures wall-clock time from navigation to first non-blank paint (cold profile). */
const puppeteer = require('puppeteer-core');
const path = require('path');

const CHROME_PATH = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const URL = process.env.LIVE_URL || 'https://playwarmer.vercel.app/';
const SCRATCH = process.env.SCRATCH_DIR || __dirname;
const PREFIX = process.env.SHOT_PREFIX || 'paint';

async function main() {
  const t0 = Date.now();
  const browser = await puppeteer.launch({
    executablePath: CHROME_PATH,
    headless: 'new',
    args: ['--window-size=900,1000', '--no-sandbox'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 900, height: 1000 });
  page.on('console', (msg) => {
    const t = ((Date.now() - t0) / 1000).toFixed(2);
    console.log(`[t=${t}s] [console.${msg.type()}] ${msg.text()}`);
  });

  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
  const navT = ((Date.now() - t0) / 1000).toFixed(2);
  console.log(`[t=${navT}s] DOM content loaded`);

  let firstPaintT = null;
  for (let i = 0; i < 24; i++) {
    // Sample average pixel brightness by checking a mid-screen pixel region
    // via a canvas dump is overkill; instead check if the DOM has any
    // flt-glass-pane with non-trivial rendered content by screenshotting
    // and comparing byte size against a known-blank baseline is unreliable
    // too -- simplest robust signal: query for the flutter semantics host
    // element's bounding rect having non-zero children, OR just screenshot
    // every 250ms and let file size proxy for "has content" (blank white
    // PNGs compress to a near-constant tiny size).
    const shotPath = path.join(SCRATCH, `${PREFIX}_${String(i).padStart(2, '0')}.png`);
    await page.screenshot({ path: shotPath });
    const fs = require('fs');
    const size = fs.statSync(shotPath).size;
    const t = ((Date.now() - t0) / 1000).toFixed(2);
    console.log(`[t=${t}s] shot ${i}: ${size} bytes`);
    if (size > 15000 && firstPaintT === null) {
      firstPaintT = t;
      console.log(`>>> FIRST NON-BLANK PAINT at t=${t}s (frame ${i})`);
    }
    await new Promise((r) => setTimeout(r, 250));
  }

  await browser.close();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
