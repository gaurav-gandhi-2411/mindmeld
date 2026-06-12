import 'package:flutter/material.dart';
import 'package:mindmeld/core/config.dart';
import 'package:mindmeld/iap/entitlements.dart';
import 'package:mindmeld/iap/revenuecat_gateway.dart';
import 'package:mindmeld/stubs/iap_stub.dart';
import 'package:shared_preferences/shared_preferences.dart';

const String _kLangPref = 'selected_lang';

/// Returns the currently selected language, defaulting to 'en'.
Future<String> loadSelectedLang() async {
  final prefs = await SharedPreferences.getInstance();
  return prefs.getString(_kLangPref) ?? 'en';
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
  });

  final String currentLang;
  final ValueChanged<String> onLangChanged;
  final VoidCallback onReplayOnboarding;

  /// Optional IAP gateway; package-private for test injection.
  final IapGateway? iapGateway;

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  // The gateway: provided by test or built from AppConfig.
  late final IapGateway _gateway;
  late String _lang;
  Entitlements _entitlements = Entitlements.empty;

  @override
  void initState() {
    super.initState();
    _lang = widget.currentLang;
    _gateway = widget.iapGateway ?? buildIapGateway();
    _loadEntitlements();
  }

  Future<void> _loadEntitlements() async {
    final e = await _gateway.current();
    if (mounted) setState(() => _entitlements = e);
  }

  Future<void> _setLang(String lang) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_kLangPref, lang);
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

  @override
  Widget build(BuildContext context) {
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
          ...IapProduct.values.map(
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
                        ? const Icon(Icons.check_circle, color: Colors.green)
                        : _entitlements.archive && p == IapProduct.archive
                            ? const Icon(Icons.check_circle, color: Colors.green)
                            : const Icon(Icons.chevron_right))
                    : const Chip(label: Text('Soon')),
                enabled: available,
                onTap: available ? () => _purchase(p) : null,
              );
            },
          ),

          // Restore purchases (only visible when iap is wired up)
          if (AppConfig.iapEnabled)
            ListTile(
              leading: const Icon(Icons.restore),
              title: const Text('Restore Purchases'),
              onTap: _restore,
            ),

          const Divider(),

          // Onboarding + About
          ListTile(
            leading: const Icon(Icons.help_outline),
            title: const Text('How to play'),
            onTap: widget.onReplayOnboarding,
          ),
          const ListTile(
            leading: Icon(Icons.info_outline),
            title: Text('About'),
            subtitle: Text('Mindmeld v1.0.0 — Semantic Daily Word Game'),
          ),
        ],
      ),
    );
  }
}
