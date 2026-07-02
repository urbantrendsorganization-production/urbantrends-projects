# OnboardKit

Client onboarding & KYC portal for insurance agencies and MFIs in Kenya. Field
agents onboard clients on a Flutter app; reviewers approve/reject on a Next.js
office console; a Rust (Axum + SQLx + Postgres) backend runs the state machine.

See [`CLAUDE.md`](./CLAUDE.md) for the authoritative spec and [`PLAN.md`](./PLAN.md)
for the phased build plan.

## Layout

```
onboarding-kit/
├── backend/        # Rust workspace: api, core, db, jobs, integrations
├── apps/
│   ├── office/     # Next.js (App Router, TS, shadcn/ui) — reviewer/admin console
│   └── agent/      # Flutter (Riverpod, dio) — field-agent app
└── ops/            # docker-compose dev stack + .env.example
```

## Quick start (dev stack)

```bash
cp ops/.env.example ops/.env
docker compose -f ops/docker-compose.yml up --build
```

Then:

- API health: `curl http://localhost:8080/api/v1/health`
- Postgres: `localhost:5432` (override with `POSTGRES_PORT` if taken)
- MinIO console: `http://localhost:9001`

### Office (Next.js)

```bash
cd apps/office && npm install
API_URL=http://localhost:8080 npm run dev   # http://localhost:3000
```

### Agent (Flutter)

The Dart sources are committed; regenerate the platform folders on a machine
with Flutter installed (see [`apps/agent/README.md`](./apps/agent/README.md)):

```bash
cd apps/agent
flutter create --platforms=android,ios --org dev.urbantrends .
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8080
```

## Checks

```bash
# backend
cd backend && cargo fmt --all -- --check && cargo clippy --all-targets --all-features -- -D warnings && cargo test --all
# office
cd apps/office && npm run lint && npm run build
```

Built by [UrbanTrends](https://urbantrends.dev).
