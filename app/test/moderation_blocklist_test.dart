/// Unit tests for [isBlockedName].
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/social/moderation_blocklist.dart';

void main() {
  group('legitimate names pass through', () {
    test('an ordinary name is not blocked', () {
      expect(isBlockedName('Gaurav'), isFalse);
    });

    test('a name that merely contains a reserved-word PREFIX is not blocked '
        '(false-positive guard)', () {
      // "moderate"/"modern" start with "mod" but are not impersonation.
      expect(isBlockedName('Moderate Team'), isFalse);
      expect(isBlockedName('ModernFan'), isFalse);
      expect(isBlockedName('Administrator99'), isFalse);
    });

    test('a legitimate non-Latin-script name is not blocked', () {
      expect(isBlockedName('गौरव'), isFalse);
    });
  });

  group('reserved-word (impersonation) blocking', () {
    test('exact reserved word is blocked', () {
      expect(isBlockedName('admin'), isTrue);
      expect(isBlockedName('Admin'), isTrue);
      expect(isBlockedName('official'), isTrue);
      expect(isBlockedName('moderator'), isTrue);
      expect(isBlockedName('mod'), isTrue);
      expect(isBlockedName('support'), isTrue);
      expect(isBlockedName('warmer'), isTrue);
      expect(isBlockedName('staff'), isTrue);
      expect(isBlockedName('system'), isTrue);
    });

    test('reserved word decorated with trailing digits is blocked ("admin123")', () {
      expect(isBlockedName('admin123'), isTrue);
    });

    test('reserved word as its own token is blocked ("the_admin", "Admin_2")', () {
      expect(isBlockedName('the_admin'), isTrue);
      expect(isBlockedName('Admin_2'), isTrue);
    });

    test('a Cyrillic-homoglyph impersonation attempt is caught ("аdmin" with Cyrillic а)', () {
      // The "a" below is Cyrillic CYRILLIC SMALL LETTER A (U+0430), not Latin
      // "a" (U+0061) — visually identical, would dodge a naive == 'admin'
      // string-match filter without the homoglyph fold.
      expect(isBlockedName('аdmin'), isTrue);
    });
  });

  group('profanity blocking', () {
    test('EN profanity is blocked (a few cases)', () {
      expect(isBlockedName('fuck'), isTrue);
      expect(isBlockedName('shit'), isTrue);
      expect(isBlockedName('bitch'), isTrue);
    });

    test('Hinglish profanity is blocked (a few cases)', () {
      expect(isBlockedName('chutiya'), isTrue);
      expect(isBlockedName('madarchod'), isTrue);
      expect(isBlockedName('gandu'), isTrue);
    });

    test('a decorated profanity word is still blocked ("chutiya1")', () {
      expect(isBlockedName('chutiya1'), isTrue);
    });

    test('a legitimate Hinglish word from the vocab list is not blocked', () {
      expect(isBlockedName('dost'), isFalse); // "friend" — generator/vocab/hinglish.txt
      expect(isBlockedName('pyaar'), isFalse); // "love"
    });
  });
}
