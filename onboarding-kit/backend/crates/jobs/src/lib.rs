//! `onboardkit-jobs` — Postgres-backed background worker (CLAUDE.md §10).
//!
//! The worker polls the `jobs` table with `SELECT ... FOR UPDATE SKIP LOCKED`,
//! dispatches by `job_type`, and records success/failure with exponential
//! backoff. Handlers must be idempotent — delivery is at-least-once.

#![warn(clippy::pedantic)]
#![allow(clippy::module_name_repetitions, clippy::doc_markdown)]

use std::sync::Arc;
use std::time::Duration;

use chrono::Utc;
use onboardkit_core::jobs::{ProcessImagePayload, SendSmsPayload, job_type};
use onboardkit_db::jobs::{self, Job};
use onboardkit_integrations::sms::{MockProvider, SmsProvider};
use onboardkit_integrations::{ObjectStore, Phone, image_ops, storage};
use sqlx::postgres::PgPool;
use tokio::signal;

/// Recompress uploads to at most this size (§10).
const MAX_IMAGE_BYTES: usize = 300 * 1024;
/// Thumbnail bounding edge in pixels.
const THUMB_EDGE: u32 = 256;
/// Backoff is capped so a stuck job still retries on a sane cadence.
const MAX_BACKOFF_SECS: i64 = 300;

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

/// Shared handles a job handler needs.
#[derive(Clone)]
struct Ctx {
    pool: PgPool,
    storage: Arc<ObjectStore>,
    sms: Arc<dyn SmsProvider>,
}

/// A handler failure. All variants are recorded on the job row; retryable ones
/// are requeued with backoff until `max_attempts` is exhausted.
#[derive(Debug, thiserror::Error)]
enum JobError {
    #[error(transparent)]
    Db(#[from] sqlx::Error),
    #[error("bad job payload: {0}")]
    BadPayload(String),
    #[error("storage: {0}")]
    Storage(String),
    #[error("image: {0}")]
    Image(String),
    #[error("sms: {0}")]
    Sms(String),
}

/// Run the worker poll loop until a shutdown signal is received.
///
/// # Errors
/// Returns an error only if the loop cannot be established; per-job failures are
/// recorded on the job row and never abort the loop.
pub async fn run(pool: PgPool, storage: ObjectStore, config: WorkerConfig) -> anyhow::Result<()> {
    let worker_id = format!("worker-{}", uuid::Uuid::new_v4());
    tracing::info!(
        worker_id,
        poll_interval_secs = config.poll_interval.as_secs(),
        "worker started"
    );

    // SMS provider: MockProvider in dev/demo. Production wires the
    // AfricasTalking → Infobip FallbackProvider here (§9).
    let ctx = Ctx {
        pool: pool.clone(),
        storage: Arc::new(storage),
        sms: Arc::new(MockProvider),
    };

    let mut ticker = tokio::time::interval(config.poll_interval);
    ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);

    loop {
        tokio::select! {
            _ = ticker.tick() => {
                // Drain all currently-due jobs before sleeping again.
                loop {
                    match jobs::claim_next(&pool, &worker_id).await {
                        Ok(Some(job)) => run_one(&ctx, job).await,
                        Ok(None) => break,
                        Err(error) => {
                            tracing::error!(%error, "failed to claim job");
                            break;
                        }
                    }
                }
            }
            () = shutdown_signal() => {
                tracing::info!("worker shutdown signal received, stopping");
                break;
            }
        }
    }

    Ok(())
}

/// Execute one claimed job and record the outcome.
async fn run_one(ctx: &Ctx, job: Job) {
    let job_id = job.id;
    let result = match job.job_type.as_str() {
        job_type::PROCESS_IMAGE => process_image(ctx, &job).await,
        job_type::SEND_SMS => send_sms(ctx, &job).await,
        other => {
            tracing::warn!(job_id = %job_id, job_type = other, "unknown job type");
            Err(JobError::BadPayload(format!("unknown job type {other}")))
        }
    };

    match result {
        Ok(()) => {
            if let Err(error) = jobs::mark_done(&ctx.pool, job_id).await {
                tracing::error!(job_id = %job_id, %error, "failed to mark job done");
            }
        }
        Err(error) => {
            // Never log the payload (may contain an SMS with a code — §8).
            tracing::warn!(job_id = %job_id, %error, "job failed");
            let backoff = backoff_secs(job.attempts);
            let retry_at = Utc::now() + chrono::Duration::seconds(backoff);
            if let Err(e) = jobs::mark_failed(&ctx.pool, job_id, &error.to_string(), retry_at).await
            {
                tracing::error!(job_id = %job_id, error = %e, "failed to record job failure");
            }
        }
    }
}

/// Exponential backoff (2^attempts seconds), capped.
fn backoff_secs(attempts: i32) -> i64 {
    let exp = attempts.clamp(1, 16);
    (1_i64 << exp).min(MAX_BACKOFF_SECS)
}

/// `process_image`: download → recompress ≤300KB + strip EXIF → thumbnail →
/// upload → mark processed. Idempotent: a missing or already-processed document
/// is a no-op success. PDFs (address proofs) are passed through unmodified.
async fn process_image(ctx: &Ctx, job: &Job) -> Result<(), JobError> {
    let payload: ProcessImagePayload = serde_json::from_value(job.payload.clone())
        .map_err(|e| JobError::BadPayload(e.to_string()))?;

    let Some(doc) = onboardkit_db::documents::get_by_id(&ctx.pool, payload.document_id).await?
    else {
        // The document was deleted / never existed — nothing to do.
        return Ok(());
    };
    if doc.processed {
        return Ok(());
    }

    // Non-images (PDF address proofs) are stored as-is; just mark them ready.
    if !doc.content_type.starts_with("image/") {
        onboardkit_db::documents::mark_processed(&ctx.pool, doc.id, None).await?;
        return Ok(());
    }

    let original = ctx
        .storage
        .get(&doc.storage_key)
        .await
        .map_err(|e| JobError::Storage(e.to_string()))?;

    // `process_photo` re-encodes to JPEG, which drops all EXIF metadata (§10).
    let processed = image_ops::process_photo(&original, MAX_IMAGE_BYTES, THUMB_EDGE)
        .map_err(|e| JobError::Image(e.to_string()))?;

    let thumb_key = storage::thumbnail_key(&doc.storage_key);
    ctx.storage
        .put(&doc.storage_key, processed.jpeg, "image/jpeg")
        .await
        .map_err(|e| JobError::Storage(e.to_string()))?;
    ctx.storage
        .put(&thumb_key, processed.thumbnail, "image/jpeg")
        .await
        .map_err(|e| JobError::Storage(e.to_string()))?;

    onboardkit_db::documents::mark_processed(&ctx.pool, doc.id, Some(&thumb_key)).await?;
    tracing::info!(document_id = %doc.id, "image processed");
    Ok(())
}

/// `send_sms`: deliver one message via the configured provider. The payload may
/// contain a one-time code, so it is never logged (§8).
async fn send_sms(ctx: &Ctx, job: &Job) -> Result<(), JobError> {
    let payload: SendSmsPayload = serde_json::from_value(job.payload.clone())
        .map_err(|e| JobError::BadPayload(e.to_string()))?;
    let phone = Phone::parse(&payload.to_phone)
        .map_err(|_| JobError::BadPayload("invalid phone".into()))?;

    let receipt = ctx
        .sms
        .send(&phone, &payload.message)
        .await
        .map_err(|e| JobError::Sms(e.to_string()))?;
    tracing::info!(provider = receipt.provider, "sms sent");
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
