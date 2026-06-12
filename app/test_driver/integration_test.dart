/// Standard flutter_driver integration-test runner.
///
/// Launch with:
///   flutter drive \
///     --driver=test_driver/integration_test.dart \
///     --target=integration_test/screenshots_test.dart \
///     -d emulator-5554
///
/// The [onScreenshot] callback is invoked by the integration_test binding
/// when the test calls [binding.takeScreenshot].  On Android the bytes are
/// raw Flutter-surface RGBA; we write them directly to a file so the host
/// can post-process or simply rename them.
library;

import 'dart:io';

import 'package:integration_test/integration_test_driver_extended.dart';

Future<void> main() async {
  await integrationDriver(
    onScreenshot: (String name, List<int> screenshotBytes, [Map<String, Object?>? args]) async {
      // `flutter drive` runs with CWD = app/ so `../docs/store-assets` is the
      // repo-root output directory.  We also create `docs/store-assets` (under
      // app/) as a fallback so the driver never errors even if the relative path
      // is different (e.g. CI workspaces).
      final outDir = Directory('../docs/store-assets');
      if (!outDir.existsSync()) {
        outDir.createSync(recursive: true);
      }
      final file = File('${outDir.path}/$name.png');
      await file.writeAsBytes(screenshotBytes);
      return true;
    },
  );
}
