# /// script
# dependencies = ["firebase-admin>=6.5.0"]
# ///
"""Daily FCM topic broadcast — the Phase 6b scheduled sender.

Background: spec-phase6b.md rules out per-token storage and Cloud Functions
entirely (the "$0, no Blaze plan" architecture decision). Clients subscribe
to a per-language FCM *topic* (`daily-en` / `daily-hi-en`) instead of the app
tracking individual device tokens, and this script — run daily by
`.github/workflows/daily-notification.yml` via GitHub Actions cron, never by
an always-on backend — sends exactly ONE message per topic. No per-user
iteration for the actual daily nudge; that's the entire point of topics over
tokens.

Why this script also touches individual `users/{uid}` docs
------------------------------------------------------------
FCM's `subscribeToTopic` client API cannot be called from a web client (a
platform limitation of the JS SDK) — web clients can only ask a *server* to
subscribe a token to a topic. So the client side (built elsewhere) can't
subscribe itself; it can only record *intent*. When a player opts in or out
via the win-screen prompt or the Settings toggle, the client writes
`notifPendingAction: 'subscribe' | 'unsubscribe'` (plus `fcmToken` and
`notifLang`) onto its own `users/{uid}` doc and waits for this script's next
run to actually call the Admin SDK's `subscribe_to_topic` /
`unsubscribe_from_topic` on its behalf, then clears the pending flag. This
keeps the $0 architecture (no Cloud Function triggered per-write) at the
cost of up to ~24h subscribe/unsubscribe latency, which is an accepted
trade-off for a daily-cadence feature.

Order of operations on every run, regardless of manual dispatch or cron
(see run() below):
  1. Process pending `subscribe` docs -> Admin SDK subscribe_to_topic.
  2. Process pending `unsubscribe` docs -> Admin SDK unsubscribe_from_topic.
  3. Send exactly one message to `daily-en` and one to `daily-hi-en`.
Steps 1-2 run before 3 so a same-day opt-in is included in that day's send
where possible, though the topic fanout is delivered by FCM asynchronously
either way, so this ordering is a best-effort nicety, not a correctness
requirement.

Idempotency: re-running the whole script is safe. Subscribing an
already-subscribed token is a no-op per the Admin SDK. Re-sending the daily
message in a manual re-run duplicates that day's notification for already-
subscribed devices -- an accepted, documented risk (see spec's "safe to
re-run, logs success" bar); this script does not attempt exactly-once dedup.

Usage:
    uv run scripts/send_daily_notification.py
    uv run scripts/send_daily_notification.py --dry-run

Auth: reads the raw service-account JSON from the `FIREBASE_SERVICE_ACCOUNT`
environment variable (the GitHub Actions secret of the same name) -- never a
file path, never checked into the repo.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Protocol

import firebase_admin
from firebase_admin import credentials, firestore, messaging
from google.cloud.firestore_v1.client import Client as FirestoreClient

# notifLang values the client is allowed to write (mirrors firestore.rules'
# isValidNotifFields check) -- also doubles as the topic-name suffix list.
VALID_LANGS: tuple[str, ...] = ("en", "hi-en")

# Localized daily-nudge copy, keyed by notifLang/topic-suffix. The hi-en body
# matches this app's established Hinglish voice (see generator/vocab/clues-hi-en.txt
# and generator/vocab/hinglish.txt for tone/style precedent -- short, casual,
# code-switched, never a literal machine translation).
DAILY_COPY: dict[str, tuple[str, str]] = {
    "en": (
        "Today's Warmer is live!",
        "A new secret word is waiting. Can you guess it?",
    ),
    "hi-en": (
        "Aaj ka Warmer ready hai!",
        "Naya secret word wait kar raha hai. Guess kar sakte ho?",
    ),
}

# Deep link opened on notification tap. The `?notif=1` query param is load-
# bearing: the client side listens for it to log a notification_opened event.
DEEP_LINK = "https://playwarmer.vercel.app/?notif=1"


class MessagingClient(Protocol):
    """Structural interface over the subset of `firebase_admin.messaging`'s
    module-level API this script calls.

    The real `firebase_admin.messaging` module already matches this shape
    (its functions have exactly these signatures), so production code just
    passes the module object itself -- no adapter class needed. Tests pass a
    small fake that records calls instead of making real FCM requests, which
    would fail without live credentials anyway.
    """

    def subscribe_to_topic(self, tokens: list[str], topic: str) -> Any: ...  # noqa: D102
    def unsubscribe_from_topic(self, tokens: list[str], topic: str) -> Any: ...  # noqa: D102
    def send(self, message: messaging.Message) -> str: ...  # noqa: D102


def _is_valid_pending_doc(data: dict[str, Any]) -> bool:
    """Returns whether `data` has the fcmToken + notifLang a pending action needs.

    Per spec: skip (log, don't crash) any doc with a missing/invalid token or
    lang rather than failing the whole run over one malformed profile doc.
    """
    token = data.get("fcmToken")
    lang = data.get("notifLang")
    return bool(token) and isinstance(token, str) and lang in VALID_LANGS


def process_subscriptions(
    db: FirestoreClient, messaging_client: MessagingClient, *, dry_run: bool
) -> tuple[int, list[str]]:
    """Subscribes every `notifPendingAction == 'subscribe'` user to their topic.

    On success, clears `notifPendingAction` on that user's doc. Docs missing
    a usable `fcmToken`/`notifLang` are skipped (logged, not raised).

    Returns:
        (count subscribed, list of skipped doc IDs).
    """
    subscribed = 0
    skipped: list[str] = []
    query = db.collection("users").where(
        filter=firestore.FieldFilter("notifPendingAction", "==", "subscribe")
    )
    for doc in query.stream():
        data = doc.to_dict() or {}
        if not _is_valid_pending_doc(data):
            print(
                f"SKIP subscribe: users/{doc.id} has missing/invalid fcmToken or "
                f"notifLang={data.get('notifLang')!r}"
            )
            skipped.append(doc.id)
            continue
        topic = f"daily-{data['notifLang']}"
        if dry_run:
            print(f"DRY-RUN: would subscribe_to_topic users/{doc.id} -> {topic}")
        else:
            messaging_client.subscribe_to_topic([data["fcmToken"]], topic)
            doc.reference.update({"notifPendingAction": None})
            print(f"OK: subscribed users/{doc.id} -> {topic}")
        subscribed += 1
    return subscribed, skipped


def process_unsubscriptions(
    db: FirestoreClient, messaging_client: MessagingClient, *, dry_run: bool
) -> tuple[int, list[str]]:
    """Unsubscribes every `notifPendingAction == 'unsubscribe'` user from their topic.

    Reads the OLD `fcmToken`/`notifLang` before any clearing -- per spec, the
    client sets `notifPendingAction: 'unsubscribe'` alongside the still-present
    old token/lang rather than clearing them itself, so this script has what
    it needs to unsubscribe from the right topic. On success, clears
    `notifPendingAction`, `fcmToken`, and `notifLang`. Docs missing a usable
    token/lang are skipped (logged, not raised).

    Returns:
        (count unsubscribed, list of skipped doc IDs).
    """
    unsubscribed = 0
    skipped: list[str] = []
    query = db.collection("users").where(
        filter=firestore.FieldFilter("notifPendingAction", "==", "unsubscribe")
    )
    for doc in query.stream():
        data = doc.to_dict() or {}
        if not _is_valid_pending_doc(data):
            print(
                f"SKIP unsubscribe: users/{doc.id} has missing/invalid fcmToken or "
                f"notifLang={data.get('notifLang')!r}"
            )
            skipped.append(doc.id)
            continue
        topic = f"daily-{data['notifLang']}"
        if dry_run:
            print(f"DRY-RUN: would unsubscribe_from_topic users/{doc.id} -> {topic}")
        else:
            messaging_client.unsubscribe_from_topic([data["fcmToken"]], topic)
            doc.reference.update(
                {"notifPendingAction": None, "fcmToken": None, "notifLang": None}
            )
            print(f"OK: unsubscribed users/{doc.id} -> {topic}")
        unsubscribed += 1
    return unsubscribed, skipped


def send_daily_messages(
    messaging_client: MessagingClient, *, dry_run: bool
) -> dict[str, str | None]:
    """Sends the daily nudge to both `daily-en` and `daily-hi-en` topics.

    Each topic's send is isolated in its own try/except so one FCM failure
    doesn't prevent the other topic's send (see run() for how the two
    results together decide the process exit code).

    Returns:
        {topic: message_id} on a successful send, {topic: None} on failure,
        or {topic: "dry-run"} when dry_run is set (no real send() call made).
    """
    results: dict[str, str | None] = {}
    for lang, (title, body) in DAILY_COPY.items():
        topic = f"daily-{lang}"
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            webpush=messaging.WebpushConfig(
                fcm_options=messaging.WebpushFCMOptions(link=DEEP_LINK)
            ),
            topic=topic,
        )
        if dry_run:
            print(f"DRY-RUN: would send to {topic}: title={title!r} body={body!r}")
            results[topic] = "dry-run"
            continue
        try:
            message_id = messaging_client.send(message)
        except Exception as e:  # noqa: BLE001 -- isolate per-topic FCM failures, see docstring
            print(f"ERROR: send to {topic} failed: {e}", file=sys.stderr)
            results[topic] = None
            continue
        print(f"OK: sent to {topic}, message_id={message_id}")
        results[topic] = message_id
    return results


def run(db: FirestoreClient, messaging_client: MessagingClient, *, dry_run: bool) -> int:
    """Runs the full subscribe -> unsubscribe -> broadcast pipeline once.

    Returns a process exit code: 0 unless every topic's daily send failed
    (skipped/invalid per-user docs never fail the run on their own).
    """
    subscribed, sub_skipped = process_subscriptions(db, messaging_client, dry_run=dry_run)
    print(f"Subscriptions: {subscribed} subscribed, {len(sub_skipped)} skipped {sub_skipped}")

    unsubscribed, unsub_skipped = process_unsubscriptions(db, messaging_client, dry_run=dry_run)
    print(
        f"Unsubscriptions: {unsubscribed} unsubscribed, {len(unsub_skipped)} skipped "
        f"{unsub_skipped}"
    )

    message_ids = send_daily_messages(messaging_client, dry_run=dry_run)
    failed_topics = [topic for topic, mid in message_ids.items() if mid is None]
    if failed_topics and len(failed_topics) == len(message_ids):
        print(
            f"ERROR: every daily send failed ({failed_topics}) -- failing the run",
            file=sys.stderr,
        )
        return 1
    if failed_topics:
        print(f"WARNING: {failed_topics} failed to send but at least one topic succeeded")
    return 0


def _load_service_account_dict() -> dict[str, Any]:
    """Parses the `FIREBASE_SERVICE_ACCOUNT` env var (raw JSON, not a path) into a dict.

    Exits non-zero with an actionable message if the env var is missing or
    not valid JSON -- this is a hard auth failure per spec, not a skippable
    per-doc issue.
    """
    raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
    if not raw:
        print(
            "ERROR: FIREBASE_SERVICE_ACCOUNT is not set. This must be the raw service-account "
            "JSON string (Firebase console -> Project settings -> Service accounts -> generate "
            "new private key), stored as the GitHub Actions secret of the same name -- not a "
            "file path.",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"ERROR: FIREBASE_SERVICE_ACCOUNT is not valid JSON: {e}", file=sys.stderr)
        sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    """CLI entrypoint: authenticate, then run() the subscribe/unsubscribe/broadcast pipeline."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Query Firestore and build every message as normal, but skip the mutating "
            "subscribe_to_topic/unsubscribe_from_topic/send() calls -- print what WOULD "
            "happen instead. Still requires a real FIREBASE_SERVICE_ACCOUNT to authenticate "
            "the Firestore query (or FIRESTORE_EMULATOR_HOST pointed at a local emulator)."
        ),
    )
    args = parser.parse_args(argv)

    service_account_dict = _load_service_account_dict()
    if not firebase_admin._apps:  # noqa: SLF001 -- firebase_admin has no public "is any app initialized" check
        firebase_admin.initialize_app(credentials.Certificate(service_account_dict))
    db = firestore.client()

    exit_code = run(db, messaging, dry_run=args.dry_run)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
