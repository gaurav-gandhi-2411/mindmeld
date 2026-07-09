/**
 * Variant of cold_repro.js (which stays unchanged) adding a `--reload`
 * action for verifying persistence-across-restart behaviour (e.g. P1
 * daily-win-screen fix CHECK 5): a page.reload() in the SAME browser
 * context/profile preserves IndexedDB/localStorage/SW, simulating a user
 * relaunching the app after already completing today's puzzle, without
 * needing a brand new cold profile (which would wipe that state anyway).
 *
 * All other behaviour (cold profile launch, action types, screenshot
 * naming, console/pageerror/requestfailed logging) is identical to
 * cold_repro.js. See that file's header comment for the general contract.
 *
 * Additional action:
 *   --reload        page.reload({ waitUntil: 'networkidle2' })
 */
const puppeteer = require('puppeteer-core');
const path = require('path');

const CHROME_PATH = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const URL = process.env.LIVE_URL || 'https://playmindmeld.vercel.app/';
const SCRATCH = process.env.SCRATCH_DIR || __dirname;
const PREFIX = process.env.SHOT_PREFIX || 'run';
const INITIAL_WAIT_MS = Number(process.env.INITIAL_WAIT_MS ?? 7000);
const CLICK_SETTLE_MS = Number(process.env.CLICK_SETTLE_MS ?? 1200);
const TYPE_SETTLE_MS = Number(process.env.TYPE_SETTLE_MS ?? 500);
const TYPE_DELAY_MS = Number(process.env.TYPE_DELAY_MS ?? 30);
const RELOAD_WAIT_MS = Number(process.env.RELOAD_WAIT_MS ?? 7000);

function parseActions(argv) {
  const actions = [];
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--click' && argv[i + 1]) {
      const [x, y] = argv[i + 1].split(',').map(Number);
      actions.push({ kind: 'click', x, y });
      i++;
    } else if (argv[i] === '--type' && argv[i + 1]) {
      actions.push({ kind: 'type', text: argv[i + 1] });
      i++;
    } else if (argv[i] === '--key' && argv[i + 1]) {
      actions.push({ kind: 'key', key: argv[i + 1] });
      i++;
    } else if (argv[i] === '--wait' && argv[i + 1]) {
      actions.push({ kind: 'wait', ms: Number(argv[i + 1]) });
      i++;
    } else if (argv[i] === '--scroll' && argv[i + 1]) {
      const [dx, dy] = argv[i + 1].split(',').map(Number);
      actions.push({ kind: 'scroll', dx, dy });
      i++;
    } else if (argv[i] === '--reload') {
      actions.push({ kind: 'reload' });
    }
  }
  return actions;
}

const GRANT_NOTIFICATIONS = process.argv.includes('--grant-notifications');

async function main() {
  const actions = parseActions(process.argv.slice(2));
  const t0 = Date.now();
  const browser = await puppeteer.launch({
    executablePath: CHROME_PATH,
    headless: 'new',
    args: ['--window-size=900,1000', '--no-sandbox'],
  });
  if (GRANT_NOTIFICATIONS) {
    await browser.defaultBrowserContext().overridePermissions(URL, ['notifications']);
  }
  const page = await browser.newPage();
  await page.setViewport({ width: 900, height: 1000 });

  const logs = [];
  const rec = (line) => {
    const t = ((Date.now() - t0) / 1000).toFixed(2);
    const out = `[t=${t}s] ${line}`;
    logs.push(out);
    console.log(out);
  };
  page.on('console', (msg) => rec(`[console.${msg.type()}] ${msg.text()}`));
  page.on('pageerror', (err) => rec(`[pageerror] ${err.message}`));
  page.on('requestfailed', (req) =>
    rec(`[requestfailed] ${req.url()} -- ${req.failure()?.errorText}`),
  );

  rec(`Navigating to ${URL} ...`);
  await page.goto(URL, { waitUntil: 'networkidle2', timeout: 60000 });

  await new Promise((r) => setTimeout(r, INITIAL_WAIT_MS));
  await page.screenshot({ path: path.join(SCRATCH, `${PREFIX}_00_initial.png`) });
  rec('Saved initial screenshot');

  for (let i = 0; i < actions.length; i++) {
    const action = actions[i];
    let label;
    if (action.kind === 'click') {
      rec(`Clicking at (${action.x}, ${action.y})...`);
      await page.mouse.click(action.x, action.y);
      label = `click_${action.x}_${action.y}`;
      await new Promise((r) => setTimeout(r, CLICK_SETTLE_MS));
    } else if (action.kind === 'type') {
      rec(`Typing "${action.text}"...`);
      await page.keyboard.type(action.text, { delay: TYPE_DELAY_MS });
      label = 'type';
      await new Promise((r) => setTimeout(r, TYPE_SETTLE_MS));
    } else if (action.kind === 'key') {
      rec(`Pressing key ${action.key}...`);
      await page.keyboard.press(action.key);
      label = `key_${action.key}`;
      await new Promise((r) => setTimeout(r, CLICK_SETTLE_MS));
    } else if (action.kind === 'wait') {
      rec(`Waiting ${action.ms}ms...`);
      await new Promise((r) => setTimeout(r, action.ms));
      label = `wait_${action.ms}`;
    } else if (action.kind === 'scroll') {
      rec(`Scrolling by (${action.dx}, ${action.dy})...`);
      await page.mouse.move(450, 500);
      await page.mouse.wheel({ deltaX: action.dx, deltaY: action.dy });
      label = `scroll_${action.dx}_${action.dy}`;
      await new Promise((r) => setTimeout(r, CLICK_SETTLE_MS));
    } else if (action.kind === 'reload') {
      rec('Reloading page (same profile/session, preserves storage)...');
      await page.reload({ waitUntil: 'networkidle2', timeout: 60000 });
      await new Promise((r) => setTimeout(r, RELOAD_WAIT_MS));
      label = 'reload';
    }
    const shotName = `${PREFIX}_${String(i + 1).padStart(2, '0')}_after_${label}.png`;
    await page.screenshot({ path: path.join(SCRATCH, shotName) });
    rec(`Saved ${shotName}`);
  }

  await new Promise((r) => setTimeout(r, 8000));
  await page.screenshot({ path: path.join(SCRATCH, `${PREFIX}_99_final.png`) });
  rec('Saved final screenshot');

  await browser.close();

  console.log('\n--- full timestamped console output ---');
  console.log(logs.join('\n'));
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
