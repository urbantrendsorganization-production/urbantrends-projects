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
}
