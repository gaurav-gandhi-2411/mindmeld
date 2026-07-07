/// Soft in-app notification opt-in ask shown on the win/loss screen, below
/// the share buttons. See spec-phase6b.md "Permission UX".
///
/// Never nags: [shouldShowNotificationOptInCard] gates visibility to
/// web-only, permission not already granted/denied at the browser level, AND
/// the card hasn't been dismissed once before (a separate local flag from a
/// browser-level denial — dismissing the in-app ask is not permanent, but
/// this phase caps re-prompting at "never show it again after one dismissal").
library;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:mindmeld/analytics/firebase_exporter.dart';
import 'package:mindmeld/notifications/notification_client.dart';
import 'package:mindmeld/notifications/notification_service.dart';
import 'package:mindmeld/stubs/analytics_stub.dart' show AnalyticsEvent;

const String _kDismissedPrefsKey = 'notif_win_card_dismissed';

/// Whether the win/loss screen should render [NotificationOptInCard] right
/// now. Safe to call unconditionally — degrades to false on any failure.
///
/// The optional [service] override lets tests avoid constructing a real
/// [NotificationService]. [isWeb] defaults to the real [kIsWeb] constant;
/// tests override it to exercise the web-only gating logic on the VM, where
/// `kIsWeb` is always false.
Future<bool> shouldShowNotificationOptInCard({
  NotificationService? service,
  bool isWeb = kIsWeb,
}) async {
  if (!isWeb) return false;
  try {
    final prefs = await SharedPreferences.getInstance();
    if (prefs.getBool(_kDismissedPrefsKey) ?? false) return false;

    final svc = service ?? buildNotificationService();
    final permission = await svc.currentPermission();
    return permission == NotifPermission.notDetermined;
  } catch (_) {
    return false;
  }
}

/// Dismissible card: "Want a reminder when tomorrow's Mindmeld is ready?"
/// with "Yes, remind me" / "Not now" buttons.
class NotificationOptInCard extends StatefulWidget {
  const NotificationOptInCard({
    super.key,
    required this.lang,
    this.notificationService,
    this.exporter,
    this.onDismissed,
  });

  /// Language to subscribe to on opt-in ('en' or 'hi-en').
  final String lang;

  /// Optional service override for tests. When null [buildNotificationService]
  /// is used.
  final NotificationService? notificationService;

  /// Optional analytics exporter override for tests.
  final AnalyticsExporter? exporter;

  /// Called once the card should no longer be shown (dismissed OR opted in
  /// successfully OR permission denied) — callers use this to hide the card.
  final VoidCallback? onDismissed;

  @override
  State<NotificationOptInCard> createState() => _NotificationOptInCardState();
}

class _NotificationOptInCardState extends State<NotificationOptInCard> {
  late final NotificationService _service =
      widget.notificationService ?? buildNotificationService();
  bool _busy = false;

  AnalyticsExporter get _analytics => widget.exporter ?? buildAnalyticsExporter();

  Future<void> _dismiss() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_kDismissedPrefsKey, true);
    await _analytics.logEvent(AnalyticsEvent.notificationOptInDismissed, {'lang': widget.lang});
    widget.onDismissed?.call();
  }

  Future<void> _optIn() async {
    setState(() => _busy = true);
    try {
      final result = await _service.optIn(lang: widget.lang);
      if (!mounted) return;

      switch (result) {
        case OptInResult.success:
          await _analytics.logEvent(
            AnalyticsEvent.notificationPermissionGranted,
            {'lang': widget.lang},
          );
          if (!mounted) return;
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text("You're in! We'll remind you when tomorrow's puzzle is ready."),
            ),
          );
          widget.onDismissed?.call();
        case OptInResult.permissionDenied:
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Notifications are blocked in your browser settings.'),
            ),
          );
          widget.onDismissed?.call();
        case OptInResult.iosNotInstalled:
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Add Mindmeld to your Home Screen first to enable reminders.'),
            ),
          );
        case OptInResult.offlineOrError:
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text("Couldn't turn on reminders — check your connection and try again."),
            ),
          );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 8),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.notifications_none, color: Theme.of(context).colorScheme.primary),
                const SizedBox(width: 8),
                const Expanded(
                  child: Text("Want a reminder when tomorrow's Mindmeld is ready?"),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                TextButton(
                  onPressed: _busy ? null : _dismiss,
                  child: const Text('Not now'),
                ),
                const SizedBox(width: 8),
                FilledButton(
                  onPressed: _busy ? null : _optIn,
                  child: _busy
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Text('Yes, remind me'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
