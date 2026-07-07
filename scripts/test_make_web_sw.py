"""Unit tests for the FCM-messaging-SW pieces added to make_web_sw.py.

Covers `_extract_firebase_web_config` (regex extraction out of the tracked
Dart source) and `_copy_firebase_messaging_sw` (copy+template into a build
dir), including their loud-failure paths — a silently-stale or
partially-extracted Firebase config would ship a messaging SW that can never
authenticate, which is invisible until a real device tries to subscribe.

Run with:
    uv run pytest scripts/test_make_web_sw.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_MODULE_PATH = Path(__file__).resolve().parent / "make_web_sw.py"


def _load_make_web_sw() -> ModuleType:
    """Import make_web_sw.py by file path (scripts/ has no package __init__)."""
    spec = importlib.util.spec_from_file_location("make_web_sw", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


make_web_sw = _load_make_web_sw()

_VALID_DART_SOURCE = """
const FirebaseOptions firebaseWebOptions = FirebaseOptions(
  apiKey: "AIzaSyTestKey123",
  authDomain: "test-project.firebaseapp.com",
  projectId: "test-project",
  storageBucket: "test-project.firebasestorage.app",
  messagingSenderId: "111222333",
  appId: "1:111222333:web:abcdef123456",
  measurementId: "G-TESTID123"
);
"""

_SW_TEMPLATE = "const firebaseConfig = __FIREBASE_CONFIG__;\n"


def test_extract_firebase_web_config_happy_path(tmp_path: Path) -> None:
    """All six required fields are extracted with their exact values."""
    dart_file = tmp_path / "firebase_web_options.dart"
    dart_file.write_text(_VALID_DART_SOURCE, encoding="utf-8")
    make_web_sw.FIREBASE_WEB_OPTIONS_SOURCE = dart_file

    config = make_web_sw._extract_firebase_web_config()

    assert config == {
        "apiKey": "AIzaSyTestKey123",
        "authDomain": "test-project.firebaseapp.com",
        "projectId": "test-project",
        "storageBucket": "test-project.firebasestorage.app",
        "messagingSenderId": "111222333",
        "appId": "1:111222333:web:abcdef123456",
    }
    # measurementId is deliberately excluded — not needed for messaging.
    assert "measurementId" not in config


def test_extract_firebase_web_config_missing_source_exits(tmp_path: Path) -> None:
    """A missing firebase_web_options.dart is a loud failure, not a silent one."""
    make_web_sw.FIREBASE_WEB_OPTIONS_SOURCE = tmp_path / "does_not_exist.dart"

    with pytest.raises(SystemExit) as exc_info:
        make_web_sw._extract_firebase_web_config()
    assert exc_info.value.code == 1


def test_extract_firebase_web_config_missing_field_exits(tmp_path: Path) -> None:
    """A source file missing one expected field fails loudly, not partially."""
    dart_file = tmp_path / "firebase_web_options.dart"
    # Drop appId entirely to simulate a malformed/edited source file.
    incomplete = _VALID_DART_SOURCE.replace('appId: "1:111222333:web:abcdef123456",\n', "")
    dart_file.write_text(incomplete, encoding="utf-8")
    make_web_sw.FIREBASE_WEB_OPTIONS_SOURCE = dart_file

    with pytest.raises(SystemExit) as exc_info:
        make_web_sw._extract_firebase_web_config()
    assert exc_info.value.code == 1


def test_copy_firebase_messaging_sw_templates_real_config(tmp_path: Path) -> None:
    """The placeholder is replaced with the real, extracted config; no marker remains."""
    dart_file = tmp_path / "firebase_web_options.dart"
    dart_file.write_text(_VALID_DART_SOURCE, encoding="utf-8")
    sw_source = tmp_path / "firebase-messaging-sw.js"
    sw_source.write_text(_SW_TEMPLATE, encoding="utf-8")
    build_dir = tmp_path / "build"
    build_dir.mkdir()

    make_web_sw.FIREBASE_WEB_OPTIONS_SOURCE = dart_file
    make_web_sw.FIREBASE_MESSAGING_SW_SOURCE = sw_source

    make_web_sw._copy_firebase_messaging_sw(build_dir)

    rendered = (build_dir / "firebase-messaging-sw.js").read_text(encoding="utf-8")
    assert make_web_sw.FIREBASE_CONFIG_PLACEHOLDER not in rendered
    assert '"apiKey": "AIzaSyTestKey123"' in rendered
    assert '"projectId": "test-project"' in rendered


def test_copy_firebase_messaging_sw_missing_source_exits(tmp_path: Path) -> None:
    """A missing tracked firebase-messaging-sw.js is a loud failure."""
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    make_web_sw.FIREBASE_MESSAGING_SW_SOURCE = tmp_path / "does_not_exist.js"

    with pytest.raises(SystemExit) as exc_info:
        make_web_sw._copy_firebase_messaging_sw(build_dir)
    assert exc_info.value.code == 1


def test_copy_firebase_messaging_sw_missing_placeholder_exits(tmp_path: Path) -> None:
    """A tracked source missing the __FIREBASE_CONFIG__ marker fails loudly."""
    dart_file = tmp_path / "firebase_web_options.dart"
    dart_file.write_text(_VALID_DART_SOURCE, encoding="utf-8")
    sw_source = tmp_path / "firebase-messaging-sw.js"
    sw_source.write_text("const firebaseConfig = {};\n", encoding="utf-8")
    build_dir = tmp_path / "build"
    build_dir.mkdir()

    make_web_sw.FIREBASE_WEB_OPTIONS_SOURCE = dart_file
    make_web_sw.FIREBASE_MESSAGING_SW_SOURCE = sw_source

    with pytest.raises(SystemExit) as exc_info:
        make_web_sw._copy_firebase_messaging_sw(build_dir)
    assert exc_info.value.code == 1


def test_firebase_messaging_sw_excluded_from_precache() -> None:
    """firebase-messaging-sw.js must never be listed as an app-shell asset."""
    assert "firebase-messaging-sw.js" in make_web_sw.EXCLUDE_NAMES


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
