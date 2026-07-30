import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/core/models.dart';

void main() {
  group('bandForRank — n=55000 (English vocab size)', () {
    const n = 55000;
    // Thresholds:
    //   scorching ≤ max(50, floor(55000 * 0.001)) = max(50, 55) = 55
    //   hot       ≤ max(500, floor(55000 * 0.01))  = max(500, 550) = 550
    //   warm      ≤ max(1050, floor(55000 * 0.05)) = max(1050, 2750) = 2750
    //     (the 1050-rank warm floor added to fix hi-en's dead Warm band does
    //     not bind at this scale: 2750 >> 1050, so this boundary is unchanged)
    //   cold      ≤ floor(55000 * 0.25)             = 13750
    //   else      freezing

    test('rank 1 → win', () {
      expect(bandForRank(1, n), equals(TemperatureBand.win));
    });

    test('rank 2 → scorching (just above win)', () {
      expect(bandForRank(2, n), equals(TemperatureBand.scorching));
    });

    test('rank 55 → scorching (at threshold)', () {
      expect(bandForRank(55, n), equals(TemperatureBand.scorching));
    });

    test('rank 56 → hot (one above scorching threshold)', () {
      expect(bandForRank(56, n), equals(TemperatureBand.hot));
    });

    test('rank 550 → hot (at threshold)', () {
      expect(bandForRank(550, n), equals(TemperatureBand.hot));
    });

    test('rank 551 → warm (one above hot threshold)', () {
      expect(bandForRank(551, n), equals(TemperatureBand.warm));
    });

    test('rank 2750 → warm (at threshold)', () {
      expect(bandForRank(2750, n), equals(TemperatureBand.warm));
    });

    test('rank 2751 → cold (one above warm threshold)', () {
      expect(bandForRank(2751, n), equals(TemperatureBand.cold));
    });

    test('rank 13750 → cold (at threshold)', () {
      expect(bandForRank(13750, n), equals(TemperatureBand.cold));
    });

    test('rank 13751 → freezing (one above cold threshold)', () {
      expect(bandForRank(13751, n), equals(TemperatureBand.freezing));
    });

    test('rank 55000 → freezing (last vocab entry)', () {
      expect(bandForRank(55000, n), equals(TemperatureBand.freezing));
    });
  });

  group('bandForRank — n=10439 (Hinglish vocab size)', () {
    const n = 10439;
    // Thresholds (post warm-floor-widening, see docs/known-limitations.md #18):
    //   scorching ≤ max(50, floor(10439 * 0.001)) = max(50, 10) = 50
    //   hot       ≤ max(500, floor(10439 * 0.01))  = max(500, 104) = 500
    //   warm      ≤ max(1050, floor(10439 * 0.05)) = max(1050, 521) = 1050
    //     (pre-fix this was 521 -- a 21-rank Warm band; the original 900-rank
    //     floor widened it to 400 ranks, and a later grid-search-backed
    //     widening to 1050 grew it further to a 550-rank band, still
    //     matching EN's proportional feel)
    //   cold      ≤ floor(10439 * 0.25)             = 2609
    //   else      freezing

    test('rank 1 → win', () {
      expect(bandForRank(1, n), equals(TemperatureBand.win));
    });

    test('rank 50 → scorching (at floor threshold)', () {
      expect(bandForRank(50, n), equals(TemperatureBand.scorching));
    });

    test('rank 51 → hot (above scorching floor)', () {
      expect(bandForRank(51, n), equals(TemperatureBand.hot));
    });

    test('rank 500 → hot (at floor threshold)', () {
      expect(bandForRank(500, n), equals(TemperatureBand.hot));
    });

    test('rank 501 → warm (above hot threshold)', () {
      expect(bandForRank(501, n), equals(TemperatureBand.warm));
    });

    test('rank 1050 → warm (at current warm-floor threshold)', () {
      expect(bandForRank(1050, n), equals(TemperatureBand.warm));
    });

    test('rank 1051 → cold', () {
      expect(bandForRank(1051, n), equals(TemperatureBand.cold));
    });

    test('rank 2609 → cold (at cold threshold)', () {
      expect(bandForRank(2609, n), equals(TemperatureBand.cold));
    });

    test('rank 2610 → freezing', () {
      expect(bandForRank(2610, n), equals(TemperatureBand.freezing));
    });
  });

  group('band color mapping', () {
    test('each band maps to a distinct emoji', () {
      final emojis = TemperatureBand.values.map((b) => b.emoji).toList();
      // All distinct
      expect(emojis.toSet().length, equals(TemperatureBand.values.length));
    });

    test('win band has brain emoji', () {
      expect(TemperatureBand.win.emoji, equals('🧠'));
    });

    test('scorching band has red square', () {
      expect(TemperatureBand.scorching.emoji, equals('🟥'));
    });

    test('freezing band has blue square', () {
      expect(TemperatureBand.freezing.emoji, equals('🟦'));
    });
  });
}
