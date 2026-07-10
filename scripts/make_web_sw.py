"""Generate a real caching Service Worker for the Warmer Flutter web build.

Why replace flutter_service_worker.js rather than add a second SW
---------------------------------------------------------------
flutter_bootstrap.js already registers ``flutter_service_worker.js`` (with a
``?v=<version>`` query param for cache-busting), so replacing the *content* of
that file keeps a single registration path and avoids scope conflicts that would
arise from two SWs competing at the same path.  Flutter ≥ 3.35 stopped
generating a caching SW (the generated file only unregisters itself), so this
script fills that gap.

Flutter ≥ 3.44 bootstrap registration quirk
--------------------------------------------
The Flutter-generated ``flutter_bootstrap.js`` calls::

    _flutter.loader.load({serviceWorkerSettings: {serviceWorkerVersion: "…"}})

Inside ``flutter.js`` the ``loadServiceWorker`` helper only calls
``navigator.serviceWorker.register()`` when ``serviceWorkerUrl`` is **not**
null *or* when there is an existing registration already present.  On a fresh
browser session there is no existing registration, so the SW is never
registered.

Fix: this script patches ``flutter_bootstrap.js`` to add
``serviceWorkerUrl: 'flutter_service_worker.js?v=<version>'`` into the
``serviceWorkerSettings`` object.  That satisfies ``serviceWorkerUrl != null``
and the registration runs normally.  We must keep ``serviceWorkerVersion``
untouched so flutter.js's ``_getNewServiceWorker`` comparison still works.

vercel.json
-----------
The canonical, version-controlled ``vercel.json`` (the ``/join/{code}`` SPA
rewrite + Cache-Control headers) lives at ``app/web/vercel.json``. This
script copies it into ``--build-dir`` on every run — see
``_copy_vercel_config`` — so it's always present by the time the existing
``Copy-Item ... web-dist/`` deploy step runs.

FCM background messaging (firebase-messaging-sw.js) — NOT in this file
------------------------------------------------------------------------
This SW (the one this script generates, registered at scope ``/``) does
**not** contain any FCM/push-messaging code. firebase_messaging_web's
``getToken()`` has no supported way to redirect to a custom-named SW — the
Firebase JS SDK always registers a SW literally named
``firebase-messaging-sw.js`` at the site root, scoped to
``/firebase-cloud-messaging-push-scope``. That registration is lazy (only
triggered the first time a user opts into notifications, never during
initial page load) and its scope never competes with this SW's ``/`` scope
for real page/asset traffic, so the two coexist safely as genuinely separate
files. ``firebase-messaging-sw.js`` is copied+templated into the build dir
by ``_copy_firebase_messaging_sw`` the same way ``vercel.json`` is, and is
excluded from this SW's own PRECACHE list (see ``EXCLUDE_NAMES``) since it
is a separate SW, not an app-shell asset for this one to manage. See
spec-phase6b.md's "Service worker integration (PRIME technical risk)"
section for the full rationale.

Fetch strategy
--------------
- Same-origin GET for a pre-cached URL → cache-first (ignore query params,
  which flutter_bootstrap appends as ``?v=``).
- Navigation requests (``mode == 'navigate'``) → network-first, fallback to
  cached ``/index.html`` so cold offline launch works.
- Cross-origin GETs to the payload CDN → network-first; on success put a copy
  in a separate ``warmer-payloads`` runtime cache (capped at ~8 entries).  On
  network failure serve from the runtime cache if present, otherwise let the
  request fail so the Flutter app falls back to bundled assets.

Usage
-----
    uv run python scripts/make_web_sw.py --build-dir app/build/web
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Files / patterns that must NOT appear in PRECACHE.
EXCLUDE_NAMES: frozenset[str] = frozenset(
    {
        "flutter_service_worker.js",
        ".last_build_id",
        "vercel.json",
        "firebase-messaging-sw.js",
    }
)

# Canonical, VERSION-CONTROLLED source of vercel.json (rewrites + Cache-Control
# headers). `flutter build web` does NOT copy arbitrary files out of app/web/
# into the build output (verified empirically — it only handles a fixed set
# of known assets: index.html, manifest.json, icons/, favicon.png, and files
# referenced by web plugins), so this script copies it into the build dir
# itself, once, right before the existing `Copy-Item ... web-dist/` deploy
# step picks it up. This exists because a prior version of this file lived
# ONLY inside web-dist/ (gitignored deploy-staging dir) with no tracked
# source anywhere — an `rm -rf web-dist/*.json` during a later deploy
# destroyed it with no way to recover the original rewrite + cache-control
# rules from git history. Keeping the source of truth here means that
# mistake is now a one-line `git checkout` away from being fixed.
VERCEL_CONFIG_SOURCE: Path = Path(__file__).resolve().parent.parent / "app" / "web" / "vercel.json"

# Canonical, VERSION-CONTROLLED source of the FCM background-message SW. See
# _copy_firebase_messaging_sw() for why this is copied+templated the same way
# vercel.json is above, and spec-phase6b.md's "Service worker integration
# (PRIME technical risk)" section for why it is a genuinely separate file from
# flutter_service_worker.js rather than merged into it.
FIREBASE_MESSAGING_SW_SOURCE: Path = (
    Path(__file__).resolve().parent.parent / "app" / "web" / "firebase-messaging-sw.js"
)

# Single source of truth for the Firebase web config values templated into
# firebase-messaging-sw.js — keeps the messaging SW's config from drifting
# out of step with the Dart app's own Firebase.initializeApp() config.
FIREBASE_WEB_OPTIONS_SOURCE: Path = (
    Path(__file__).resolve().parent.parent
    / "app"
    / "lib"
    / "analytics"
    / "firebase_web_options.dart"
)

# Placeholder marker in the tracked firebase-messaging-sw.js source that gets
# string-replaced with the real, extracted Firebase config object.
FIREBASE_CONFIG_PLACEHOLDER: str = "__FIREBASE_CONFIG__"

# Fields extracted from firebase_web_options.dart and templated into the
# messaging SW's firebaseConfig object. measurementId is deliberately
# excluded — it's Analytics-specific and not needed for messaging.
FIREBASE_CONFIG_FIELDS: tuple[str, ...] = (
    "apiKey",
    "authDomain",
    "projectId",
    "storageBucket",
    "messagingSenderId",
    "appId",
)

# Directory segments that exclude any file underneath them.
EXCLUDE_DIR_SEGMENTS: frozenset[str] = frozenset({".well-known"})

# Runtime cache name for cross-origin payloads.
PAYLOAD_CACHE_NAME: str = "warmer-payloads"

# CDN origin that serves daily puzzle payloads.
PAYLOAD_ORIGIN: str = "https://gaurav-gandhi-2411.github.io"

# Maximum number of payload responses to keep in the runtime cache.
PAYLOAD_CACHE_MAX: int = 8

# Cap on how long Flutter's own bootstrap loader blocks app startup waiting
# for the service worker to register/activate, in milliseconds.
#
# Root-caused live 2026-07-07 while chasing "create-group only works on the
# SECOND cold-start attempt": Flutter's flutter.js loader (FlutterServiceWorkerLoader
# class) calls `_flutter.loader.load({serviceWorkerSettings: {...}})`, and its
# `load()` method AWAITS `loadServiceWorker()` before it ever loads
# main.dart.js -- the whole app, including onboarding and every button, is
# unpainted (a blank white page) until that promise settles. Flutter's own
# default `timeoutMillis` for that wait is 4000ms, and a fresh registration on
# a cold profile routinely takes 4000-4700ms wall-clock (confirmed via a
# cold-profile headless-Chrome repro: "prepareServiceWorker took more than
# 4000ms to resolve"), which was a BLANK, unresponsive page -- any tap in that
# window (including the very first tap of a first-time visitor) lands on
# nothing and is silently lost, forcing a second, later attempt after the app
# finally paints. This is a regression from _patch_flutter_bootstrap() itself:
# before it added `serviceWorkerUrl`, a fresh session had no existing
# registration so the SW step short-circuited to Promise.resolve() with zero
# delay. Registration keeps running in the background past the timeout (it is
# a race, not a cancellation), so shortening the cap only shrinks the blank
# window -- it does not disable caching.
SW_REGISTRATION_TIMEOUT_MILLIS: int = 1000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _should_exclude(rel: Path) -> bool:
    """Return True if *rel* must be omitted from PRECACHE."""
    if rel.name in EXCLUDE_NAMES:
        return True
    for part in rel.parts:
        if part in EXCLUDE_DIR_SEGMENTS:
            return True
    return False


def _collect_files(build_dir: Path) -> list[str]:
    """Walk *build_dir* and return sorted root-relative URL strings.

    The root URL ``/`` (served from index.html) is prepended first, then all
    files are listed in sorted order so the PRECACHE array is deterministic
    across runs and platforms.
    """
    urls: list[str] = ["/"]
    for path in sorted(build_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(build_dir)
        if _should_exclude(rel):
            continue
        # Convert Windows backslashes to forward slashes for URLs.
        url = "/" + rel.as_posix()
        urls.append(url)
    return urls


def _build_cache_name(build_dir: Path) -> str:
    """Return a cache name that changes whenever any build output changes.

    Always content-derived: Flutter's version.json build_number stays "1"
    across deploys, and the shell is served cache-first, so a non-changing
    cache name would strand returning users on stale main.dart.js forever.
    Hash file bytes (not just sizes — a one-byte config change keeps size).
    """
    hasher = hashlib.sha1()  # noqa: S324  — not used for security, only cache naming
    for path in sorted(build_dir.rglob("*")):
        if path.is_file() and path.name != "flutter_service_worker.js":
            rel = path.relative_to(build_dir).as_posix()
            hasher.update(rel.encode())
            hasher.update(path.read_bytes())
    return f"warmer-precache-{hasher.hexdigest()[:12]}"


def _render_sw(cache_name: str, urls: list[str]) -> str:
    """Render the complete service-worker JavaScript source."""
    # Serialise the URL array as a pretty-printed JS literal.
    url_lines = ",\n  ".join(json.dumps(u) for u in urls)
    precache_literal = f"[\n  {url_lines}\n]"

    return f"""\
