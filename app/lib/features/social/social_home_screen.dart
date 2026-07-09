import 'package:flutter/material.dart';

import 'package:mindmeld/features/social/display_name_dialog.dart';
import 'package:mindmeld/features/social/group_leaderboard_screen.dart';
import 'package:mindmeld/social/social_models.dart';
import 'package:mindmeld/social/social_service.dart';

/// "Play with friends" home: my groups list + create/join entry points.
///
/// Silent anonymous auth is NOT triggered just by opening this screen — only
/// by tapping Create or Join (the actual social action), per spec. A player
/// who has never used social features sees a gentle connect prompt here,
/// never a blocker; solo play is entirely unaffected either way.
class SocialHomeScreen extends StatefulWidget {
  const SocialHomeScreen({
    super.key,
    required this.date,
    required this.lang,
    this.socialService,
    this.active = true,
  });

  final String date;
  final String lang;
  final SocialService? socialService;

  /// Whether this tab is the currently-selected destination in the app
  /// shell's [IndexedStack].
  ///
  /// [SocialHomeScreen] is mounted eagerly at boot (all `IndexedStack`
  /// children build regardless of which index is selected) and only ever
  /// loaded once in [initState] — mirrors the same staleness pattern fixed
  /// for [StatsScreen] (see its doc comment). Unlike stats, this screen
  /// already has a manual pull-to-refresh, but nothing re-triggered it on
  /// tab reactivation. [_SocialHomeScreenState.didUpdateWidget] reloads
  /// whenever [active] transitions false→true. Defaults to `true` so direct
  /// usages (tests, the win/loss "Challenge your group" push) reload on
  /// every build as before.
  final bool active;

  @override
  State<SocialHomeScreen> createState() => _SocialHomeScreenState();
}

class _SocialHomeScreenState extends State<SocialHomeScreen> {
  late final SocialService _service = widget.socialService ?? buildSocialService();
  List<SocialGroup>? _groups;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  @override
  void didUpdateWidget(SocialHomeScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    // Reload on false→true activation (tab becomes visible again after
    // groups may have changed elsewhere in this session — e.g. joining via
    // a deep link, or a friend's win landing on this device). Unlike
    // StatsScreen, the group list itself isn't lang-scoped, so no
    // lang-change trigger is needed here.
    final becameActive = widget.active && !oldWidget.active;
    if (becameActive) _refresh();
  }

  Future<void> _refresh() async {
    if (!_service.hasLocalIdentity) {
      setState(() => _groups = []);
      return;
    }
    final groups = await _service.myGroups();
    if (mounted) setState(() => _groups = groups);
  }

  Future<String?> _resolveDisplayName() async {
    final cached = await _service.cachedDisplayName();
    if (cached != null) return cached;
    if (!mounted) return null;
    return promptDisplayName(context);
  }

