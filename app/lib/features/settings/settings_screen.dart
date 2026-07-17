import 'package:flutter/material.dart';
import 'package:mindmeld/ads/consent_manager.dart';
import 'package:mindmeld/core/config.dart';
import 'package:mindmeld/core/design_tokens.dart';
import 'package:mindmeld/features/packs/pack_selector_screen.dart';
import 'package:mindmeld/iap/entitlements.dart';
import 'package:mindmeld/iap/revenuecat_gateway.dart';
import 'package:mindmeld/notifications/notification_client.dart';
import 'package:mindmeld/notifications/notification_service.dart';
import 'package:mindmeld/social/social_service.dart';
import 'package:mindmeld/stubs/iap_stub.dart';
import 'package:shared_preferences/shared_preferences.dart';

const String _kLangPref = 'selected_lang';
const String _kRivalEnabledPref = 'rival_enabled';
const String _kRivalTierPref = 'rival_tier';

/// URL shown in the privacy policy dialog.
///
/// url_launcher is not a current dependency; we show a selectable-text dialog
/// so the user can copy the URL. Tracked as a named constant for easy update.
const String _kPrivacyPolicyUrl =
    'https://gaurav-gandhi-2411.github.io/mindmeld-payloads/privacy.html';

/// Returns the currently selected language, defaulting to 'en'.
Future<String> loadSelectedLang() async {
  final prefs = await SharedPreferences.getInstance();
  return prefs.getString(_kLangPref) ?? 'en';
}

/// Persists [lang] as the selected language — the write counterpart to
/// [loadSelectedLang].
///
/// Exposed publicly (not just via [_SettingsScreenState._setLang]) so
/// [OnboardingFlow]'s language toggle — a brand-new player choosing Hinglish
/// before ever reaching Settings — can persist the same pref without
/// duplicating the key.
Future<void> setSelectedLang(String lang) async {
  final prefs = await SharedPreferences.getInstance();
  await prefs.setString(_kLangPref, lang);
}

/// Snackbar text shown after a purchase attempt in stub / coming-soon mode.
const String _kComingSoonMessage =
    'Coming soon! In-app purchases will be available in the next update.';

/// Settings screen: language toggle, IAP, replay onboarding, about.
class SettingsScreen extends StatefulWidget {
  const SettingsScreen({
    super.key,
    required this.currentLang,
    required this.onLangChanged,
    required this.onReplayOnboarding,
    /// Optional gateway override for tests. When null [buildIapGateway] is used.
    this.iapGateway,
    /// Optional notification service override for tests. When null
    /// [buildNotificationService] is used.
    this.notificationService,
    /// Optional social service override for tests (used by the "Delete my
    /// data" action). When null [buildSocialService] is used.
    this.socialService,
  });

  final String currentLang;
  final ValueChanged<String> onLangChanged;
  final VoidCallback onReplayOnboarding;

  /// Optional IAP gateway; package-private for test injection.
  final IapGateway? iapGateway;

  /// Optional notification service override; package-private for test injection.
  final NotificationService? notificationService;

  /// Optional social service override; package-private for test injection.
  final SocialService? socialService;

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  // The gateway: provided by test or built from AppConfig.
  late final IapGateway _gateway;
  late String _lang;
  Entitlements _entitlements = Entitlements.empty;

  /// Whether the UMP SDK requires a privacy options entry point in this region.
  ///
  /// Starts as false and is set asynchronously in [initState] so the tile
  /// only appears once the SDK has confirmed it is needed. When adsEnabled is
  /// false [ConsentManager.isPrivacyOptionsRequired] returns false immediately
  /// without any platform channel call, so the tile never renders in test builds.
  bool _privacyOptionsRequired = false;
  bool _rivalEnabled = true;
  String _rivalTier = 'even';

  late final NotificationService _notifService;
  NotifPermission _notifPermission = NotifPermission.notDetermined;
  bool _notifSubscribedLocally = false;
  bool _notifBusy = false;

  late final SocialService _socialService;
  bool _deletingData = false;

  @override
  void initState() {
    super.initState();
    _lang = widget.currentLang;
    _gateway = widget.iapGateway ?? buildIapGateway();
    _notifService = widget.notificationService ?? buildNotificationService();
    _socialService = widget.socialService ?? buildSocialService();
    _loadEntitlements();
    _checkPrivacyOptionsRequired();
    _loadRivalSettings();
    _loadNotifState();
  }