'use strict';

// Cache name changes on every deploy so stale assets are evicted immediately.
const CACHE_NAME = {json.dumps(cache_name)};
// Separate runtime cache for cross-origin daily-puzzle payloads (capped).
const PAYLOAD_CACHE = {json.dumps(PAYLOAD_CACHE_NAME)};
const PAYLOAD_ORIGIN = {json.dumps(PAYLOAD_ORIGIN)};
const PAYLOAD_CACHE_MAX = {PAYLOAD_CACHE_MAX};

// All app-shell assets to cache on install.
const PRECACHE = {precache_literal};

// Build a Set for O(1) lookup (strip query strings for flutter_bootstrap?v=…).
const PRECACHE_URLS = new Set(PRECACHE.map(u => new URL(u, self.location).pathname));

// ---------------------------------------------------------------------------
// Install — cache all app-shell assets atomically then take control immediately.
// ---------------------------------------------------------------------------
self.addEventListener('install', (event) => {{
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE))
  );
  self.skipWaiting();
}});

// ---------------------------------------------------------------------------
// Activate — evict old caches, claim all open tabs.
// ---------------------------------------------------------------------------
self.addEventListener('activate', (event) => {{
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(
        names
          .filter((n) => n !== CACHE_NAME && n !== PAYLOAD_CACHE)
          .map((n) => caches.delete(n))
      )
    ).then(() => self.clients.claim())
  );
}});

