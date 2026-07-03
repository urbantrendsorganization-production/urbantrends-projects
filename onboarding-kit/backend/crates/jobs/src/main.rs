//! Worker binary entrypoint (`cargo run -p onboardkit-jobs --bin worker`).
//!
//! Runs the same Docker image as the API but as a separate compose service
//! (CLAUDE.md §10, §14).

#![warn(clippy::pedantic)]
#![allow(clippy::doc_markdown)]

use std::time::Duration;

use onboardkit_db::PoolConfig;
use onboardkit_jobs::WorkerConfig;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Load .env in development; missing file is not an error (prod uses real env).
    let _ = dotenvy::dotenv();

    init_tracing();

    let database_url = require_env("DATABASE_URL")?;
    let poll_interval = env_duration_secs("WORKER_POLL_INTERVAL_SECS", 5);

    let pool = onboardkit_db::connect(&database_url, &PoolConfig::default()).await?;

    onboardkit_jobs::run(pool, WorkerConfig { poll_interval }).await
}

/// Initialise `tracing`: JSON logs when `APP_ENV=production`, pretty otherwise.
fn init_tracing() {
    use tracing_subscriber::{EnvFilter, fmt, prelude::*};

    let filter =
        EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info,sqlx=warn"));

    let is_prod = std::env::var("APP_ENV").as_deref() == Ok("production");

    let registry = tracing_subscriber::registry().with(filter);
    if is_prod {
        registry.with(fmt::layer().json()).init();
    } else {
        registry.with(fmt::layer().pretty()).init();
    }
}

fn require_env(key: &str) -> anyhow::Result<String> {
    std::env::var(key)
        .map_err(|_| anyhow::anyhow!("required environment variable {key} is not set"))
}

fn env_duration_secs(key: &str, default_secs: u64) -> Duration {
    let secs = std::env::var(key)
        .ok()
        .and_then(|raw| raw.parse::<u64>().ok())
        .unwrap_or(default_secs);
    Duration::from_secs(secs)
}
