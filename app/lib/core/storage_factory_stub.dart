/// Stub database factory — fallback when neither dart:io nor dart:html is available.
///
/// This file is the "default" import target in the conditional import chain:
///   import 'storage_factory_stub.dart'
///     if (dart.library.io) 'storage_factory_io.dart'
///     if (dart.library.html) 'storage_factory_web.dart';
///
/// In practice this stub should never be reached on supported platforms (native
/// always has dart:io, web always has dart:html). It exists so that the import
/// chain compiles cleanly on all tooling configurations.
library;

import 'package:sqflite_common/sqlite_api.dart';

/// Throws [UnsupportedError] — this stub should never be reached at runtime.
DatabaseFactory getPlatformDatabaseFactory() {
  throw UnsupportedError(
    'No database factory available for this platform. '
    'Use storage_factory_io.dart (native) or storage_factory_web.dart (web).',
  );
}