  Future<void> _loadNotifState() async {
    final permission = await _notifService.currentPermission();
    final subscribed = await _notifService.isSubscribedLocally();
    if (mounted) {
      setState(() {
        _notifPermission = permission;
        _notifSubscribedLocally = subscribed;
      });
    }
  }

  /// Turning the Notifications toggle on/off. Denial at the browser level is
  /// never re-prompted — [NotificationService.optIn] already enforces this,
  /// but the honest subtitle text (see [_notifStatusText]) is what actually
  /// prevents the user from expecting a prompt that will never come.
  Future<void> _setNotifEnabled(bool value) async {
    setState(() => _notifBusy = true);
    try {
      if (value) {
        final result = await _notifService.optIn(lang: _lang);
        if (!mounted) return;
        final message = switch (result) {
          OptInResult.success => 'Reminders are on.',
          OptInResult.permissionDenied =>
            'Notifications are blocked in your browser settings.',
          OptInResult.iosNotInstalled =>
            'Add Warmer to your Home Screen first to enable reminders.',
          OptInResult.offlineOrError =>
            "Couldn't turn on reminders — check your connection and try again.",
        };
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
      } else {
        await _notifService.optOut();
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Reminders are off.')),
        );
      }
    } finally {
      await _loadNotifState();
      if (mounted) setState(() => _notifBusy = false);
    }
  }

  /// Honest state text for the Notifications section — never claims a state
  /// the app hasn't actually verified.
  String _notifStatusText(bool enabled) {
    if (_notifService.iosNotInstalled) {
      return 'Add to Home Screen to enable notifications';
    }
    if (_notifPermission == NotifPermission.denied) {
      return 'Notifications blocked in your browser settings';
    }
    return enabled ? 'On' : 'Off';
  }

  Future<void> _checkPrivacyOptionsRequired() async {
    final required = await ConsentManager.isPrivacyOptionsRequired();
    if (mounted) setState(() => _privacyOptionsRequired = required);
  }

  Future<void> _loadRivalSettings() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      if (mounted) {
        setState(() {
          _rivalEnabled = prefs.getBool(_kRivalEnabledPref) ?? true;
          _rivalTier = prefs.getString(_kRivalTierPref) ?? 'even';
        });
      }
    } catch (_) {
      // SharedPreferences not available in test environments without mock setup;
      // silently retain default values.
    }
  }

  Future<void> _setRivalEnabled(bool value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_kRivalEnabledPref, value);
    if (mounted) setState(() => _rivalEnabled = value);
  }

  Future<void> _setRivalTier(String tier) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_kRivalTierPref, tier);
    if (mounted) setState(() => _rivalTier = tier);
  }

  Future<void> _loadEntitlements() async {
    final e = await _gateway.current();
    if (mounted) setState(() => _entitlements = e);
  }

  Future<void> _setLang(String lang) async {
    await setSelectedLang(lang);
    setState(() => _lang = lang);
    widget.onLangChanged(lang);
  }

  Future<void> _purchase(IapProduct product) async {
    final outcome = await _gateway.purchase(product);
    if (!mounted) return;

    final message = switch (outcome) {
      PurchaseOutcome.success => 'Purchase successful!',
      PurchaseOutcome.cancelled => 'Purchase cancelled.',
      PurchaseOutcome.failed => 'Purchase failed. Please try again.',
      // Stub mode always returns comingSoon — preserves Phase 1 snackbar text.
      PurchaseOutcome.comingSoon => _kComingSoonMessage,
    };

    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message)),
    );

    if (outcome == PurchaseOutcome.success) {
      // Refresh entitlement cache after a successful purchase.
      await _loadEntitlements();
    }
  }

  /// Opens the themed-pack selector (phase 6c) — replaces the old "Soon"
  /// stub row now that packs have a real purchase/play flow.
  void _openPacks() {
    Navigator.push(
      context,
      MaterialPageRoute<void>(builder: (_) => PackSelectorScreen(lang: _lang)),
    );
  }

  Future<void> _restore() async {
    await _gateway.restore();
    await _loadEntitlements();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Purchases restored.')),
    );
  }

  /// Archive row subtitle: "Unlocked" when entitled, "Coming soon" otherwise.
  String _archiveSubtitle() {
    if (_entitlements.archive) return 'Unlocked';
    return 'Coming soon';
  }

  /// Delegates to [ConsentManager.showPrivacyOptions].
  ///
  /// Only reachable when [AppConfig.adsEnabled] is true AND
  /// [_privacyOptionsRequired] is true, so the platform channel call is always
  /// appropriate.
  Future<void> _showPrivacyOptions() async {
    await ConsentManager.showPrivacyOptions();
  }

  /// Shows the privacy policy URL in a [SelectableText] dialog.
  ///
  /// url_launcher is not a current dependency; a dialog lets the user long-press
  /// to copy the URL on any platform without adding a new package.
  void _showPrivacyPolicyDialog() {
    showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Privacy Policy'),
        content: const SelectableText(_kPrivacyPolicyUrl),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const Text('Close'),
          ),
        ],
      ),
    );
  }

  /// "Delete my data": confirms, then calls [SocialService.deleteMyData].
  ///
  /// See [SocialService.deleteMyData]'s doc comment for exactly what this
  /// deletes vs. leaves as accepted residual (documented in
  /// docs/privacy-policy.md). This action does NOT touch local-only
  /// gameplay data (guess history, streaks, pack progress) — those have no
  /// server-side copy and are unaffected either way.
  Future<void> _deleteMyData() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete my data?'),
        content: const Text(
          'This removes your display name, group memberships, and past '
          'leaderboard results from our servers. Your local gameplay '
          'history (guesses, streaks) stays on this device and is not '
          'affected. This cannot be undone.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    if (!mounted) return;

    setState(() => _deletingData = true);
    try {
      final result = await _socialService.deleteMyData();
      if (!mounted) return;
      final message = switch (result.status) {
        DeleteMyDataStatus.success => 'Your data has been deleted.',
        DeleteMyDataStatus.notSignedIn =>
          "You haven't used Play with Friends, so there's nothing to delete.",
        DeleteMyDataStatus.offline =>
          "Couldn't delete your data — check your connection and try again.",
      };
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
    } finally {
      if (mounted) setState(() => _deletingData = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final tokens = Theme.of(context).extension<WarmerTokens>() ?? WarmerTokens.light;
    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: ListView(
        children: [
          // Language
          const ListTile(
            title: Text('Language'),
            dense: true,
            enabled: false,
          ),
          ...AppConfig.supportedLangs.map(
            (lang) => ListTile(
              title: Text(AppConfig.langLabels[lang] ?? lang),
              leading: Radio<String>(
                value: lang,
                // ignore: deprecated_member_use
                groupValue: _lang,
                // ignore: deprecated_member_use
                onChanged: (v) {
                  if (v != null) _setLang(v);
                },
              ),
              onTap: () => _setLang(lang),
            ),
          ),

          const Divider(),

          // IAP section
          const ListTile(
            title: Text('In-App Purchases'),
            dense: true,
            enabled: false,
          ),
          // Themed Packs (phase 6c) is a navigation row, not a purchase row —
          // it opens the pack selector rather than IapGateway.purchase().
          // Excluded from the generic products loop below.
          ...IapProduct.values
              .where((p) => p != IapProduct.themedPacks)
              .map(
            (p) {
              final available = IapStub.isAvailable(p);
              // For the archive product, show unlocked state when entitled.
              final subtitle = p == IapProduct.archive
                  ? _archiveSubtitle()
                  : (available ? 'Coming soon' : 'Coming in a future update');
              return ListTile(
                title: Text(IapStub.productNames[p] ?? p.name),
                subtitle: Text(subtitle),
                trailing: available
                    ? (_entitlements.removeAds && p == IapProduct.removeAds
                        ? Icon(Icons.check_circle, color: tokens.accentText)
                        : _entitlements.archive && p == IapProduct.archive
                            ? Icon(Icons.check_circle, color: tokens.accentText)
                            : const Icon(Icons.chevron_right))
                    : const Chip(label: Text('Soon')),
                enabled: available,
                onTap: available ? () => _purchase(p) : null,
              );
            },
          ),
          ListTile(
            title: Text(IapStub.productNames[IapProduct.themedPacks] ?? 'Themed Packs'),
            subtitle: const Text('Bollywood, Cricket, Food & more'),
            trailing: const Icon(Icons.chevron_right),
            onTap: _openPacks,
          ),

          // Restore purchases (only visible when iap is wired up on native).
          // iapEnabledEffective is false on web (purchases_flutter is native-only).
          if (AppConfig.iapEnabledEffective)
            ListTile(
              leading: const Icon(Icons.restore),
              title: const Text('Restore Purchases'),
              onTap: _restore,
            ),

          const Divider(),

          // Privacy section
          //
          // "Privacy options" — only shown when adsEnabled AND the UMP SDK has
          // confirmed a privacy-options entry point is required for this user's
          // region (EEA/UK). In all test builds adsEnabled=false, so this tile
          // never renders in tests.
          if (AppConfig.adsEnabledEffective && _privacyOptionsRequired)
            ListTile(
              leading: const Icon(Icons.shield_outlined),
              title: const Text('Privacy options'),
              onTap: _showPrivacyOptions,
            ),

          // "Privacy policy" — always visible regardless of monetisation flags.
          // Opens a dialog with a selectable URL (url_launcher is not a dep).
          ListTile(
            leading: const Icon(Icons.policy_outlined),
            title: const Text('Privacy policy'),
            onTap: _showPrivacyPolicyDialog,
          ),

          // "Delete my data" — always visible; deleteMyData() itself
          // degrades gracefully to a friendly "nothing to delete" message
          // for a player who has never used Play with Friends.
          ListTile(
            leading: const Icon(Icons.delete_outline),
            title: const Text('Delete my data'),
            subtitle: const Text('Removes your social data from our servers'),
            enabled: !_deletingData,
            onTap: _deleteMyData,
          ),

          // Onboarding + About
          ListTile(
            leading: const Icon(Icons.help_outline),
            title: const Text('How to play'),
            onTap: widget.onReplayOnboarding,
          ),
          const ListTile(
            leading: Icon(Icons.info_outline),
            title: Text('About'),
            subtitle: Text('Warmer v1.0.0 — Semantic Daily Word Game'),
          ),

          const Divider(),

          // Race the Bot
          const ListTile(
            title: Text('Race the Bot'),
            dense: true,
            enabled: false,
          ),
          SwitchListTile(
            title: const Text('Enable rival'),
            subtitle: const Text('Race an AI opponent each day'),
            value: _rivalEnabled,
            onChanged: _setRivalEnabled,
          ),
          if (_rivalEnabled) ...[
            const Padding(
              padding: EdgeInsets.only(left: WarmerSpacing.lg, top: WarmerSpacing.xs, bottom: 2),
              child: Text('Difficulty',
                  style: TextStyle(fontWeight: FontWeight.w500)),
            ),
            RadioListTile<String>(
              title: const Text('Chill'),
              subtitle: const Text('Easier — slower solver (~par +4)'),
              value: 'chill',
              // ignore: deprecated_member_use
              groupValue: _rivalTier,
              // ignore: deprecated_member_use
              onChanged: (v) {
                if (v != null) _setRivalTier(v);
              },
            ),
            RadioListTile<String>(
              title: const Text('Even'),
              subtitle: const Text('Matched — similar pace (~par)'),
              value: 'even',
              // ignore: deprecated_member_use
              groupValue: _rivalTier,
              // ignore: deprecated_member_use
              onChanged: (v) {
                if (v != null) _setRivalTier(v);
              },
            ),
            RadioListTile<String>(
              title: const Text('Sharp'),
              subtitle: const Text('Harder — fast solver (~par −2)'),
              value: 'sharp',
              // ignore: deprecated_member_use
              groupValue: _rivalTier,
              // ignore: deprecated_member_use
              onChanged: (v) {
                if (v != null) _setRivalTier(v);
              },
            ),
          ],

          // Notifications — real push delivery is web-only this phase
          // (native push out of scope, see spec-phase6b.md); the toggle
          // itself renders cross-platform since [NotificationService]
          // degrades gracefully everywhere.
          const Divider(),
          const ListTile(
            title: Text('Notifications'),
            dense: true,
            enabled: false,
          ),
          SwitchListTile(
            title: const Text('Daily puzzle reminder'),
            subtitle: Text(
              _notifStatusText(_notifPermission == NotifPermission.granted &&
                  _notifSubscribedLocally),
            ),
            value: _notifPermission == NotifPermission.granted && _notifSubscribedLocally,
            onChanged: _notifBusy ? null : _setNotifEnabled,
          ),
        ],
      ),
    );
  }
}
