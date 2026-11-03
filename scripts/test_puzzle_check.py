"""Tests for the notification puzzle-exists gate (puzzle_check.py + main() wiring).

No network, no Firebase: fetches are fakes and firebase_admin is stubbed.

Run with:
    uv run --with pytest pytest scripts/test_puzzle_check.py
"""

from __future__ import annotations

import gzip
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))
import puzzle_check as pc  # noqa: E402

GOOD: dict[str, Any] = {
    "v": 3,
    "lang": "en",
    "date": "2026-11-03",
    "model": "m",
    "n": 2,
    "salt": "abc",
    "s": "eHg=",
    "words": {"aaaaaaaaaaaa": [1, 30000]},
    "hints": [[5, "word"]],
}


def _gz(obj: object) -> bytes:
    return gzip.compress(json.dumps(obj).encode())


def _fake(status: int, body: bytes = b""):  # noqa: ANN202
    calls: list[str] = []

    def fetch(url: str) -> tuple[int, bytes]:
        calls.append(url)
        return status, body

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


def test_present_and_valid() -> None:
    fetch = _fake(200, _gz(GOOD))
    status, _ = pc.check_puzzle("en", "2026-11-03", fetch)
    assert status is pc.PuzzleStatus.OK
    assert fetch.calls == [  # type: ignore[attr-defined]
        "https://gaurav-gandhi-2411.github.io/mindmeld-payloads/en/2026-11-03.json.gz"
    ]


def test_404_is_missing() -> None:
    status, _ = pc.check_puzzle("en", "2026-12-15", _fake(404))
    assert status is pc.PuzzleStatus.MISSING


@pytest.mark.parametrize(
    "body",
    [
        b"not gzip at all",
        gzip.compress(b"{not json"),
        gzip.compress(b"\xff\xfe"),
        _gz([1, 2]),
        _gz({k: v for k, v in GOOD.items() if k != "salt"}),
        _gz({**GOOD, "words": {"x": ["a", 1]}}),
        _gz({**GOOD, "hints": [[1, 2]]}),
        _gz({**GOOD, "v": True}),
    ],
)
def test_invalid(body: bytes) -> None:
    status, detail = pc.check_puzzle("en", "2026-11-03", _fake(200, body))
    assert status is pc.PuzzleStatus.INVALID
    assert detail.startswith("en:")


def test_network_error_and_500_raise() -> None:
    def boom(url: str) -> tuple[int, bytes]:
        raise TimeoutError(url)

    with pytest.raises(TimeoutError):
        pc.check_puzzle("en", "2026-11-03", boom)
    with pytest.raises(RuntimeError):
        pc.check_puzzle("en", "2026-11-03", _fake(500))


def test_check_all_requires_every_lang() -> None:
    def fetch(url: str) -> tuple[int, bytes]:
        return (200, _gz(GOOD)) if "/en/" in url else (404, b"")

    status, _ = pc.check_all(("en", "hi-en"), "2026-11-03", fetch)
    assert status is pc.PuzzleStatus.MISSING


def test_today_ist_format() -> None:
    assert len(pc.today_ist()) == 10


# --- main() wiring: send path must not run when the gate fails -------------------------


def _load_sender(monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, list[str]]:
    """Import send_daily_notification with firebase stubbed; returns (module, call log)."""
    log: list[str] = []
    fb = ModuleType("firebase_admin")
    fb._apps = {}  # type: ignore[attr-defined]
    fb.initialize_app = lambda *a, **k: log.append("init_app")  # type: ignore[attr-defined]
    fb.credentials = ModuleType("credentials")  # type: ignore[attr-defined]
    fb.credentials.Certificate = lambda d: d  # type: ignore[attr-defined]
    fb.firestore = ModuleType("firestore")  # type: ignore[attr-defined]
    fb.firestore.client = lambda: log.append("firestore.client")  # type: ignore[attr-defined]
    fb.messaging = ModuleType("messaging")  # type: ignore[attr-defined]
    gc = ModuleType("google.cloud.firestore_v1.client")
    gc.Client = object  # type: ignore[attr-defined]
    for name, mod in {
        "firebase_admin": fb,
        "firebase_admin.credentials": fb.credentials,  # type: ignore[attr-defined]
        "firebase_admin.firestore": fb.firestore,  # type: ignore[attr-defined]
        "firebase_admin.messaging": fb.messaging,  # type: ignore[attr-defined]
        "google.cloud.firestore_v1.client": gc,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)
    spec = importlib.util.spec_from_file_location(
        "send_daily_notification_t", _SCRIPTS / "send_daily_notification.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run = lambda *a, **k: log.append("run") or 0  # type: ignore[attr-defined]
    return mod, log


def test_main_missing_puzzle_exits_0_without_sending(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mod, log = _load_sender(monkeypatch)
    real = pc.check_all
    monkeypatch.setattr(pc, "check_all", lambda langs, d: real(langs, d, _fake(404)))
    with pytest.raises(SystemExit) as exc:
        mod.main(["--date", "2026-12-15"])
    assert exc.value.code == 0
    assert "no puzzle for 2026-12-15" in capsys.readouterr().out.splitlines()
    assert log == []  # no Firestore, no FCM, no run()


def test_main_network_error_fails_closed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mod, log = _load_sender(monkeypatch)

    def boom(langs: tuple[str, ...], date: str) -> None:
        raise TimeoutError("timed out")

    monkeypatch.setattr(pc, "check_all", boom)
    with pytest.raises(SystemExit) as exc:
        mod.main(["--date", "2026-11-03"])
    assert exc.value.code == 1
    assert "no puzzle for" not in capsys.readouterr().out
    assert log == []


def test_main_valid_puzzle_proceeds_to_send(monkeypatch: pytest.MonkeyPatch) -> None:
    mod, log = _load_sender(monkeypatch)
    monkeypatch.setattr(pc, "check_all", lambda langs, d: (pc.PuzzleStatus.OK, []))
    monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT", "{}")
    with pytest.raises(SystemExit) as exc:
        mod.main(["--date", "2026-11-03", "--dry-run"])
    assert exc.value.code == 0
    assert "run" in log
