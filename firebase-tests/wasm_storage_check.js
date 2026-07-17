/**
 * Proves the SQLite/WASM storage backend is actually active and writing real
 * data under a REAL `flutter build web --wasm` build — not a UI toast, not a
 * DDC-run test (dart.library.html is TRUE under DDC, which is exactly how
 * the P0 wasm-stub bug hid for a whole launch-1 wave: every test green
 * while production silently fell back to PrefsStore since 2026-07-12).
 *
 * IMPORTANT — dev.log does NOT surface in the console under a release wasm
 * build (dart:developer.log is effectively a no-op outside debug/profile
 * mode/DevTools attachment), so the originally-planned check for
 * persistence.dart's "AppPersistence: SQLite/WASM backend active (web)"
 * console line does NOT work here — verified empirically: a real release
 * --wasm build of this app emits ZERO page-console messages on cold boot,
 * with or without a working SQLite backend. This script instead asserts a
 * harder, lower-level signal that only a genuine SQLite/IndexedDB write
 * path can produce (PrefsStore never touches IndexedDB, only localStorage):
 *
 *   1. The `sqflite_databases` IndexedDB database exists (sqflite_common_ffi_web's
 *      fixed VFS database name — see sqlite3 package's IndexedDbFileSystem).
 *   2. Its `files` object store has at least one row (the opened .db file)
 *      AND its `blocks` object store has at least one row (actual page data
 *      written by the CREATE TABLE statements in SqliteStore._onCreate —
 *      an empty `blocks` store with a non-empty `files` store is exactly
 *      the failure signature hit during this fix's own bring-up: the
 *      sqflite_sw.js SharedWorker failed to instantiate its sqlite3.wasm
 *      ("Import #25 'env': module is not an object or function") and never
 *      got to execute any SQL, while still creating the empty file record).
 *   3. No worker console line matching /error|WebAssembly\.instantiate/i is
 *      observed (this is the exact failure class from bullet 2 above).
 *   4. After a same-session `page.reload()` (IndexedDB survives reloads),
 *      the same file id is still present with its blocks intact — proving
 *      persistence across reload, not just a first-boot fluke.
 *
 * Usage (serve `flutter build web --wasm` output locally first):
 *   python -m http.server 8642   (from app/build/web)
 *   node firebase-tests/wasm_storage_check.js
 *   node firebase-tests/wasm_storage_check.js http://localhost:8642/
 *
 * Exit 0 = SQLite/WASM backend proven to have written real data, persisted
 *          across reload, with no WASM-instantiation errors from the worker.
 * Exit 1 = any check failed — treat the wasm-stub fix as NOT verified.
 */
const puppeteer = require('puppeteer-core');

// Env-overridable so the CI wasm lane (ubuntu, google-chrome on PATH) can
// point at its own binary; defaults to the local Windows install.
const CHROME_PATH =
  process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const TARGET_URL = process.argv[2] || process.env.LIVE_URL || 'http://localhost:8642/';
const BOOT_TIMEOUT_MS = 30000;
const SETTLE_MS = 8000;
const SQFLITE_IDB_NAME = 'sqflite_databases';
const WORKER_ERROR_PATTERN = /error|WebAssembly\.instantiate/i;

async function waitForBoot(page) {
  await page.waitForFunction(
    () => {
      const pane = document.querySelector('flt-glass-pane');
      const canvas = pane && pane.shadowRoot && pane.shadowRoot.querySelector('canvas');
      return !!canvas && canvas.width > 0 && canvas.height > 0;
    },
    { timeout: BOOT_TIMEOUT_MS },
  );
}

/** Reads the sqflite IndexedDB VFS database and returns file/block row counts. */
async function readSqfliteIdbState(page) {
  return page.evaluate(async (dbName) => {
    const dbNames = 'databases' in indexedDB
      ? (await indexedDB.databases()).map((d) => d.name)
      : null;

    const opened = await new Promise((resolve, reject) => {
      const req = indexedDB.open(dbName);
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });

    const storeNames = Array.from(opened.objectStoreNames);
    if (storeNames.length === 0) {
      opened.close();
      return { dbNames, storeNames, fileKeys: [], blockKeys: [] };
    }

    const tx = opened.transaction(storeNames, 'readonly');
    const [fileKeys, blockKeys] = await Promise.all([
      new Promise((resolve, reject) => {
        const r = tx.objectStore('files').getAllKeys();
        r.onsuccess = () => resolve(r.result);
        r.onerror = () => reject(r.error);
      }),
      new Promise((resolve, reject) => {
        const r = tx.objectStore('blocks').getAllKeys();
        r.onsuccess = () => resolve(r.result);
        r.onerror = () => reject(r.error);
      }),
    ]);

    opened.close();
    return { dbNames, storeNames, fileKeys, blockKeys };
  }, SQFLITE_IDB_NAME);
}