// ---------------------------------------------------------------------------
// Fetch
// ---------------------------------------------------------------------------
self.addEventListener('fetch', (event) => {{
  const req = event.request;
  const url = new URL(req.url);

  // Only handle GET requests.
  if (req.method !== 'GET') return;

  // --- Cross-origin payload CDN: network-first, runtime cache fallback. ---
  if (url.origin === PAYLOAD_ORIGIN) {{
    event.respondWith(networkFirstPayload(req));
    return;
  }}

  // Only handle same-origin requests below this point.
  if (url.origin !== self.location.origin) return;

  // --- Navigation (page load): network-first, cached /index.html fallback. ---
  if (req.mode === 'navigate') {{
    event.respondWith(networkFirstNavigate(req));
    return;
  }}

  // --- App-shell asset: cache-first (ignore ?v= query params). ---
  if (PRECACHE_URLS.has(url.pathname)) {{
    event.respondWith(cacheFirst(req));
    return;
  }}
}});

// ---------------------------------------------------------------------------
// Strategy implementations
// ---------------------------------------------------------------------------

/** Cache-first: serve from cache; populate cache on miss. */
async function cacheFirst(req) {{
  const cached = await caches.match(req, {{ ignoreSearch: true }});
  if (cached) return cached;
  const resp = await fetch(req);
  if (resp.ok) {{
    const cache = await caches.open(CACHE_NAME);
    cache.put(req, resp.clone());
  }}
  return resp;
}}

