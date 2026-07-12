import 'package:flutter/material.dart';

import 'package:mindmeld/core/design_tokens.dart';
import 'package:mindmeld/features/social/display_name_dialog.dart';
import 'package:mindmeld/social/social_models.dart';
import 'package:mindmeld/social/social_service.dart';

/// Deep-link join confirmation screen for `/join/{code}`.
///
/// Shown after onboarding has already been handled by the app shell (so a
/// first-time user sees onboard -> [JoinFlowScreen]; a returning user goes
/// straight here). Previews the group name (silent anon sign-in happens
/// here — this IS the "first social action"), captures a display name if
/// none is cached yet, then joins on confirm.
class JoinFlowScreen extends StatefulWidget {
  const JoinFlowScreen({
    super.key,
    required this.code,
    required this.date,
    required this.lang,
    required this.onDone,
    this.socialService,
  });

  final String code;
  final String date;
  final String lang;
  final VoidCallback onDone;
  final SocialService? socialService;

  @override
  State<JoinFlowScreen> createState() => _JoinFlowScreenState();
}

enum _JoinFlowState { loading, notFound, offline, confirm, joining }

class _JoinFlowScreenState extends State<JoinFlowScreen> {
  late final SocialService _service = widget.socialService ?? buildSocialService();
  _JoinFlowState _state = _JoinFlowState.loading;
  SocialGroup? _preview;

  /// Whichever step (preview or confirm) most recently failed with a
  /// retryable (offline/timeout) error — the "Retry" button re-runs it.
  /// Tracking this (rather than always retrying confirm) avoids retrying
  /// the wrong step when the failure happened during the initial preview.
  VoidCallback _retryAction = () {};

  @override
  void initState() {
    super.initState();
    _loadPreview();
  }

  Future<void> _loadPreview() async {
    setState(() => _state = _JoinFlowState.loading);
    _retryAction = _loadPreview;
    try {
      final result = await _service.previewGroupForCode(widget.code);
      if (!mounted) return;
      setState(() {
        switch (result.status) {
          case JoinCodeStatus.success:
            _preview = result.group;
            _state = _JoinFlowState.confirm;
          case JoinCodeStatus.codeNotFound:
            _state = _JoinFlowState.notFound;
          case JoinCodeStatus.offline:
            _state = _JoinFlowState.offline;
          case JoinCodeStatus.rejectedName:
            // previewGroupForCode never sets a display name, so this status
            // never actually occurs here — included only for switch
            // exhaustiveness over the shared JoinCodeStatus enum.
            _state = _JoinFlowState.offline;
        }
      });
    } catch (e) {
      // SocialService.previewGroupForCode never throws by contract, but this
      // guarantees the screen never sits on a spinner forever, regardless of cause.
      debugPrint('JoinFlowScreen._loadPreview unexpected error: $e');
      if (mounted) setState(() => _state = _JoinFlowState.offline);
    }
  }

  Future<void> _confirmJoin() async {
    final cachedName = await _service.cachedDisplayName();
    final displayName = cachedName ??
        (mounted ? await promptValidatedName(context, maxLength: kDisplayNameMaxLength) : null);
    if (displayName == null) return;
    if (!mounted) return;

    setState(() => _state = _JoinFlowState.joining);
    _retryAction = _confirmJoin;
    try {
      final result = await _service.joinByCode(code: widget.code, displayName: displayName);
      if (!mounted) return;

      if (result.status == JoinCodeStatus.rejectedName) {
        // Defense-in-depth fallback: promptValidatedName already screens
        // the name client-side, so this should be unreachable in practice.
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text(kNameRejectedMessage)),
        );
        setState(() => _state = _JoinFlowState.confirm);
        return;
      }

      if (result.status == JoinCodeStatus.success && result.group != null) {
        // Return to the main app shell rather than pushReplacement-ing to
        // GroupLeaderboardScreen directly: JoinFlowScreen is shown in place
        // of the main Scaffold (see main.dart's `_pendingJoinCode` gate), not
        // pushed on top of it, so replacing it leaves GroupLeaderboardScreen
        // as the ONLY route on the stack — no back button, no bottom nav, a
        // dead end for a first-time deep-link joiner (found live 2026-07-07:
        // a fresh user joining via /join/{code} had no way back to the
        // puzzle). widget.onDone() clears the pending code and rebuilds the
        // normal home shell, from which the new group's leaderboard is one
        // tap away on the Friends tab — fully functional, per the earlier
        // verified in-app navigation path.
        widget.onDone();
      } else {
        setState(() => _state = _JoinFlowState.offline);
      }
    } catch (e) {
      debugPrint('JoinFlowScreen._confirmJoin unexpected error: $e');
      if (mounted) setState(() => _state = _JoinFlowState.offline);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Join group'),
        leading: IconButton(icon: const Icon(Icons.close), onPressed: widget.onDone),
      ),
      body: Center(child: _buildBody(context)),
    );
  }

  Widget _buildBody(BuildContext context) {
    final tokens = Theme.of(context).extension<WarmerTokens>() ?? WarmerTokens.light;
    switch (_state) {
      case _JoinFlowState.loading:
        return const CircularProgressIndicator();
      case _JoinFlowState.notFound:
        return Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.link_off, size: 64, color: tokens.text3),
              const SizedBox(height: 16),
              const Text('This invite link is invalid or has expired.'),
              const SizedBox(height: 16),
              FilledButton(onPressed: widget.onDone, child: const Text('Back to Warmer')),
            ],
          ),
        );
      case _JoinFlowState.offline:
        return Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.wifi_off, size: 64, color: tokens.text3),
              const SizedBox(height: 16),
              const Text("Couldn't join — check your connection and try again."),
              const SizedBox(height: 16),
              FilledButton(onPressed: _retryAction, child: const Text('Retry')),
              TextButton(onPressed: widget.onDone, child: const Text('Cancel')),
            ],
          ),
        );
      case _JoinFlowState.joining:
        return const CircularProgressIndicator();
      case _JoinFlowState.confirm:
        final group = _preview!;
        return Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.groups, size: 64, color: Theme.of(context).colorScheme.primary),
              const SizedBox(height: 16),
              Text(
                'Join "${group.name}"?',
                style: Theme.of(context).textTheme.titleLarge,
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 8),
              Text('${group.memberUids.length} member${group.memberUids.length == 1 ? '' : 's'}'),
              const SizedBox(height: 24),
              FilledButton(onPressed: _confirmJoin, child: const Text('Join group')),
              const SizedBox(height: 8),
              TextButton(onPressed: widget.onDone, child: const Text('Not now')),
            ],
          ),
        );
    }
  }
}