async function main() {
  const browser = await puppeteer.launch({
    executablePath: CHROME_PATH,
    headless: 'new',
    args: ['--window-size=900,1000', '--no-sandbox'],
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 900, height: 1000 });

  const workerLines = [];
  const pageErrors = [];
  page.on('pageerror', (err) => pageErrors.push(err.message));
  browser.on('targetcreated', async (target) => {
    if (target.type() !== 'worker' && target.type() !== 'shared_worker') return;
    workerLines.push(`[worker created] ${target.url()}`);
    try {
      const w = await target.worker();
      if (w) w.on('console', (msg) => workerLines.push(`[worker.console] ${msg.text()}`));
    } catch (e) {
      workerLines.push(`[worker attach error] ${e.message}`);
    }
  });

  const failures = [];
  let firstLoadState = null;
  let reloadState = null;

  try {
    await page.goto(TARGET_URL, { waitUntil: 'networkidle2', timeout: 30000 });
    await waitForBoot(page);
    await new Promise((r) => setTimeout(r, SETTLE_MS));
    firstLoadState = await readSqfliteIdbState(page);

    await page.reload({ waitUntil: 'networkidle2', timeout: 30000 });
    await waitForBoot(page);
    await new Promise((r) => setTimeout(r, SETTLE_MS));
    reloadState = await readSqfliteIdbState(page);
  } catch (err) {
    failures.push(`navigation/boot error: ${err.message}`);
  }

  await browser.close();

  const errorWorkerLines = workerLines.filter(
    (l) => l.startsWith('[worker.console]') && WORKER_ERROR_PATTERN.test(l),
  );

  if (pageErrors.length) {
    failures.push(`${pageErrors.length} pageerror(s): ${pageErrors.join(' | ')}`);
  }
  if (errorWorkerLines.length) {
    failures.push(`sqflite worker reported error(s): ${errorWorkerLines.join(' | ')}`);
  }
  if (!firstLoadState || !firstLoadState.dbNames || !firstLoadState.dbNames.includes(SQFLITE_IDB_NAME)) {
    failures.push(
      `first load: indexedDB.databases() did not include "${SQFLITE_IDB_NAME}" (got: ${JSON.stringify(firstLoadState && firstLoadState.dbNames)})`,
    );
  }
  if (!firstLoadState || firstLoadState.fileKeys.length === 0) {
    failures.push('first load: sqflite "files" store is empty — no database file was ever opened');
  }
  if (!firstLoadState || firstLoadState.blockKeys.length === 0) {
    failures.push(
      'first load: sqflite "blocks" store is empty — the database file exists but no SQL (e.g. CREATE TABLE) was ever executed against it; this is the exact "worker fails to instantiate its wasm" failure signature this fix addresses',
    );
  }
  if (!reloadState || reloadState.fileKeys.length === 0 || reloadState.blockKeys.length === 0) {
    failures.push('reload: sqflite files/blocks not present after reload — not proven persistent across reload');
  }

  console.log(`URL: ${TARGET_URL}`);
  console.log(`\nfirst load IDB state: ${JSON.stringify(firstLoadState)}`);
  console.log(`reload IDB state:     ${JSON.stringify(reloadState)}`);
  console.log('\n--- worker lines ---');
  console.log(workerLines.join('\n') || '(none)');
  console.log(`\npageerror count: ${pageErrors.length}`);

  if (failures.length) {
    console.log('\nFAIL:');
    for (const f of failures) console.log(`  - ${f}`);
    process.exit(1);
  }

  console.log(
    '\nPASS: SQLite/WASM backend wrote real data (files + blocks in the sqflite IndexedDB VFS) on first ' +
      'load and after reload, with zero worker instantiation errors.',
  );
  process.exit(0);
}

main().catch((e) => {
  console.error('wasm_storage_check.js crashed:', e);
  process.exit(1);
});
