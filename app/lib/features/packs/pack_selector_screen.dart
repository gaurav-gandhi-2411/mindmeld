import 'package:flutter/material.dart';
import 'package:mindmeld/core/design_tokens.dart';
import 'package:mindmeld/core/packs.dart';
import 'package:mindmeld/core/persistence.dart';
import 'package:mindmeld/features/packs/pack_puzzle_list_screen.dart';
import 'package:mindmeld/iap/entitlements.dart';
import 'package:mindmeld/iap/revenuecat_gateway.dart';

/// Grid of themed-pack tiles (phase 6c) — entry point pushed from the
/// Practice tab and from the Settings "Themed Packs" row.
///
/// Live + unlocked packs show "won/count" progress and are tappable.
/// Live + locked packs (native only — web is always unlocked, see
/// [packUnlocked]) show a lock chip and open a purchase sheet.
/// "coming_soon" packs are dimmed and not tappable.
class PackSelectorScreen extends StatefulWidget {
  const PackSelectorScreen({
    super.key,
    required this.lang,
    this.catalog,
    this.iapGateway,
  });

  final String lang;

  /// Optional [PackCatalog] override (used in tests). When null a default
  /// [PackCatalog] is constructed (production behaviour: network-first with
  /// bundled-asset fallback).
  final PackCatalog? catalog;

  /// Optional [IapGateway] override (used in tests). When null
  /// [buildIapGateway] is used.
  final IapGateway? iapGateway;

  @override
  State<PackSelectorScreen> createState() => _PackSelectorScreenState();
}

class _PackSelectorScreenState extends State<PackSelectorScreen> {
  late final PackCatalog _catalog;
  late final IapGateway _gateway;

  List<Pack> _packs = const [];
  Map<String, int> _progress = const {};
  Entitlements _entitlements = Entitlements.empty;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _catalog = widget.catalog ?? PackCatalog();
    _gateway = widget.iapGateway ?? buildIapGateway();
    _load();
  }

  Future<void> _load() async {
    try {
      final result = await _catalog.fetch();
      final entitlements = await _gateway.current();
      final progress = <String, int>{};
      for (final pack in result.manifest.packs) {
        progress[pack.id] =
            await AppPersistence.instance.packProgress(pack.id, widget.lang);
      }
      if (mounted) {
        setState(() {
          _packs = result.manifest.packs;
          _entitlements = entitlements;
          _progress = progress;
          _loading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = e.toString();
          _loading = false;
        });
      }
    }
  }

  void _openPack(Pack pack) {
    Navigator.push(
      context,
      MaterialPageRoute<void>(
        builder: (_) => PackPuzzleListScreen(
          pack: pack,
          lang: widget.lang,
          iapGateway: _gateway,
        ),
      ),
    ).then((_) => _load()); // refresh progress after returning from play.
  }

  Future<void> _showUnlockSheet(Pack pack) async {
    final confirmed = await showModalBottomSheet<bool>(
      context: context,
      builder: (_) => _PackUnlockSheet(pack: pack, lang: widget.lang),
    );
    if (confirmed != true) return;

    final outcome = await _gateway.purchasePack(pack.id);
    if (!mounted) return;

    final message = switch (outcome) {
      PurchaseOutcome.success => '${pack.titleFor(widget.lang)} unlocked!',
      PurchaseOutcome.cancelled => 'Purchase cancelled.',
      PurchaseOutcome.failed => 'Purchase failed. Please try again.',
      PurchaseOutcome.comingSoon =>
        'Coming soon! Pack purchases will be available in a future update.',
    };
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));

    if (outcome == PurchaseOutcome.success) {
      final entitlements = await _gateway.current();
      if (mounted) setState(() => _entitlements = entitlements);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Themed Packs')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(WarmerSpacing.xl),
                    child: Text('Failed to load packs: $_error'),
                  ),
                )
              : _packs.isEmpty
                  ? const Center(child: Text('No packs available yet.'))
                  : GridView.extent(
                      padding: const EdgeInsets.all(WarmerSpacing.lg),
                      // Responsive columns: ~2 on phones, more on wide
                      // viewports — keeps the quiet cards compact instead of
                      // stretching two tall columns across desktop widths.
                      maxCrossAxisExtent: 260,
                      childAspectRatio: 0.88,
                      crossAxisSpacing: 12,
                      mainAxisSpacing: 12,
                      children: _packs.map(_buildTile).toList(),
                    ),
    );
  }

  Widget _buildTile(Pack pack) {
    final comingSoon = !pack.isLive;
    final unlocked = packUnlocked(pack, _entitlements);
    final won = _progress[pack.id] ?? 0;
    final tokens = Theme.of(context).extension<WarmerTokens>() ?? WarmerTokens.light;

    return Opacity(
      opacity: comingSoon ? 0.55 : 1.0,
      child: Card(
        clipBehavior: Clip.antiAlias,
        margin: EdgeInsets.zero,
        child: InkWell(
          onTap: comingSoon
              ? null
              : (unlocked ? () => _openPack(pack) : () => _showUnlockSheet(pack)),
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.max,
              children: [
                Container(
                  width: 44,
                  height: 44,
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(14),
                    gradient: LinearGradient(
                      begin: Alignment.topLeft,
                      end: Alignment.bottomRight,
                      colors: [pack.accent, pack.accentDark],
                    ),
                  ),
                  child: Icon(pack.iconData, color: Colors.white, size: 24),
                ),
                const Spacer(),
                Text(
                  pack.titleFor(widget.lang),
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(
                        fontWeight: FontWeight.w700,
                        color: tokens.text1,
                      ),
                ),
                const SizedBox(height: WarmerSpacing.xs),
                Text(
                  pack.taglineFor(widget.lang),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context)
                      .textTheme
                      .bodySmall
                      ?.copyWith(color: tokens.text2),
                ),
                const SizedBox(height: WarmerSpacing.sm),
                if (comingSoon)
                  const Chip(
                    label: Text('Coming soon'),
                    visualDensity: VisualDensity.compact,
                  )
                else if (!unlocked)
                  const Chip(
                    avatar: Icon(Icons.lock, size: 14),
                    label: Text('Unlock'),
                    visualDensity: VisualDensity.compact,
                  )
                else
                  Text(
                    '$won/${pack.count}',
                    style: Theme.of(context)
                        .textTheme
                        .labelSmall
                        ?.copyWith(color: tokens.text2),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// Bottom sheet shown when tapping a locked (native-only) pack tile.
class _PackUnlockSheet extends StatelessWidget {
  const _PackUnlockSheet({required this.pack, required this.lang});

  final Pack pack;
  final String lang;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(WarmerSpacing.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Unlock ${pack.titleFor(lang)}',
                style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: WarmerSpacing.sm),
            Text('Get all ${pack.count} puzzles in this pack.'),
            const SizedBox(height: 20),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Unlock pack'),
            ),
            const SizedBox(height: WarmerSpacing.xs),
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Not now'),
            ),
          ],
        ),
      ),
    );
  }
}
