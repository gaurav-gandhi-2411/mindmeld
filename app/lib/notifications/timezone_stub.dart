/// Stub for non-web platforms: timezone capture is web-only this phase
/// (native push is out of scope — see spec-phase6b.md).
///
/// Imported via conditional import (see [currentTimezone] call sites in
/// notification_service.dart):
///   import 'timezone_stub.dart'
///     if (dart.library.html) 'timezone_web.dart';
library;

/// Always null on native this phase.
String? currentTimezone() => null;
