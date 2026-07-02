# OnboardKit backend

Rust workspace (Axum + SQLx + Tokio + Postgres). See `../CLAUDE.md` for the
authoritative spec. Crate graph: `api → {core, db, jobs, integrations}`,
`db → core`, `jobs → {core, db, integrations}`, `integrations → core`. `core`
depends on nothing internal and must never import `axum` or `sqlx`.

## Prerequisites

- Rust (edition 2024 toolchain)
- `sqlx-cli`: `cargo install sqlx-cli --no-default-features --features rustls,postgres`
- A running Postgres (use the dev stack: `docker compose -f ../ops/docker-compose.yml up postgres`)

## Run

```bash
# API
cargo run -p onboardkit-api --bin api

# Background worker
cargo run -p onboardkit-jobs --bin worker
```

Health check: `curl http://localhost:8080/api/v1/health`.

## Checks (must pass before any merge — CLAUDE.md §3, §16)

```bash
cargo fmt --all -- --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test --all
```

## Migrations & SQLx offline cache

Schema lives in `migrations/` and is the source of truth (CLAUDE.md §5). It is
seeded starting in Phase 1; Phase 0 ships the tooling only.

```bash
export DATABASE_URL=postgres://onboardkit:onboardkit@localhost:5432/onboardkit

# Create / run / add migrations
sqlx database create
sqlx migrate run
sqlx migrate add <name>
```

Compile-time-checked `sqlx::query!` / `query_as!` macros require an offline
query cache so CI can build without a database. Regenerate it whenever queries
change and commit the `.sqlx/` directory:

```bash
cargo sqlx prepare --workspace
git add .sqlx
```

CI verifies the cache is current with `cargo sqlx prepare --workspace --check`
and builds with `SQLX_OFFLINE=true`. Phase 0 contains no `query!` macros yet, so
the build already succeeds fully offline.
