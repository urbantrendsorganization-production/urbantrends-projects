//! `onboardkit-db` — database access layer.
//!
//! Owns the connection pool and (from Phase 1) the tenant-scoped repositories.
//! Every query in this crate MUST filter by `tenant_id` (CLAUDE.md §4). Schema
//! lives in `backend/migrations/`, which is the source of truth.

#![warn(clippy::pedantic)]
#![allow(clippy::module_name_repetitions, clippy::doc_markdown)]

pub mod applications;
pub mod clients;
pub mod documents;
pub mod events;
pub mod jobs;
pub mod models;
pub mod otp;
pub mod refresh_tokens;
pub mod tenants;
pub mod users;

pub use models::{
    Application, ApplicationEvent, Client, KycDocument, OtpRow, RefreshToken, Tenant, User,
};

use std::time::Duration;

use sqlx::postgres::{PgPool, PgPoolOptions};

/// Migrations embedded from `backend/migrations/`, the schema source of truth
/// (§5). Run at api/worker startup so a fresh database self-provisions.
pub static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("../../migrations");

/// Apply any pending migrations. Idempotent.
///
/// # Errors
/// Returns [`sqlx::migrate::MigrateError`] if a migration fails to apply.
pub async fn run_migrations(pool: &PgPool) -> Result<(), sqlx::migrate::MigrateError> {
    MIGRATOR.run(pool).await
}

/// Options for building the connection pool.
#[derive(Debug, Clone)]
pub struct PoolConfig {
    pub max_connections: u32,
    pub acquire_timeout: Duration,
}

impl Default for PoolConfig {
    fn default() -> Self {
        Self {
            max_connections: 10,
            acquire_timeout: Duration::from_secs(5),
        }
    }
}

/// Build and return a Postgres connection pool.
///
/// A connection is acquired eagerly so that a misconfigured `DATABASE_URL` or an
/// unreachable database fails fast at startup rather than on first request.
///
/// # Errors
/// Returns [`sqlx::Error`] if the pool cannot be created or the initial
/// connection/health check fails.
pub async fn connect(database_url: &str, config: &PoolConfig) -> Result<PgPool, sqlx::Error> {
    let pool = PgPoolOptions::new()
        .max_connections(config.max_connections)
        .acquire_timeout(config.acquire_timeout)
        .connect(database_url)
        .await?;

    // Fail fast on startup if the database is unreachable.
    sqlx::query_scalar::<_, i32>("SELECT 1")
        .fetch_one(&pool)
        .await?;

    tracing::info!(
        max_connections = config.max_connections,
        "database pool ready"
    );
    Ok(pool)
}
