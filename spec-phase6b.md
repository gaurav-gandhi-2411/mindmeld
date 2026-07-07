# Mindmeld — Phase 6b: Daily Push Notifications

## Why this phase
For a daily-habit game, a "today's puzzle is live" nudge is the highest-ROI retention lever that exists — it's what converts a one-time player into a daily returner. Built on the Firebase setup from 6a and the existing service worker.

## Architecture decision — $0, no Blaze plan
- **Broadcast via FCM topics, not stored tokens.** Clients that opt in subscribe to a per-language topic (`daily-en`, `daily-hi-en`). The daily send is ONE message to the topic — no token database, no per-token iteration, no stale-token cleanup for the basic daily nudge.
- **Scheduled via GitHub Actions cron, not Cloud Functions.** A daily scheduled workflow in the existing GitHub setup runs a small script that sends the topic message via the Firebase Admin SDK (authenticated with a service-account key stored as a GitHub secret). This avoids the Blaze (pay-as-you-go) plan entirely and reuses the same "scheduled job" pattern as the payload-publish pipeline.
- Net: daily push with zero new paid dependencies and no new always-on backend.

## Non-negotiables
- Solo + social core keep working with notifications denied or unsupported. Notifications are purely additive.
- Never nag: ask permission at a good moment (not first load), respect denial permanently, one daily notification max in this phase.
- Wordle-style engagement, not dependency pressure.

## Scope (MVP this phase)
Daily "puzzle is live" web push. Permission opt-in on the win screen. Topic subscription. One scheduled GitHub Action that broadcasts daily. Foreground + background message handling via the existing SW. Analytics on sent/opened.

### Out of scope (later)
- **Streak reminders** ("your streak ends tonight") — needs per-user targeting + server-side play-state (currently local). Deferred; noted as the natural 6b-follow-on once play-state is server-visible.
- **Per-timezone send bucketing** — MVP sends once at a single time (India-first, ~8:30am IST); global users receive at their local offset, acceptable for validation. Store user timezone now so bucketed topics (`daily-en-utc+X`) are a later, non-breaking upgrade.
- **Native push** — FCM works on native too, but native builds stay behind their existing flags; this phase targets web.

## Permission UX
- Do NOT prompt on first load (kills opt-in rates). Prompt contextually: on the **win/loss screen**, a soft in-app ask — "Want a reminder when tomorrow's Mindmeld is ready?" → only if yes, trigger the browser permission prompt.
- Also a toggle in Settings → Notifications (on/off) that subscribes/unsubscribes the topic.
- If denied at the browser level: show the state honestly in Settings (how to re-enable via site settings), never re-prompt automatically.
- iOS reality: web push works ONLY on an INSTALLED PWA on iOS 16.4+. On iOS Safari (not installed), the opt-in nudges "Add to Home Screen first" instead of failing silently.

## Service worker integration (PRIME technical risk)
- The app already ships a custom generated SW (`make_web_sw.py`) for offline caching, and it's boot-sensitive (the cold-start timeout fix). FCM web messaging needs a background message handler. Do NOT add a second competing service worker — **integrate FCM messaging into the existing SW** (or the FCM `onBackgroundMessage` handler must coexist without breaking the offline-cache SW or re-introducing the boot stall). Verify cold-start boot timing is unchanged after integration.

## Data / config additions
- Client stores the granted state + subscribed topic(s) locally; subscribes/unsubscribes via FCM.
- User timezone captured (for later bucketing) — stored on the 6a `users/{uid}` doc if signed in, else locally.
- No token DB needed for topic broadcast.

## Scheduled sender (GitHub Actions)
- A workflow (`.github/workflows/daily-notification.yml`) on a cron schedule (daily, ~08:30 IST = 03:00 UTC) runs a script (`scripts/send_daily_notification.py` or `.js`) that:
  - Authenticates with the Firebase Admin SDK via a service-account JSON stored in a GitHub secret (`FIREBASE_SERVICE_ACCOUNT`).
  - Sends a notification message to `daily-en` and `daily-hi-en` topics with title/body copy (localized per topic; Hinglish body for hi-en) and a click action deep-linking to the app.
  - Is idempotent / safe to re-run; logs success.
- Manual trigger (`workflow_dispatch`) enabled for testing.

## Acceptance criteria
1. Opt-in on win/loss screen → browser permission prompt only after in-app yes; grant subscribes the correct per-language topic; Settings toggle subscribes/unsubscribes.
2. Denial handled gracefully and permanently (no auto re-prompt); Settings shows honest state.
3. iOS-not-installed path nudges Add-to-Home-Screen rather than failing.
4. FCM messaging integrated into the EXISTING service worker; offline caching still works; cold-start boot timing unchanged (verify via the cold-profile headless harness).
5. Foreground message → in-app toast/handling; background message → system notification; tapping it opens the app (deep link to today's puzzle).
6. GitHub Actions workflow sends to both topics on schedule AND via manual dispatch; authenticated by the service-account secret; a manual-dispatch run delivers a real notification to a subscribed test device.
7. Analytics: `notification_permission_granted`, `notification_sent` (from the workflow, or client-open proxy), `notification_opened` fire with params.
8. All existing solo/social tests stay green; notifications fully additive (denied/unsupported → everything else works).
9. Live verify: subscribe on a real browser, trigger the workflow manually, receive the notification, tap → lands on today's puzzle.

## Manual steps (GG — CC will provide exact steps; these need console/secret access only you have)
1. Firebase console → Cloud Messaging: confirm the API is enabled; under Web configuration, **generate a Web Push certificate (VAPID key pair)** — CC needs the PUBLIC VAPID key wired into the web app.
2. Create a **Firebase service-account key** (Project settings → Service accounts → generate new private key JSON).
3. Add it as a GitHub Actions secret `FIREBASE_SERVICE_ACCOUNT` on the mindmeld repo.
4. (No Blaze plan required.)

## Risks
- **SW integration** (above) — the one place this can break existing behavior; treat with the cold-profile harness as the gate.
- **iOS web push constraints** — set expectations; installed-PWA-only on iOS 16.4+.
- **Opt-in rate** — contextual timing (win screen) matters; don't prompt cold.
- **Single-time send** — fine for India-first validation; revisit with timezone buckets on signal.
