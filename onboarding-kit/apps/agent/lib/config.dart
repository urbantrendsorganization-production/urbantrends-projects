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

  /// Fallback product list, used only when `GET /products` is unavailable
  /// (offline, or before the first fetch resolves). The live list comes from
  /// the backend (`productsProvider` → `/products`, admin-managed), so products
  /// an admin adds show up in the app. This mirrors the seeded demo tenant.
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
