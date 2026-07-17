/// Static guard against the wasm-stub class of bug (known-limitations 19).
///
/// Production ships `flutter build web --wasm`, where `dart.library.html` is
/// FALSE and `dart:html` does not exist. Any conditional import or
/// fromEnvironment check keyed on them selects the no-op stub / io branch in
/// production while passing every DDC-compiled test — which is exactly how
/// ?reset=1, /join links, the share sheet, AND the SQLite storage backend
/// were all silently dead/stubbed on live between 2026-07-12 and 2026-07-17.
///
/// This test fails the build the moment anyone reintroduces the pattern.
/// Web-only code must use package:web / dart:js_interop behind
/// `if (dart.library.js_interop)`.
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:path/path.dart' as p;

/// Real-usage patterns. Comments are excluded line-wise below, so docs may
/// still *mention* dart.library.html when explaining this very incident.
final _banned = <RegExp, String>{
  RegExp(r'''if\s*\(\s*dart\.library\.html\s*\)'''):
      "conditional import keyed on dart.library.html — false under --wasm; use if (dart.library.js_interop)",
  RegExp(r'''fromEnvironment\(\s*['"]dart\.library\.html['"]'''):
      "fromEnvironment('dart.library.html') — false under --wasm; use 'dart.library.js_interop' or kIsWeb",
  RegExp(r'''import\s+['"]dart:html['"]'''):
      "dart:html import — does not compile under --wasm; use package:web",
  RegExp(r'''import\s+['"]dart:js['"]'''):
      "dart:js import — unavailable under --wasm; use dart:js_interop",
};

void main() {
  test('lib/ contains no dart.library.html conditionals or dart:html imports',
      () {
    // Resolve lib/ relative to this test file so the test works from any cwd.
    final libDir = Directory(p.join(Directory.current.path, 'lib'));
    expect(libDir.existsSync(), isTrue,
        reason: 'expected to run from the app/ package root');

    final violations = <String>[];
    for (final entity in libDir.listSync(recursive: true)) {
      if (entity is! File || !entity.path.endsWith('.dart')) continue;
      final lines = entity.readAsLinesSync();
      for (var i = 0; i < lines.length; i++) {
        final trimmed = lines[i].trimLeft();
        // Skip comment lines: incident writeups legitimately reference the
        // banned tokens when explaining WHY they are banned.
        if (trimmed.startsWith('//')) continue;
        for (final entry in _banned.entries) {
          if (entry.key.hasMatch(lines[i])) {
            final rel = p.relative(entity.path, from: libDir.parent.path);
            violations.add('$rel:${i + 1}: ${entry.value}\n    ${lines[i].trim()}');
          }
        }
      }
    }

    expect(violations, isEmpty,
        reason: 'wasm-stub guard: banned dart:html-era pattern(s) found — '
            'these silently break production --wasm builds while all '
            'DDC-compiled tests pass (see docs/known-limitations.md entry 19):\n'
            '${violations.join('\n')}');
  });
}