  Future<void> _createGroup() async {
    final name = await promptDisplayName(
      context,
      title: 'Name your group',
    );
    if (name == null) return;
    final displayName = await _resolveDisplayName();
    if (displayName == null) return;
    if (!mounted) return;

    setState(() => _busy = true);
    try {
      final group = await _service.createGroup(groupName: name, displayName: displayName);
      if (!mounted) return;

      if (group == null) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text("Couldn't create the group — check your connection and try again."),
          ),
        );
        return;
      }
      await _refresh();
      if (!mounted) return;
      _showInviteSheet(group);
    } catch (e) {
      // SocialService.createGroup never throws by contract, but this
      // guarantees the button always leaves its loading state and no
      // failure is ever silent, regardless of cause.
      debugPrint('SocialHomeScreen._createGroup unexpected error: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Something went wrong creating the group: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _joinByCode() async {
    final code = await showDialog<String>(
      context: context,
      builder: (ctx) {
        final controller = TextEditingController();
        return AlertDialog(
          title: const Text('Join a group'),
          content: TextField(
            controller: controller,
            autofocus: true,
            textCapitalization: TextCapitalization.characters,
            decoration: const InputDecoration(labelText: 'Invite code'),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
            FilledButton(
              onPressed: () => Navigator.pop(ctx, controller.text.trim()),
              child: const Text('Join'),
            ),
          ],
        );
      },
    );
    if (code == null || code.isEmpty) return;
    final displayName = await _resolveDisplayName();
    if (displayName == null) return;
    if (!mounted) return;

    setState(() => _busy = true);
    try {
      final result = await _service.joinByCode(code: code, displayName: displayName);
      if (!mounted) return;

      switch (result.status) {
        case JoinCodeStatus.success:
          await _refresh();
          break;
        case JoinCodeStatus.codeNotFound:
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('That code doesn\'t match any group.')),
          );
          break;
        case JoinCodeStatus.offline:
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text("Couldn't join — check your connection and try again.")),
          );
          break;
      }
    } catch (e) {
      debugPrint('SocialHomeScreen._joinByCode unexpected error: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Something went wrong joining the group: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _showInviteSheet(SocialGroup group) {
    showModalBottomSheet<void>(
      context: context,
      builder: (ctx) => Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('"${group.name}" is ready!', style: Theme.of(ctx).textTheme.titleLarge),
            const SizedBox(height: 12),
            Text('Code: ${group.code}', style: Theme.of(ctx).textTheme.titleMedium),
            const SizedBox(height: 4),
            SelectableText(group.joinLink),
            const SizedBox(height: 16),
            FilledButton(
              onPressed: () {
                Navigator.pop(ctx);
                _openGroup(group);
              },
              child: const Text('View leaderboard'),
            ),
          ],
        ),
      ),
    );
  }

  void _openGroup(SocialGroup group) {
    Navigator.of(context).push(MaterialPageRoute<void>(
      builder: (_) => GroupLeaderboardScreen(
        group: group,
        date: widget.date,
        lang: widget.lang,
        socialService: _service,
      ),
    ));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Play with friends')),
      body: Stack(
        children: [
          _groups == null
              ? const Center(child: CircularProgressIndicator())
              : RefreshIndicator(
                  onRefresh: _refresh,
                  child: _buildBody(context),
                ),
          // Visible loading overlay while a create/join is in flight — not
          // just a disabled button — so "nothing happens" can never be the
          // honest description of what the user sees.
          if (_busy)
            Positioned.fill(
              child: ColoredBox(
                color: Colors.black.withValues(alpha: 0.35),
                child: const Center(
                  child: Card(
                    child: Padding(
                      padding: EdgeInsets.all(24),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          CircularProgressIndicator(),
                          SizedBox(height: 16),
                          Text('Connecting…'),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
      floatingActionButton: _groups != null && _groups!.isNotEmpty
          ? FloatingActionButton(
              onPressed: _busy ? null : _joinByCode,
              tooltip: 'Join a group',
              child: const Icon(Icons.group_add),
            )
          : null,
    );
  }

  Widget _buildBody(BuildContext context) {
    final groups = _groups!;
    if (groups.isEmpty) {
      return ListView(
        padding: const EdgeInsets.all(24),
        children: [
          const SizedBox(height: 40),
          Icon(Icons.groups_outlined, size: 72, color: Theme.of(context).colorScheme.primary),
          const SizedBox(height: 16),
          Text(
            'Connect to play with friends',
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 8),
          const Text(
            'Compare daily results on a private leaderboard — no email or '
            'password needed.',
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 24),
          FilledButton.icon(
            onPressed: _busy ? null : _createGroup,
            icon: const Icon(Icons.add),
            label: const Text('Create a group'),
          ),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: _busy ? null : _joinByCode,
            icon: const Icon(Icons.group_add),
            label: const Text('Join a group'),
          ),
        ],
      );
    }

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        for (final g in groups)
          Card(
            child: ListTile(
              leading: const Icon(Icons.groups),
              title: Text(g.name),
              subtitle: Text('${g.memberUids.length} member${g.memberUids.length == 1 ? '' : 's'}'),
              onTap: () => _openGroup(g),
            ),
          ),
        const SizedBox(height: 16),
        Center(
          child: OutlinedButton.icon(
            onPressed: _busy ? null : _createGroup,
            icon: const Icon(Icons.add),
            label: const Text('Create another group'),
          ),
        ),
      ],
    );
  }
}