/** Network-first for navigation; fall back to cached /index.html. */
async function networkFirstNavigate(req) {{
  try {{
    const resp = await fetch(req);
    if (resp.ok) {{
      const cache = await caches.open(CACHE_NAME);
      cache.put(req, resp.clone());
    }}
    return resp;
  }} catch (_) {{
    const cached = await caches.match('/index.html');
    if (cached) return cached;
    throw _;
  }}
}}

/** Network-first for payload CDN; on success cap the runtime cache. */
async function networkFirstPayload(req) {{
  try {{
    const resp = await fetch(req);
    if (resp.ok) {{
      const cache = await caches.open(PAYLOAD_CACHE);
      await cache.put(req, resp.clone());
      await trimCache(cache, PAYLOAD_CACHE_MAX);
    }}
    return resp;
  }} catch (_) {{
    const cached = await caches.match(req, {{ cacheName: PAYLOAD_CACHE }});
    if (cached) return cached;
    throw _;
  }}
}}

/** Delete oldest entries from [cache] until at most [max] remain. */
async function trimCache(cache, max) {{
  const keys = await cache.keys();
  const toDelete = keys.slice(0, Math.max(0, keys.length - max));
  await Promise.all(toDelete.map((k) => cache.delete(k)));
}}
"""


def _copy_vercel_config(build_dir: Path) -> None:
    """Copy the tracked vercel.json into *build_dir*. Fails loudly if missing.

    A missing or forgotten vercel.json means the deployed site loses its
    /join/{code} rewrite and its Cache-Control policy silently — better to
    stop the deploy flow here than ship that regression.
    """
    if not VERCEL_CONFIG_SOURCE.is_file():
        print(
            f"ERROR: canonical vercel.json not found at {VERCEL_CONFIG_SOURCE}. "
            "The deploy would ship without the /join/{code} rewrite or Cache-Control "
            "headers. Restore it (git checkout) before deploying.",
            file=sys.stderr,
        )
        sys.exit(1)
    shutil.copyfile(VERCEL_CONFIG_SOURCE, build_dir / "vercel.json")


def _extract_firebase_web_config() -> dict[str, str]:
    """Regex-extract the Firebase web config fields out of the tracked Dart source.

    Reads ``FIREBASE_WEB_OPTIONS_SOURCE`` (the single source of truth for the
    Dart app's own ``FirebaseOptions``) and pulls each name in
    ``FIREBASE_CONFIG_FIELDS`` out with a named-capture regex of the form
    ``field:\\s*"value"``. Exits loudly (``sys.exit(1)``) if the source file is
    missing or any expected field can't be found — a silently-stale or
    partially-extracted config would ship a messaging SW that can never
    authenticate, and that failure mode is invisible until a real device
    tries to subscribe.
    """
    if not FIREBASE_WEB_OPTIONS_SOURCE.is_file():
        print(
            f"ERROR: firebase_web_options.dart not found at {FIREBASE_WEB_OPTIONS_SOURCE}. "
            "Cannot extract the Firebase web config needed by firebase-messaging-sw.js.",
            file=sys.stderr,
        )
        sys.exit(1)

    source = FIREBASE_WEB_OPTIONS_SOURCE.read_text(encoding="utf-8")
    config: dict[str, str] = {}
    for field in FIREBASE_CONFIG_FIELDS:
        match = re.search(rf'{field}:\s*"([^"]+)"', source)
        if match is None:
            print(
                f"ERROR: could not extract '{field}' from {FIREBASE_WEB_OPTIONS_SOURCE}. "
                "The Firebase web config is incomplete — fix the Dart source before "
                "building.",
                file=sys.stderr,
            )
            sys.exit(1)
        config[field] = match.group(1)
    return config


def _copy_firebase_messaging_sw(build_dir: Path) -> None:
    """Copy+template the tracked firebase-messaging-sw.js into *build_dir*.

    Mirrors ``_copy_vercel_config`` above: the canonical source lives under
    version control at ``app/web/`` (not just in gitignored build/deploy
    output), and this script is responsible for getting it into the build
    dir on every run. Additionally templates the real Firebase web config
    values (extracted from ``firebase_web_options.dart``) over the
    ``__FIREBASE_CONFIG__`` placeholder in the tracked source, mirroring how
    ``_patch_flutter_bootstrap`` does targeted string patching — this keeps
    the messaging SW's config from ever drifting out of step with the Dart
    app's own Firebase config, since there is exactly one place the values
    are hand-typed.

    Fails loudly if the tracked source is missing or the placeholder marker
    is not found (the latter would silently ship a SW that can't
    initialize).
    """
    if not FIREBASE_MESSAGING_SW_SOURCE.is_file():
        print(
            f"ERROR: canonical firebase-messaging-sw.js not found at "
            f"{FIREBASE_MESSAGING_SW_SOURCE}. Background push notifications would "
            "silently fail to register. Restore it (git checkout) before deploying.",
            file=sys.stderr,
        )
        sys.exit(1)

    template = FIREBASE_MESSAGING_SW_SOURCE.read_text(encoding="utf-8")
    if FIREBASE_CONFIG_PLACEHOLDER not in template:
        print(
            f"ERROR: {FIREBASE_MESSAGING_SW_SOURCE} is missing the "
            f"{FIREBASE_CONFIG_PLACEHOLDER} placeholder — cannot template in the real "
            "Firebase config.",
            file=sys.stderr,
        )
        sys.exit(1)

    config = _extract_firebase_web_config()
    config_literal = json.dumps(config, indent=2)
    rendered = template.replace(FIREBASE_CONFIG_PLACEHOLDER, config_literal)
    (build_dir / "firebase-messaging-sw.js").write_text(rendered, encoding="utf-8")


def _patch_flutter_bootstrap(build_dir: Path) -> bool:
    """Add ``serviceWorkerUrl`` to flutter_bootstrap.js so the SW is registered.

    Flutter ≥ 3.44 only calls ``navigator.serviceWorker.register()`` when
    ``serviceWorkerUrl != null`` in ``serviceWorkerSettings``.  The generated
    bootstrap only supplies ``serviceWorkerVersion``, so on a fresh session
    (no existing registration) the SW is silently skipped.

    This function injects ``serviceWorkerUrl: '/flutter_service_worker.js?v=<ver>'``
    (root-absolute — see below) next to ``serviceWorkerVersion`` to trigger the
    registration path.

    Returns True if the patch was applied (or was already present), False if
    the expected pattern was not found and no change was made.
    """
    bootstrap_path = build_dir / "flutter_bootstrap.js"
    if not bootstrap_path.exists():
        return False

    source = bootstrap_path.read_text(encoding="utf-8")

    # Match:  serviceWorkerVersion: "<digits>"  in the _flutter.loader.load({...}) call.
    # We look specifically in the trailing non-minified block (after the minified flutter.js).
    pattern = re.compile(r'(serviceWorkerVersion:\s*"(\d+)")')
    # Find the LAST occurrence — the minified flutter.js preamble also contains
    # 'serviceWorkerVersion' inside its own variable-destructuring pattern, but
    # the actual _flutter.loader.load({...}) invocation always appears after the
    # preamble, so the last match is the one we want to patch.
    matches = list(pattern.finditer(source))
    if not matches:
        return False

    match = matches[-1]
    version = match.group(2)

    # Check: if the text immediately following already has serviceWorkerUrl,
    # the patch was already applied in a previous run.
    tail = source[match.end() : match.end() + 80]
    if "serviceWorkerUrl" in tail:
        return True

    # Inject serviceWorkerUrl immediately after the serviceWorkerVersion entry.
    # MUST be root-absolute ("/flutter_service_worker.js"), not relative —
    # verified live 2026-07-07: a user's first visit can be a deep link like
    # /join/{code} (shared via WhatsApp before they've ever hit "/"), and a
    # relative URL there resolves to /join/flutter_service_worker.js, which
    # doesn't exist (only /join/(.*) itself is rewritten to index.html — see
    # web-dist/vercel.json). That 404s as text/html, and the browser rejects
    # the registration with "unsupported MIME type" — the SW silently never
    # installs on exactly the entry point most first-time players use.
    replacement = (
        f'{match.group(1)},\n'
        f'    serviceWorkerUrl: "/flutter_service_worker.js?v={version}",\n'
        f'    timeoutMillis: {SW_REGISTRATION_TIMEOUT_MILLIS}'
    )
    patched = source[: match.start()] + replacement + source[match.end() :]
    bootstrap_path.write_text(patched, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """Entry point: parse args, collect files, write SW."""
    parser = argparse.ArgumentParser(
        description="Replace flutter_service_worker.js with a real caching SW."
    )
    parser.add_argument(
        "--build-dir",
        required=True,
        type=Path,
        help="Path to the Flutter web build directory (e.g. app/build/web).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the generated SW to stdout without writing to disk.",
    )
    args = parser.parse_args(argv)

    build_dir: Path = args.build_dir.resolve()
    if not build_dir.is_dir():
        print(f"ERROR: build-dir does not exist: {build_dir}", file=sys.stderr)
        sys.exit(1)

    if not args.dry_run:
        _copy_vercel_config(build_dir)
        print(f"Copied: {VERCEL_CONFIG_SOURCE} -> {build_dir / 'vercel.json'}")
        _copy_firebase_messaging_sw(build_dir)
        print(
            f"Copied+templated: {FIREBASE_MESSAGING_SW_SOURCE} -> "
            f"{build_dir / 'firebase-messaging-sw.js'}"
        )

    urls = _collect_files(build_dir)
    cache_name = _build_cache_name(build_dir)
    sw_source = _render_sw(cache_name, urls)

    sw_path = build_dir / "flutter_service_worker.js"

    if args.dry_run:
        print(sw_source)
        print(
            f"\n--- dry-run: {len(urls)} URLs, cache name: {cache_name} ---",
            file=sys.stderr,
        )
        return

    sw_path.write_text(sw_source, encoding="utf-8")
    print(f"Written: {sw_path}")
    print(f"  Cache name : {cache_name}")
    print(f"  PRECACHE   : {len(urls)} entries")
    print(f"  SW size    : {sw_path.stat().st_size:,} bytes")

    # Patch flutter_bootstrap.js so the SW is actually registered on first visit.
    # Flutter ≥ 3.44 skips registration when serviceWorkerUrl is null and there
    # is no existing registration in the browser.
    patched = _patch_flutter_bootstrap(build_dir)
    if patched:
        print("Patched: flutter_bootstrap.js (added serviceWorkerUrl)")
    else:
        print(
            "WARNING: could not patch flutter_bootstrap.js — serviceWorkerVersion "
            "pattern not found; the SW may not register on first visit.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
