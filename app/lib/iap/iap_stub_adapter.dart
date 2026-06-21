/// [IapGateway] adapter that delegates to [IapStub].
///
/// Used when [AppConfig.iapEnabled] is false or the RevenueCat API key is
/// empty.  All behaviour is identical to the existing stub: purchase() always
/// returns [PurchaseOutcome.comingSoon], restore() is a no-op, current()
/// returns [Entitlements.empty].
library;

import 'package:mindmeld/iap/entitlements.dart';
import 'package:mindmeld/stubs/iap_stub.dart';

/// [IapGateway] backed by [IapStub].
///
/// This adapter preserves all existing IapStub behaviour so screens that
/// previously used [IapStub] directly continue to work unchanged.
class IapStubAdapter implements IapGateway {
  IapStubAdapter() : _stub = const IapStub();

  final IapStub _stub;

  @override
  Future<PurchaseOutcome> purchase(Product product) async {
    final result = await _stub.purchase(product);
    // IapStub always returns success:false with a "coming soon" message.
    if (!result.success) return PurchaseOutcome.comingSoon;
    return PurchaseOutcome.success;
  }

  @override
  Future<void> restore() async {
    await _stub.restorePurchases();
  }

  @override
  Future<void> consumeStreakFreeze() async {}

  @override
  Future<Entitlements> current() async => Entitlements.empty;
}
