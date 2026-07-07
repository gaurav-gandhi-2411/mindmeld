"""Firestore-emulator test for scripts/send_daily_notification.py's
subscribe/unsubscribe/broadcast logic.

Mirrors this repo's existing JS emulator-test style (rules.test.js,
create_group_flow.test.js: a `check(name, fn)` pass/fail accumulator, never
a framework-managed test runner) rather than introducing pytest as a new
Python test dependency into a repo that has none for scripts/ today.

Runs against the Firestore emulator only (never production). Connects with
a plain `google.cloud.firestore.Client` + `AnonymousCredentials` instead of
going through `firebase_admin` -- `google.cloud.firestore_v1.base_client
.BaseClient.__init__` reads the `FIRESTORE_EMULATOR_HOST` env var and, when
credentials are already supplied, uses them as-is against the emulator's
insecure local channel (verified by reading that source directly; the
emulator never validates the credential, so AnonymousCredentials works).
This sidesteps needing a real (or even well-formed) service-account JSON
just to run this test -- the script's own `main()` still requires the real
`FIREBASE_SERVICE_ACCOUNT` secret for production runs.

`send_daily_notification.py` is a standalone PEP 723 script (no package
`__init__.py`, no root pyproject.toml for scripts/), so it's imported here
by file path via importlib rather than a normal package import.

The actual FCM Admin SDK calls (`subscribe_to_topic`, `unsubscribe_from_topic`,
`send`) are never exercised against real FCM here -- they'd fail without live
credentials regardless. A `_FakeMessagingClient` (matching
send_daily_notification.MessagingClient's structural shape) is injected in
their place to record calls instead.

Run (from repo root, needs JDK 21+ -- same requirement as the other
firebase-tests):
    JAVA_HOME=<jdk21+ path> firebase-tests/node_modules/.bin/firebase \\
        emulators:exec --project demo-mindmeld-rules-test --only firestore \\
        "uv run --with firebase-admin python firebase-tests/send_daily_notification_test.py"
"""

from __future__ import annotations

import importlib.util
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore

