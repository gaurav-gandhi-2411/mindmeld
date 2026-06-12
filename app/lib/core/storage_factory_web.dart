/// Web database factory — used when compiling for the web platform.
///
/// Imported via conditional import in [persistence.dart]:
///   import 'storage_factory_stub.dart'
///     if (dart.library.io) 'storage_factory_io.dart'
///     if (dart.library.html) 'storage_factory_web.dart';
///
/// On web, sqflite_common_ffi_web provides a WASM SQLite backend persisted via
/// IndexedDB, exposing the same [DatabaseFactory] API as native sqflite.
library;

import 'package:sqflite_common/sqlite_api.dart' show DatabaseFactory;
import 'package:sqflite_common_ffi_web/sqflite_ffi_web.dart' show databaseFactoryFfiWeb;

/// Returns the WASM/IndexedDB-backed database factory for web builds.
DatabaseFactory getPlatformDatabaseFactory() => databaseFactoryFfiWeb;
