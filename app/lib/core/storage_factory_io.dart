/// Native (dart:io) database factory — used on Android, iOS, Windows, macOS, Linux.
///
/// Imported via conditional import in [persistence.dart]:
///   import 'storage_factory_stub.dart'
///     if (dart.library.io) 'storage_factory_io.dart'
///     if (dart.library.html) 'storage_factory_web.dart';
///
/// On native platforms sqflite's default factory is used, which opens real
/// SQLite files via platform channels.
library;

import 'package:sqflite_common/sqlite_api.dart' show DatabaseFactory;
import 'package:sqflite/sqflite.dart' show databaseFactory;

/// Returns the platform-appropriate database factory for native builds.
///
/// On native platforms this is sqflite's default (platform-channel-backed) factory.
DatabaseFactory getPlatformDatabaseFactory() => databaseFactory;
