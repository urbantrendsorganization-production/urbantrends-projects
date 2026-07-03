# OnboardKit Agent (Flutter)

Field-agent app for client onboarding & KYC capture. Android-first (a signed demo
APK is the Phase 6 deliverable). State via Riverpod, HTTP via dio, tokens in
`flutter_secure_storage` (CLAUDE.md §12).

## Phase 0

Ships the connectivity scaffold: a single screen that calls the backend
`GET /api/v1/health` endpoint and shows API + database status, with retry.

- `lib/config.dart` — API base URL (`--dart-define=API_BASE_URL=...`).
- `lib/api/health.dart` — dio client + `healthProvider`.
- `lib/main.dart` — `HealthScreen`.

## Generate platform folders

This scaffold contains the Dart sources and `pubspec.yaml` only. The Flutter CLI
was not available in the environment that created it, so the generated
`android/` and `ios/` folders are not committed. Recreate them (non-destructive
to `lib/`) on a machine with Flutter installed:

```bash
cd apps/agent
flutter create --platforms=android,ios --org dev.urbantrends .
flutter pub get
```

## Run against the dev stack

The Android emulator reaches the host machine at `10.0.2.2` (the default in
`config.dart`). With the backend stack up:

```bash
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8080
```

## Test

```bash
flutter test
```
