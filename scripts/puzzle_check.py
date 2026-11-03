"""Is today's puzzle actually published? Gate for the daily push notification.

Stdlib-only on purpose so it is importable (and unit-testable) without
firebase-admin. Mirrors the app's loader:

  * URL:   {payloadBaseUrl}/{lang}/{date}.json.gz
           app/lib/core/config.dart:139-140, app/lib/core/payload_client.dart:148
  * "Missing" is HTTP 404 only (payload_client.dart:96-97); any other non-200 is an
    error, not a "no puzzle" signal, so it fails closed here.
  * "Valid" = gzip -> UTF-8 -> JSON object (payload_codec.dart:24-27) with the keys
    DailyPayload.fromJson requires and their types (app/lib/core/models.dart:176-235):
    v:int, lang:str, date:str, model:str, n:int, salt:str, s:str,
    words:{hash:[int,int]}, hints:[[int,str]]. Optional keys (alt, rival, ...) are not checked.
  * "Today": the app uses the device-local date (app/lib/main.dart:357-359). Players are
    India-first and the cron fires at 03:00 UTC = 08:30 IST, when the IST and UTC dates
    agree, so today is computed in IST (fixed +05:30, no tzdata dependency).
"""

from __future__ import annotations

import gzip
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from enum import Enum

PAYLOAD_BASE_URL = "https://gaurav-gandhi-2411.github.io/mindmeld-payloads"
TIMEOUT_S = 10  # same as PayloadClient._timeout
IST = timezone(timedelta(hours=5, minutes=30))

Fetch = Callable[[str], tuple[int, bytes]]


class PuzzleStatus(Enum):
    OK = "ok"
    MISSING = "missing"
    INVALID = "invalid"


def today_ist() -> str:
    """Today's date (YYYY-MM-DD) in IST."""
    return datetime.now(UTC).astimezone(IST).strftime("%Y-%m-%d")


def default_fetch(url: str) -> tuple[int, bytes]:
    """GET `url`; returns (status, body). HTTP error statuses are returned, not raised.

    Transport errors (DNS, timeout, connection reset) propagate to the caller.
    """
    req = urllib.request.Request(url, headers={"User-Agent": "mindmeld-notify-check/1"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""


def payload_url(lang: str, date: str, base_url: str = PAYLOAD_BASE_URL) -> str:
    """The exact URL PayloadClient._fetchNetwork requests."""
    return f"{base_url}/{lang}/{date}.json.gz"


def _is_pair(value: object, second: type) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= 2
        and isinstance(value[0], int)
        and isinstance(value[1], second)
    )


def _has_type(obj: dict, key: str, typ: type) -> bool:
    value = obj.get(key)
    return isinstance(value, typ) and not isinstance(value, bool)


def validate_payload(raw: bytes) -> str | None:
    """Returns None if `raw` decodes like the Dart codec, else a reason string."""
    try:
        obj = json.loads(gzip.decompress(raw).decode("utf-8"))
    except (OSError, EOFError, ValueError) as exc:  # gzip / utf-8 / json errors
        return f"cannot decode: {exc}"
    if not isinstance(obj, dict):
        return "JSON root is not an object"
    for key, typ in (
        ("v", int),
        ("n", int),
        ("lang", str),
        ("date", str),
        ("model", str),
        ("salt", str),
        ("s", str),
    ):
        if not _has_type(obj, key, typ):
            return f"missing or wrong-typed key {key!r}"
    words = obj.get("words")
    if not isinstance(words, dict) or not all(_is_pair(x, int) for x in words.values()):
        return "missing or malformed 'words'"
    hints = obj.get("hints")
    if not isinstance(hints, list) or not all(_is_pair(x, str) for x in hints):
        return "missing or malformed 'hints'"
    return None


def check_puzzle(
    lang: str, date: str, fetch: Fetch = default_fetch, base_url: str = PAYLOAD_BASE_URL
) -> tuple[PuzzleStatus, str]:
    """Fetches and validates one language's puzzle for `date`.

    Raises on transport errors or non-200/non-404 statuses (caller fails closed).
    """
    status, body = fetch(payload_url(lang, date, base_url))
    if status == 404:
        return PuzzleStatus.MISSING, f"{lang}: HTTP 404"
    if status != 200:
        msg = f"{lang}: unexpected HTTP {status}"
        raise RuntimeError(msg)
    reason = validate_payload(body)
    if reason is not None:
        return PuzzleStatus.INVALID, f"{lang}: {reason}"
    return PuzzleStatus.OK, f"{lang}: ok"


def check_all(
    langs: tuple[str, ...], date: str, fetch: Fetch = default_fetch
) -> tuple[PuzzleStatus, list[str]]:
    """Every language must be OK; returns the first non-OK status (or OK) plus details."""
    details: list[str] = []
    worst = PuzzleStatus.OK
    for lang in langs:
        status, detail = check_puzzle(lang, date, fetch)
        details.append(detail)
        if status is not PuzzleStatus.OK and worst is PuzzleStatus.OK:
            worst = status
    return worst, details
