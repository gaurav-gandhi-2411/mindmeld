import 'dart:io';
import 'package:path/path.dart' as p;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:mindmeld/core/persistence.dart';

/// Initialise sqflite_common_ffi for desktop/Windows test environments.
///
/// Call once in setUpAll() for any test that uses [AppPersistence].
void initSqfliteFfi() {
  sqfliteFfiInit();
  databaseFactory = databaseFactoryFfi;
}

/// Create an [AppPersistence] instance backed by a temp-dir SQLite DB.
///
/// Returns the persistence instance and the temp dir for cleanup.
Future<(AppPersistence, Directory)> openTestDb() async {
  AppPersistence.resetForTest();
  final tmpDir = await Directory.systemTemp.createTemp('mindmeld_test_');
  final dbPath = p.join(tmpDir.path, 'test.db');
  final db = AppPersistence.instance;
  await db.init(dbPath: dbPath);
  return (db, tmpDir);
}

/// Close and clean up a test database.
Future<void> closeTestDb(AppPersistence db, Directory tmpDir) async {
  await db.close();
  AppPersistence.resetForTest();
  await tmpDir.delete(recursive: true);
}
