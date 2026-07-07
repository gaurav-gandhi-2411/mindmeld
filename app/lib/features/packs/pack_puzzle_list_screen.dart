import 'package:flutter/material.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/packs.dart';
import 'package:mindmeld/core/payload_client.dart';
import 'package:mindmeld/core/payload_codec.dart';
import 'package:mindmeld/core/persistence.dart';
import 'package:mindmeld/features/puzzle/puzzle_screen.dart';
import 'package:mindmeld/features/win/win_screen.dart';
import 'package:mindmeld/iap/entitlements.dart';

/// Pack date key used both for [PuzzleScreen.date] and for constructing the
/// contract's synthetic pack payload date ("{packId}-{NNN}").
String packDateKey(String packId, int idx) =>
    '$packId-${idx.toString().padLeft(3, '0')}';

/// Themed-pack puzzle list (phase 6c) — shows puzzles 1..count for one pack
/// with won/attempted/unplayed status, themed with the pack's accent color.
///
/// Tapping a puzzle pushes [PuzzleScreen] in pack mode wrapped in a [Theme]
/// seeded from the pack's accent so the whole puzzle screen carries the
/// pack's visual identity.
class PackPuzzleListScreen extends StatefulWidget {
  const PackPuzzleListScreen({
    super.key,
    required this.pack,
    required this.lang,
    this.iapGateway,
  });

  final Pack pack;
  final String lang;

  /// Optional [IapGateway] override (used in tests); currently unused
  /// directly by this screen but threaded through so a future re-lock check
  /// (e.g. subscription expiry) has a single injection point.
  final IapGateway? iapGateway;

  @override
  State<PackPuzzleListScreen> createState() => _PackPuzzleListScreenState();
}

class _PackPuzzleListScreenState extends State<PackPuzzleListScreen> {
  List<PackPuzzleState> _states = const [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final states = await AppPersistence.instance
        .loadPackStatesForPack(widget.pack.id, widget.lang);
    if (mounted) {
      setState(() {
        _states = states;
        _loading = false;
      });
    }
  }

  Map<int, PackPuzzleState> get _byIdx => {for (final s in _states) s.idx: s};

  Future<void> _play(int idx) async {
    await Navigator.push(
      context,
      MaterialPageRoute<void>(
        builder: (routeContext) => Theme(
          data: Theme.of(context).copyWith(
            colorScheme: ColorScheme.fromSeed(seedColor: widget.pack.accent),
          ),
          child: PuzzleScreen(
            lang: widget.lang,
            date: packDateKey(widget.pack.id, idx),
            packId: widget.pack.id,
            packIdx: idx,
            packTitle: widget.pack.titleFor(widget.lang),
            onWin: () => _finish(routeContext, idx, won: true),
            onLoss: () => _finish(routeContext, idx, won: false),
          ),
        ),
      ),
    );
    _load();
  }

  /// Fetches the payload again (for the secret + par/budget) and the just-
  /// saved [PackPuzzleState], then replaces the puzzle route with the
  /// appropriate result screen — mirrors main.dart's daily win/loss flow but
  /// scoped to this screen's own Navigator stack (see spec-phase6c.md).
  Future<void> _finish(BuildContext routeContext, int idx,
      {required bool won}) async {
    final client = PayloadClient();
    final result = await client.fetchPack(widget.pack.id, idx, widget.lang);
    final secret = PayloadCodec.decodeSecret(result.payload);
    final state = await AppPersistence.instance
        .loadPackState(widget.pack.id, idx, widget.lang);
    if (!routeContext.mounted) return;

    final date = packDateKey(widget.pack.id, idx);
    final packName = widget.pack.titleFor(widget.lang);

    Navigator.of(routeContext).pushReplacement(
      MaterialPageRoute<void>(
        builder: (screenCtx) => won
            ? WinScreen(
                secret: secret,
                guesses: state?.guesses ?? const [],
                lang: widget.lang,
                date: date,
                onPlayAgain: () => Navigator.of(screenCtx).pop(),
                parGuesses: result.payload.parGuesses,
                maxGuesses: result.payload.maxGuesses,
                hintsUsed: state?.hintsUsed ?? 0,
                packName: packName,
                packPuzzleNumber: idx,
              )
            : LossScreen(
                secret: secret,
                guesses: state?.guesses ?? const [],
                lang: widget.lang,
                date: date,
                onClose: () => Navigator.of(screenCtx).pop(),
                parGuesses: result.payload.parGuesses,
                maxGuesses: result.payload.maxGuesses,
                hintsUsed: state?.hintsUsed ?? 0,
                gaveUp: state?.gaveUp ?? false,
                packName: packName,
                packPuzzleNumber: idx,
              ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final pack = widget.pack;
    return Scaffold(
      appBar: AppBar(
        backgroundColor: pack.accent,
        foregroundColor: Colors.white,
        title: Text(pack.titleFor(widget.lang)),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : pack.count == 0
              ? const Center(child: Text('No puzzles in this pack yet.'))
              : ListView.builder(
                  itemCount: pack.count,
                  itemBuilder: (ctx, i) {
                    final idx = i + 1;
                    final state = _byIdx[idx];
                    final won = state?.won ?? false;
                    final lost = state != null && state.gaveUp && !won;
                    final inProgress =
                        state != null && !state.isFinished && !won && !lost;

                    return ListTile(
                      leading: CircleAvatar(
                        backgroundColor: won
                            ? Colors.green
                            : lost
                                ? Colors.grey
                                : pack.accent.withValues(alpha: 0.2),
                        child: Icon(
                          won
                              ? Icons.check
                              : lost
                                  ? Icons.close
                                  : Icons.play_arrow,
                          color: won || lost ? Colors.white : pack.accent,
                        ),
                      ),
                      title: Text('Puzzle #$idx'),
                      subtitle: Text(
                        won
                            ? 'Solved'
                            : lost
                                ? 'Attempted'
                                : inProgress
                                    ? 'In progress'
                                    : 'Not played',
                      ),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () => _play(idx),
                    );
                  },
                ),
    );
  }
}
