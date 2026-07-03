# Multi-stage build (CLAUDE.md §14): cargo-chef dependency cache → debian-slim
# runtime. One image serves both the `api` and `worker` (jobs) binaries.

FROM lukemathwalker/cargo-chef:latest-rust-1 AS chef
WORKDIR /app

# ── Plan: compute the dependency recipe ──────────────────────────────────────
FROM chef AS planner
COPY . .
RUN cargo chef prepare --recipe-path recipe.json

# ── Build: cook dependencies (cached), then build the workspace binaries ──────
FROM chef AS builder
COPY --from=planner /app/recipe.json recipe.json
RUN cargo chef cook --release --recipe-path recipe.json
COPY . .
# No live database at build time; rely on the committed SQLx offline cache.
ENV SQLX_OFFLINE=true
RUN cargo build --release --bin api --bin worker

# ── Runtime: minimal image with both binaries ────────────────────────────────
FROM debian:bookworm-slim AS runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app

COPY --from=builder /app/target/release/api /usr/local/bin/api
COPY --from=builder /app/target/release/worker /usr/local/bin/worker
COPY --from=builder /app/migrations /app/migrations

# Run as an unprivileged user.
RUN useradd --system --create-home --uid 10001 onboardkit
USER onboardkit

EXPOSE 8080
CMD ["api"]
