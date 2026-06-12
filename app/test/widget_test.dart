/// Smoke test: pumps [PuzzleScreen] with an injected pre-loaded payload client
/// and verifies the guess input field is present and functional.
///
/// Uses [sqflite_common_ffi] + [tester.runAsync] to handle the SQLite async
/// operations that don't respond to plain [WidgetTester.pump] calls.
library;

import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mindmeld/core/models.dart';
import 'package:mindmeld/core/payload_client.dart';
import 'package:mindmeld/core/payload_codec.dart';
import 'package:mindmeld/core/persistence.dart';
import 'package:mindmeld/features/puzzle/puzzle_screen.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

/// [PayloadClient] that returns a pre-loaded [DailyPayload] without any I/O.
///
/// Used in widget tests to make [PuzzleScreen._load()] resolve in a single
/// microtask, avoiding real file I/O during [WidgetTester.pump].
class _PreloadedClient extends PayloadClient {
  _PreloadedClient(this._preloaded);

  final DailyPayload _preloaded;

  @override
  Future<PayloadResult> fetch(String lang, String date) => Future.value(
        PayloadResult(
          payload: _preloaded,
          source: PayloadSource.bundledAsset,
        ),
      );
}

/// Load a bundled payload synchronously from disk before the test starts.
DailyPayload _loadPayload(String lang, String date) {
  final bytes = File('assets/payloads/$lang/$date.json.gz').readAsBytesSync();
  return PayloadCodec.decode(Uint8List.fromList(bytes));
}

void main() {
  late Directory tmpDir;

  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  setUp(() async {
    AppPersistence.resetForTest();
    tmpDir = await Directory.systemTemp.createTemp('mindmeld_smoke_');
    final dbPath = p.join(tmpDir.path, 'smoke.db');
    await AppPersistence.instance.init(dbPath: dbPath);
  });

  tearDown(() async {
    await AppPersistence.instance.close();
    AppPersistence.resetForTest();
    await tmpDir.delete(recursive: true);
  });

  testWidgets('PuzzleScreen smoke — guess input is visible after load',
      (tester) async {
    final payload = _loadPayload('en', '2026-06-12');
    final client = _PreloadedClient(payload);

    await tester.pumpWidget(
      MaterialApp(
        home: PuzzleScreen(
          lang: 'en',
          date: '2026-06-12',
          onWin: () {},
          payloadClient: client,
        ),
      ),
    );

    // runAsync lets real async operations (sqflite FFI) complete on OS threads.
    await tester.runAsync(() async {
      await Future<void>.delayed(const Duration(milliseconds: 200));
    });
    // Then pump to process the setState calls that resulted from the async work.
    await tester.pump();

    // The guess input TextField must be visible.
    expect(find.byType(TextField), findsOneWidget);

    // The "Enter a word…" hint text is present.
    expect(find.text('Enter a word…'), findsOneWidget);

    // The "Guess" submit button is present.
    expect(find.text('Guess'), findsOneWidget);

    // A non-vocab word must produce the "Not in word list" error.
    await tester.enterText(find.byType(TextField), 'zzzqqq');
    await tester.tap(find.text('Guess'));
    await tester.pump();
    expect(find.text('Not in word list'), findsOneWidget);
  });

  testWidgets('PuzzleScreen smoke — hi-en variant loads without error',
      (tester) async {
    final payload = _loadPayload('hi-en', '2026-06-12');
    final client = _PreloadedClient(payload);

    await tester.pumpWidget(
      MaterialApp(
        home: PuzzleScreen(
          lang: 'hi-en',
          date: '2026-06-12',
          onWin: () {},
          payloadClient: client,
        ),
      ),
    );

    await tester.runAsync(() async {
      await Future<void>.delayed(const Duration(milliseconds: 200));
    });
    await tester.pump();

    expect(find.byType(TextField), findsOneWidget);
    expect(find.text('Guess'), findsOneWidget);
  });
}
