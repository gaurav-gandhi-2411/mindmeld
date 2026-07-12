import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:intl/intl.dart';

import 'package:mindmeld/core/config.dart';
import 'package:mindmeld/core/design_tokens.dart';
import 'package:mindmeld/social/social_models.dart';
import 'package:mindmeld/social/social_service.dart';

import 'package:mindmeld/features/win/share_stub.dart'
    if (dart.library.html) 'package:mindmeld/features/win/share_web.dart';

/// Per-group, per-day leaderboard.
///
/// SPOILER SAFETY: a row for a member with [LeaderboardEntry.played] == false
/// renders ONLY their name and "Not played yet" — never any outcome/score
/// field, and never the word or guesses (which this screen never even
/// fetches — see [SocialClient.fetchResults]).
class GroupLeaderboardScreen extends StatefulWidget {
  const GroupLeaderboardScreen({
    super.key,
    required this.group,
    required this.date,
    required this.lang,
    this.socialService,
  });

  final SocialGroup group;
  final String date;
  final String lang;
  final SocialService? socialService;

  @override
  State<GroupLeaderboardScreen> createState() => _GroupLeaderboardScreenState();
}

class _GroupLeaderboardScreenState extends State<GroupLeaderboardScreen> {
  late final SocialService _service = widget.socialService ?? buildSocialService();
  late String _lang = widget.lang;
  List<LeaderboardEntry>? _entries;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _entries = null;
      _error = null;
    });
    try {
      final all = await _service.leaderboardFor(
        groupId: widget.group.id,
        date: widget.date,
      );
      final filtered = all.where((e) => e.lang == null || e.lang == _lang).toList();
      if (mounted) setState(() => _entries = filtered);
    } catch (e) {
      if (mounted) setState(() => _error = 'Could not load the leaderboard.');
    }
  }

  Future<void> _shareInvite() async {
    final text = 'Play Warmer with me — join "${widget.group.name}"!\n'
        '${widget.group.joinLink}\n'
        'Code: ${widget.group.code}';
    if (webShareAvailable()) {
      final shared = await shareViaWebApi(
        title: 'Warmer',
        text: text,
        url: widget.group.joinLink,
      );
      if (shared) return;
    }
    await Clipboard.setData(ClipboardData(text: text));
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Invite copied to clipboard!')),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.group.name),
        actions: [
          IconButton(
            icon: const Icon(Icons.share),
            tooltip: 'Invite friends',
            onPressed: _shareInvite,
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _load,
        child: _buildBody(context),
      ),
    );
  }

  Widget _buildBody(BuildContext context) {
    if (_error != null) {
      return ListView(
        children: [
          const SizedBox(height: 80),
          Center(child: Text(_error!)),
          Center(
            child: TextButton(onPressed: _load, child: const Text('Retry')),
          ),
        ],
      );
    }
    if (_entries == null) {
      return const Center(child: CircularProgressIndicator());
    }

    final entries = _entries!;
    final dateLabel = DateFormat('EEE, MMM d').format(DateTime.parse(widget.date));

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        if (AppConfig.supportedLangs.length > 1)
          Center(
            child: SegmentedButton<String>(
              segments: [
                for (final l in AppConfig.supportedLangs)
                  ButtonSegment(value: l, label: Text(AppConfig.langLabels[l] ?? l)),
              ],
              selected: {_lang},
              onSelectionChanged: (s) {
                setState(() => _lang = s.first);
                _load();
              },
            ),
          ),
        const SizedBox(height: 12),
        Text(
          'Today · $dateLabel',
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.titleMedium,
        ),
        const SizedBox(height: 20),
        if (entries.isEmpty)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 40),
            child: Center(child: Text('No members yet.')),
          )
        else
          ...entries.asMap().entries.map(
                (e) => _LeaderboardRow(
                  rank: e.key + 1,
                  entry: e.value,
                  isSelf: e.value.uid == _service.selfUidOrNull,
                ),
              ),
        const SizedBox(height: 24),
        Center(
          child: OutlinedButton.icon(
            onPressed: _shareInvite,
            icon: const Icon(Icons.person_add_alt),
            label: const Text('Invite friends'),
          ),
        ),
      ],
    );
  }
}

class _LeaderboardRow extends StatelessWidget {
  const _LeaderboardRow({
    required this.rank,
    required this.entry,
    required this.isSelf,
  });

  final int rank;
  final LeaderboardEntry entry;
  final bool isSelf;

  String get _resultLabel {
    if (!entry.played) return 'Not played yet';
    if (entry.outcome == 'win') {
      final delta = entry.scoreVsPar;
      final parStr = delta == null || delta == 0
          ? 'par'
          : (delta > 0 ? '+$delta vs par' : '$delta vs par');
      return 'Won in ${entry.guessesUsed} ($parStr)';
    }
    return "Didn't get it";
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final tokens = theme.extension<WarmerTokens>() ?? WarmerTokens.light;
    final notPlayed = !entry.played;
    return Card(
      color: isSelf ? theme.colorScheme.primaryContainer : null,
      margin: const EdgeInsets.symmetric(vertical: 4),
      child: ListTile(
        leading: CircleAvatar(
          backgroundColor: theme.colorScheme.surfaceContainerHighest,
          child: Text(
            '$rank',
            style: TextStyle(color: tokens.text2, fontSize: 12, fontWeight: FontWeight.w600),
          ),
        ),
        title: Text(
          entry.displayName + (isSelf ? ' (you)' : ''),
          style: TextStyle(fontWeight: isSelf ? FontWeight.bold : FontWeight.normal),
        ),
        trailing: Text(
          _resultLabel,
          style: TextStyle(
            fontStyle: notPlayed ? FontStyle.italic : FontStyle.normal,
            color: notPlayed ? tokens.text3 : null,
          ),
        ),
      ),
    );
  }
}
