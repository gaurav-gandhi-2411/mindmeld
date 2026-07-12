"""Unit tests for check_uptime.py's three checks — the app root, the CDN
manifest, and one real CDN payload — including their loud-failure paths.

Network calls are mocked (via check_uptime._get) so this suite never touches
the real network; only the parsing/validation logic is under test. A live
failure of the actual endpoints is caught by the scheduled workflow
(.github/workflows/uptime-check.yml), not by this suite.

Run with:
    uv run pytest scripts/test_check_uptime.py
"""

from __future__ import annotations

import gzip
import importlib.util
import json
import sys
import urllib.error
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

_MODULE_PATH = Path(__file__).resolve().parent / "check_uptime.py"


def _load_check_uptime() -> ModuleType:
    """Import check_uptime.py by file path (scripts/ has no package __init__)."""
    spec = importlib.util.spec_from_file_location("check_uptime", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec: check_uptime.py's @dataclass needs
    # sys.modules[cls.__module__] to resolve its own type hints.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cu = _load_check_uptime()

VALID_MANIFEST = json.dumps(
    {"langs": {"en": {"days": [{"date": "2026-06-12", "file": "en/2026-06-12.json.gz"}]}}}
).encode()

VALID_PAYLOAD = gzip.compress(
    json.dumps(
        {"date": "2026-06-12", "words": {"a": [1, 0.9]}, "maxGuesses": 15, "salt": "abc"}
    ).encode()
)


def test_check_app_pass() -> None:
    with patch.object(cu, "_get", return_value=(200, b"<html>Warmer</html>")):
        result = cu.check_app("https://playwarmer.vercel.app/")
    assert result.ok


def test_check_app_fails_on_non_200() -> None:
    err = urllib.error.HTTPError("url", 404, "Not Found", {}, None)
    with patch.object(cu, "_get", side_effect=err):
        result = cu.check_app("https://playwarmer.vercel.app/")
    assert not result.ok
    assert "404" in result.detail


def test_check_app_fails_when_signature_missing() -> None:
    """A 200 that isn't actually our app (e.g. a placeholder page) must fail,
    not silently pass — this is the exact failure mode a deleted/misrouted
    Vercel project produces."""
    with patch.object(cu, "_get", return_value=(200, b"<html>Someone else's app</html>")):
        result = cu.check_app("https://playwarmer.vercel.app/")
    assert not result.ok
    assert "signature" in result.detail


def test_check_app_fails_on_unreachable() -> None:
    with patch.object(cu, "_get", side_effect=urllib.error.URLError("nope")):
        result = cu.check_app("https://playwarmer.vercel.app/")
    assert not result.ok
    assert "unreachable" in result.detail


def test_check_manifest_pass() -> None:
    with patch.object(cu, "_get", return_value=(200, VALID_MANIFEST)):
        result = cu.check_manifest("https://example.test/manifest.json")
    assert result.ok


def test_check_manifest_fails_on_invalid_json() -> None:
    with patch.object(cu, "_get", return_value=(200, b"not json")):
        result = cu.check_manifest("https://example.test/manifest.json")
    assert not result.ok
    assert "invalid JSON" in result.detail


def test_check_manifest_fails_on_empty_days() -> None:
    empty = json.dumps({"langs": {"en": {"days": []}}}).encode()
    with patch.object(cu, "_get", return_value=(200, empty)):
        result = cu.check_manifest("https://example.test/manifest.json")
    assert not result.ok


def test_check_payload_pass() -> None:
    responses = [(200, VALID_MANIFEST), (200, VALID_PAYLOAD)]
    with patch.object(cu, "_get", side_effect=responses):
        result = cu.check_payload("https://example.test/", "https://example.test/manifest.json")
    assert result.ok
    assert "1 words" in result.detail


def test_check_payload_fails_on_missing_keys() -> None:
    bad_payload = gzip.compress(json.dumps({"date": "2026-06-12"}).encode())
    responses = [(200, VALID_MANIFEST), (200, bad_payload)]
    with patch.object(cu, "_get", side_effect=responses):
        result = cu.check_payload("https://example.test/", "https://example.test/manifest.json")
    assert not result.ok
    assert "missing keys" in result.detail


def test_check_payload_fails_on_bad_gzip() -> None:
    responses = [(200, VALID_MANIFEST), (200, b"not gzip data")]
    with patch.object(cu, "_get", side_effect=responses):
        result = cu.check_payload("https://example.test/", "https://example.test/manifest.json")
    assert not result.ok
    assert "could not decode" in result.detail


def test_main_exits_nonzero_when_any_check_fails() -> None:
    ok = cu.CheckResult("cdn_manifest", True, "ok")
    ok2 = cu.CheckResult("cdn_payload", True, "ok")
    with (
        patch.object(cu, "check_app", return_value=cu.CheckResult("app", False, "boom")),
        patch.object(cu, "check_manifest", return_value=ok),
        patch.object(cu, "check_payload", return_value=ok2),
    ):
        assert cu.main([]) == 1


def test_main_exits_zero_when_all_pass() -> None:
    ok_manifest = cu.CheckResult("cdn_manifest", True, "ok")
    ok_payload = cu.CheckResult("cdn_payload", True, "ok")
    with (
        patch.object(cu, "check_app", return_value=cu.CheckResult("app", True, "ok")),
        patch.object(cu, "check_manifest", return_value=ok_manifest),
        patch.object(cu, "check_payload", return_value=ok_payload),
    ):
        assert cu.main([]) == 0


if __name__ == "__main__":
    sys.exit(__import__("pytest").main([__file__]))