# --- import scripts/send_daily_notification.py by file path (see module docstring) ---
_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "send_daily_notification.py"
_spec = importlib.util.spec_from_file_location("send_daily_notification", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None, f"could not load {_SCRIPT_PATH}"
send_daily_notification = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(send_daily_notification)

passed = 0
failed = 0


def check(name: str, fn: Callable[[], None]) -> None:
    """Runs `fn`, printing ok/FAIL and tallying results (mirrors rules.test.js's check())."""
    global passed, failed
    try:
        fn()
        passed += 1
        print(f"  ok - {name}")
    except Exception as e:  # noqa: BLE001 -- this is a top-level test-runner catch-all, not app code
        failed += 1
        print(f"  FAIL - {name}")
        print(f"    {e}")


class _FakeMessagingClient:
    """Records subscribe/unsubscribe/send calls instead of hitting real FCM."""

    def __init__(self) -> None:
        self.subscribed: list[tuple[list[str], str]] = []
        self.unsubscribed: list[tuple[list[str], str]] = []
        self.sent: list[Any] = []

    def subscribe_to_topic(self, tokens: list[str], topic: str) -> None:
        self.subscribed.append((tokens, topic))

    def unsubscribe_from_topic(self, tokens: list[str], topic: str) -> None:
        self.unsubscribed.append((tokens, topic))

    def send(self, message: Any) -> str:
        self.sent.append(message)
        return f"fake-message-id-{len(self.sent)}"


def _seed_fixtures(db: firestore.Client) -> None:
    """Seeds four users/{uid} docs covering the subscribe/unsubscribe/skip/untouched cases."""
    users = db.collection("users")
    users.document("alice").set(
        {
            "displayName": "Alice",
            "fcmToken": "alice-token",
            "notifLang": "en",
            "notifPendingAction": "subscribe",
        }
    )
    users.document("bob").set(
        {
            "displayName": "Bob",
            "fcmToken": "bob-token",
            "notifLang": "hi-en",
            "notifPendingAction": "unsubscribe",
        }
    )
    users.document("carol").set(
        # Pending subscribe but no usable token -- must be skipped, not crash the run.
        {
            "displayName": "Carol",
            "fcmToken": None,
            "notifLang": "en",
            "notifPendingAction": "subscribe",
        }
    )
    users.document("dave").set(
        # No pending action at all -- must never be touched by either pass.
        {
            "displayName": "Dave",
            "fcmToken": "dave-token",
            "notifLang": "en",
            "notifPendingAction": None,
        }
    )


def main() -> None:
    """Seeds fixtures, exercises the script's Firestore-processing functions, and asserts."""
    os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080")
    db = firestore.Client(project="demo-mindmeld-rules-test", credentials=AnonymousCredentials())
    _seed_fixtures(db)
    fake = _FakeMessagingClient()

    def check_subscriptions() -> None:
        count, skipped = send_daily_notification.process_subscriptions(db, fake, dry_run=False)
        assert count == 1, f"expected 1 subscribed, got {count}"
        assert skipped == ["carol"], f"expected carol skipped, got {skipped}"
        assert fake.subscribed == [(["alice-token"], "daily-en")], (
            f"unexpected subscribe_to_topic calls: {fake.subscribed}"
        )

    def check_alice_cleared() -> None:
        data = db.collection("users").document("alice").get().to_dict() or {}
        assert data.get("notifPendingAction") is None, f"alice's pending action not cleared: {data}"

    def check_carol_untouched() -> None:
        data = db.collection("users").document("carol").get().to_dict() or {}
        assert data.get("notifPendingAction") == "subscribe", f"carol should be untouched: {data}"

    def check_unsubscriptions() -> None:
        count, skipped = send_daily_notification.process_unsubscriptions(db, fake, dry_run=False)
        assert count == 1, f"expected 1 unsubscribed, got {count}"
        assert skipped == [], f"expected no skips, got {skipped}"
        assert fake.unsubscribed == [(["bob-token"], "daily-hi-en")], (
            f"unexpected unsubscribe_from_topic calls: {fake.unsubscribed}"
        )

    def check_bob_cleared() -> None:
        data = db.collection("users").document("bob").get().to_dict() or {}
        assert (
            data.get("notifPendingAction") is None
            and data.get("fcmToken") is None
            and data.get("notifLang") is None
        ), f"bob's fields not fully cleared: {data}"

    def check_dave_untouched() -> None:
        data = db.collection("users").document("dave").get().to_dict() or {}
        assert data.get("fcmToken") == "dave-token" and data.get("notifLang") == "en", (
            f"dave should be untouched: {data}"
        )

    def check_send_daily_messages() -> None:
        message_ids = send_daily_notification.send_daily_messages(fake, dry_run=False)
        assert set(message_ids.keys()) == {"daily-en", "daily-hi-en"}, message_ids.keys()
        assert len(fake.sent) == 2, f"expected exactly 2 send() calls, got {len(fake.sent)}"
        assert {m.topic for m in fake.sent} == {"daily-en", "daily-hi-en"}

    def check_run_exit_code_is_zero() -> None:
        # run() re-processes the now-cleared pending flags (both already
        # None) plus a fresh broadcast -- exercises the full orchestration
        # function, not just the three pieces above in isolation.
        exit_code = send_daily_notification.run(db, fake, dry_run=False)
        assert exit_code == 0, f"expected exit code 0, got {exit_code}"

    check(
        "process_subscriptions subscribes alice, skips carol (missing token)",
        check_subscriptions,
    )
    check("alice's notifPendingAction is cleared after subscribe", check_alice_cleared)
    check("carol's pending action is left untouched (skip, not crash)", check_carol_untouched)
    check("process_unsubscriptions unsubscribes bob", check_unsubscriptions)
    check(
        "bob's fcmToken/notifLang/notifPendingAction all cleared after unsubscribe",
        check_bob_cleared,
    )
    check("dave (no pending action) is never touched by either pass", check_dave_untouched)
    check(
        "send_daily_messages sends exactly one message per topic via the fake client",
        check_send_daily_messages,
    )
    check("run() orchestrates all three steps and returns exit code 0", check_run_exit_code_is_zero)

    print(f"\n{passed} passed, {failed} failed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
