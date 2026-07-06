/// Runtime configuration for the agent app.
///
/// The API base URL is injected at build time with
/// `--dart-define=API_BASE_URL=...`. The default targets the host machine from
/// the Android emulator (`10.0.2.2` maps to the host's `localhost`).
class AppConfig {
  const AppConfig._();

  static const String apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://10.0.2.2:8080',
  );

  /// Terms-of-service version presented at the consent step. Must match the
  /// backend `CONSENT_TERMS_VERSION` (defaults to `v1`) — the consent endpoint
  /// rejects a mismatched version (backend `routes/consent.rs`).
  static const String consentTermsVersion = String.fromEnvironment(
    'CONSENT_TERMS_VERSION',
    defaultValue: 'v1',
  );

  /// Product codes an agent can start an onboarding under. The backend does not
  /// expose a product list to agents (`/products` is admin-only), so the MVP
  /// ships a fixed set that mirrors the seeded demo tenant. `product_code` is a
  /// free-text column server-side, so this list is safe to extend.
  static const List<ProductOption> products = [
    ProductOption(code: 'SAV', name: 'Chama Savings Account'),
    ProductOption(code: 'LOAN', name: 'Biashara Business Loan'),
    ProductOption(code: 'INS', name: 'Afya Health Cover'),
  ];
}

/// A selectable onboarding product.
class ProductOption {
  const ProductOption({required this.code, required this.name});

  final String code;
  final String name;
}
