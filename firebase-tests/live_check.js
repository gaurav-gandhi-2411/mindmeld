/**
 * Headless live-site probe using the locally installed Chrome (via
 * puppeteer-core, no bundled Chromium download). Loads the deployed app,
 * captures ALL console output, and optionally clicks at given coordinates.
 *
 * Usage (actions run in the order given on the command line):
 *   node live_check.js
 *   node live_check.js --click X,Y --type "some text" --click X2,Y2
 */
const puppeteer = require('puppeteer-core');
const path = require('path');

const CHROME_PATH = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const URL = process.env.LIVE_URL || 'https://playwarmer.vercel.app/';
const SCRATCH = process.env.SCRATCH_DIR || __dirname;

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
    }
  }
  return actions;
}

async function main() {
  const actions = parseActions(process.argv.slice(2));
  const browser = await puppeteer.launch({
    executablePath: CHROME_PATH,
    headless: 'new',
    args: ['--window-size=900,1000', '--no-sandbox'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 900, height: 1000 });

  const logs = [];
  page.on('console', (msg) => {
    const line = `[console.${msg.type()}] ${msg.text()}`;
    logs.push(line);
    console.log(line);
  });
  page.on('pageerror', (err) => {
    const line = `[pageerror] ${err.message}`;
    logs.push(line);
    console.log(line);
  });

  console.log(`Navigating to ${URL} ...`);
  await page.goto(URL, { waitUntil: 'networkidle2', timeout: 60000 });

  // Give the Flutter engine time to boot and paint the first frame.
  await new Promise((r) => setTimeout(r, 7000));
  await page.screenshot({ path: path.join(SCRATCH, 'shot_00_initial.png') });
  console.log('Saved shot_00_initial.png');

  for (let i = 0; i < actions.length; i++) {
    const action = actions[i];
    let label;
    if (action.kind === 'click') {
      console.log(`Clicking at (${action.x}, ${action.y})...`);
      await page.mouse.click(action.x, action.y);
      label = `click_${action.x}_${action.y}`;
    } else {
      console.log(`Typing "${action.text}"...`);
      await page.keyboard.type(action.text, { delay: 30 });
      label = 'type';
    }
    await new Promise((r) => setTimeout(r, 3500));
    const shotName = `shot_${String(i + 1).padStart(2, '0')}_after_${label}.png`;
    await page.screenshot({ path: path.join(SCRATCH, shotName) });
    console.log(`Saved ${shotName}`);
  }

  // Extra settle time to catch async console output (e.g. sign-in results).
  await new Promise((r) => setTimeout(r, 6000));
  await page.screenshot({ path: path.join(SCRATCH, 'shot_99_final.png') });
  console.log('Saved shot_99_final.png');

  await browser.close();

  console.log('\n--- all console output ---');
  console.log(logs.join('\n'));
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
