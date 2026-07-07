/// Unit tests for [rankLeaderboard] / [LeaderboardEntry.compare].
///
/// Pure-function tests — no Firebase, no Flutter widgets.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/social/social_models.dart';

LeaderboardEntry _win(String uid, int guesses, {int? scoreVsPar}) => LeaderboardEntry(
      uid: uid,
      displayName: uid,
      played: true,
      outcome: 'win',
      guessesUsed: guesses,
      par: 6,
      scoreVsPar: scoreVsPar ?? (guesses - 6),
      lang: 'en',
    );

LeaderboardEntry _loss(String uid) => LeaderboardEntry(
      uid: uid,
      displayName: uid,
      played: true,
      outcome: 'loss',
      guessesUsed: 15,
      par: 6,
      scoreVsPar: 9,
      lang: 'en',
    );

LeaderboardEntry _notPlayed(String uid) => LeaderboardEntry(
      uid: uid,
      displayName: uid,
      played: false,
    );

void main() {
  group('rankLeaderboard', () {
    test('wins rank ahead of losses, which rank ahead of not-played', () {
      final entries = [_notPlayed('c'), _loss('b'), _win('a', 5)];
      final ranked = rankLeaderboard(entries);
      expect(ranked.map((e) => e.uid).toList(), ['a', 'b', 'c']);
    });

    test('among wins, fewest guesses ranks first', () {
      final entries = [_win('slow', 9), _win('fast', 3), _win('mid', 6)];
      final ranked = rankLeaderboard(entries);
      expect(ranked.map((e) => e.uid).toList(), ['fast', 'mid', 'slow']);
    });

    test('does not mutate the input list', () {
      final entries = [_win('b', 9), _win('a', 3)];
      final ranked = rankLeaderboard(entries);
      expect(entries.first.uid, 'b'); // original order untouched
      expect(ranked.first.uid, 'a');
    });

    test('a not-played entry carries no outcome/score fields (spoiler safety)', () {
      final entry = _notPlayed('unplayed');
      expect(entry.played, isFalse);
      expect(entry.outcome, isNull);
      expect(entry.guessesUsed, isNull);
      expect(entry.par, isNull);
      expect(entry.scoreVsPar, isNull);
      expect(entry.finishedAt, isNull);
    });

    test('multiple not-played members are ordered deterministically by name', () {
      final entries = [_notPlayed('zed'), _notPlayed('amy')];
      final ranked = rankLeaderboard(entries);
      expect(ranked.map((e) => e.uid).toList(), ['amy', 'zed']);
    });
  });

  group('SocialGroup', () {
    test('joinLink embeds the group code', () {
      const group = SocialGroup(
        id: 'g1',
        name: 'Friends',
        code: 'ABC123',
        createdBy: 'alice',
        memberUids: ['alice'],
      );
      expect(group.joinLink, 'https://playmindmeld.vercel.app/join/ABC123');
    });
  });
}
