//! `onboardkit-jobs` — Postgres-backed background worker.
//!
//! The worker polls the `jobs` table with `SELECT ... FOR UPDATE SKIP LOCKED`
//! and executes job types (`process_image`, `send_sms`, `nightly_export_digest`).
//! Job execution lands in Phase 2; Phase 0 provides the poll loop scaffold and
//! graceful shutdown so the compose `jobs` service has something to run.

#![warn(clippy::pedantic)]
#![allow(clippy::module_name_repetitions, clippy::doc_markdown)]

use std::time::Duration;

use sqlx::postgres::PgPool;
use tokio::signal;

/// Runtime configuration for the worker loop.
#[derive(Debug, Clone)]
pub struct WorkerConfig {
    /// How often to poll the `jobs` table for due work.
    pub poll_interval: Duration,
}

impl Default for WorkerConfig {
    fn default() -> Self {
        Self {
            poll_interval: Duration::from_secs(5),
        }
    }
}

/// Run the worker poll loop until a shutdown signal is received.
///
/// In Phase 0 each tick is a no-op placeholder; job dispatch is wired in Phase 2.
///
/// # Errors
/// Returns an error if awaiting the shutdown signal fails.
pub async fn run(_pool: PgPool, config: WorkerConfig) -> anyhow::Result<()> {
    tracing::info!(
        poll_interval_secs = config.poll_interval.as_secs(),
        "worker started"
    );

    let mut ticker = tokio::time::interval(config.poll_interval);
    ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);

    loop {
        tokio::select! {
            _ = ticker.tick() => {
                // Phase 2: SELECT ... FOR UPDATE SKIP LOCKED, dispatch job types.
                tracing::trace!("worker tick (no jobs configured yet)");
            }
            () = shutdown_signal() => {
                tracing::info!("worker shutdown signal received, stopping");
                break;
            }
        }
    }

    Ok(())
}

/// Resolve when the process receives Ctrl-C or (on Unix) `SIGTERM`.
async fn shutdown_signal() {
    let ctrl_c = async {
        if let Err(error) = signal::ctrl_c().await {
            tracing::error!(%error, "failed to install Ctrl-C handler");
        }
    };

    #[cfg(unix)]
    let terminate = async {
        match signal::unix::signal(signal::unix::SignalKind::terminate()) {
            Ok(mut stream) => {
                stream.recv().await;
            }
            Err(error) => tracing::error!(%error, "failed to install SIGTERM handler"),
        }
    };

    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        () = ctrl_c => {},
        () = terminate => {},
    }
}
