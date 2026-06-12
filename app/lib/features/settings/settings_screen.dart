import 'package:flutter/material.dart';
import 'package:mindmeld/core/config.dart';
import 'package:mindmeld/stubs/iap_stub.dart';
import 'package:shared_preferences/shared_preferences.dart';

const String _kLangPref = 'selected_lang';

/// Returns the currently selected language, defaulting to 'en'.
Future<String> loadSelectedLang() async {
  final prefs = await SharedPreferences.getInstance();
  return prefs.getString(_kLangPref) ?? 'en';
}

/// Settings screen: language toggle, IAP stubs, replay onboarding, about.
class SettingsScreen extends StatefulWidget {
  const SettingsScreen({
    super.key,
    required this.currentLang,
    required this.onLangChanged,
    required this.onReplayOnboarding,
  });

  final String currentLang;
  final ValueChanged<String> onLangChanged;
  final VoidCallback onReplayOnboarding;

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _iap = const IapStub();
  late String _lang;

  @override
  void initState() {
    super.initState();
    _lang = widget.currentLang;
  }

  Future<void> _setLang(String lang) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_kLangPref, lang);
    setState(() => _lang = lang);
    widget.onLangChanged(lang);
  }

  Future<void> _purchase(IapProduct product) async {
    final result = await _iap.purchase(product);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(result.message)),
    );
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
                onChanged: (v) { if (v != null) _setLang(v); },
              ),
              onTap: () => _setLang(lang),
            ),
          ),

          const Divider(),

          // IAP stubs
          const ListTile(
            title: Text('In-App Purchases'),
            dense: true,
            enabled: false,
          ),
          ...IapProduct.values.map(
            (p) => ListTile(
              title: Text(IapStub.productNames[p] ?? p.name),
              subtitle: IapStub.isAvailable(p)
                  ? const Text('Coming soon')
                  : const Text('Coming in a future update'),
              trailing: IapStub.isAvailable(p)
                  ? const Icon(Icons.chevron_right)
                  : const Chip(label: Text('Soon')),
              enabled: IapStub.isAvailable(p),
              onTap: IapStub.isAvailable(p) ? () => _purchase(p) : null,
            ),
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
