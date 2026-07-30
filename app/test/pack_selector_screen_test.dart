/// Widget tests for [PackSelectorScreen] (phase 6c) using an injected
/// [PackCatalog] pointed at the bundled manifest fixture (no real network).
library;

import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:mindmeld/core/packs.dart';
import 'package:mindmeld/core/persistence.dart';
import 'package:mindmeld/features/packs/pack_selector_screen.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

/// A minimal [AssetBundle] that loads files directly from the file system
/// (relative to app/) — mirrors payload_client_fallback_test.dart's helper.
///
/// Uses a SYNCHRONOUS read (unlike the plain-`test()` fallback helpers
/// elsewhere) because this bundle is exercised from a widget's `initState()`-
/// triggered future chain inside `testWidgets()`; a real `dart:io` async read
/// there never gets scheduled without `tester.runAsync()` wrapping the exact
/// call site, which isn't possible from inside the widget itself.
class _FileSystemAssetBundle extends AssetBundle {
  @override
  Future<ByteData> load(String key) async {
    final file = File(key);
    if (!file.existsSync()) {
      throw Exception('Asset not found: $key');
    }
    final bytes = file.readAsBytesSync();
    return ByteData.view(bytes.buffer);
  }

  @override
  Future<String> loadString(String key, {bool cache = true}) async {
    throw UnimplementedError();
  }

  @override
  Future<T> loadStructuredData<T>(
    String key,
    Future<T> Function(String value) parser,
  ) {
    throw UnimplementedError();
  }
}

void main() {
  late Directory tmpDir;

  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  setUp(() async {
    AppPersistence.resetForTest();
    tmpDir = await Directory.systemTemp.createTemp('mindmeld_pack_selector_');
    await AppPersistence.instance.init(dbPath: p.join(tmpDir.path, 'test.db'));
  });

  tearDown(() async {
    await AppPersistence.instance.close();
    AppPersistence.resetForTest();
    await tmpDir.delete(recursive: true);
  });

  Widget buildScreen() {
    // A MockClient that always throws forces the network-first fetch to fail
    // fast and fall through to the injected bundled-asset fixture — avoids
    // relying on flutter_test's implicit HttpClient interception for timing.
    final mockHttp = MockClient((_) async {
      throw const SocketException('Network unreachable');
    });
    final catalog = PackCatalog(
      baseUrl: 'https://unreachable.invalid',
      httpClient: mockHttp,
      assetBundle: _FileSystemAssetBundle(),
    );
    return MaterialApp(home: PackSelectorScreen(lang: 'en', catalog: catalog));
  }

  Future<void> settle(WidgetTester tester) async {
    await tester.runAsync(() async {
      await Future<void>.delayed(const Duration(milliseconds: 250));
    });
    await tester.pump();
  }

  testWidgets('renders all 3 pack tiles, all live, no coming-soon chips',
      (tester) async {
    await tester.pumpWidget(buildScreen());
    await settle(tester);

    expect(find.text('Bollywood'), findsOneWidget);
    expect(find.text('Cricket'), findsOneWidget);
    expect(find.text('Indian Kitchen'), findsOneWidget);

    // All 3 packs are live + unlocked → each shows won/count progress.
    // The Nature & Wild coming_soon stub was deleted at launch (spec-
    // warmer-closeout.md: "no coming soon tiles at launch") — there is no
    // longer a fixture pack to exercise the coming_soon-tap-does-nothing
    // path against; that behavior is otherwise untested pending a new
    // coming_soon pack being added as a future content drop.
    expect(find.text('0/25'), findsNWidgets(3));
    expect(find.widgetWithText(Chip, 'Coming soon'), findsNothing);
  });

  testWidgets('tapping the Indian Kitchen tile opens the puzzle list',
      (tester) async {
    await tester.pumpWidget(buildScreen());
    await settle(tester);

    await tester.tap(find.text('Indian Kitchen'));
    await tester.pump(); // begin the route push transition
    await settle(tester); // let PackPuzzleListScreen's sqflite read complete
    await tester.pump(const Duration(milliseconds: 400)); // finish transition

    expect(find.text('Puzzle #1'), findsOneWidget);
  });

  testWidgets('tapping the Bollywood tile opens the puzzle list', (tester) async {
    await tester.pumpWidget(buildScreen());
    await settle(tester);

    await tester.tap(find.text('Bollywood'));
    await tester.pump(); // begin the route push transition
    await settle(tester); // let PackPuzzleListScreen's sqflite read complete
    await tester.pump(const Duration(milliseconds: 400)); // finish transition

    expect(find.text('Puzzle #1'), findsOneWidget);
  });

  testWidgets('tapping the Cricket tile opens the puzzle list', (tester) async {
    await tester.pumpWidget(buildScreen());
    await settle(tester);

    await tester.tap(find.text('Cricket'));
    await tester.pump(); // begin the route push transition
    await settle(tester); // let PackPuzzleListScreen's sqflite read complete
    await tester.pump(const Duration(milliseconds: 400)); // finish transition

    expect(find.text('Puzzle #1'), findsOneWidget);
  });
}
