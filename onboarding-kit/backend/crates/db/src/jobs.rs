//! Postgres-backed job queue (CLAUDE.md §10).
//!
//! `claim_next` uses `FOR UPDATE SKIP LOCKED` so multiple workers never grab the
//! same job. Retries use backoff by pushing `run_at` into the future; a job that
//! exhausts `max_attempts` becomes `failed`.

use chrono::{DateTime, Utc};
use sqlx::PgExecutor;
use sqlx::postgres::PgPool;
use uuid::Uuid;

/// A claimed unit of work.
#[derive(Debug, Clone)]
pub struct Job {
    pub id: Uuid,
    pub job_type: String,
    pub payload: serde_json::Value,
    pub attempts: i32,
    pub max_attempts: i32,
}

/// Enqueue a job to run as soon as possible.
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn enqueue(
    exec: impl PgExecutor<'_>,
    job_type: &str,
    payload: serde_json::Value,
) -> Result<Uuid, sqlx::Error> {
    let row = sqlx::query!(
        r#"INSERT INTO jobs (job_type, payload) VALUES ($1, $2) RETURNING id"#,
        job_type,
        payload,
    )
    .fetch_one(exec)
    .await?;
    Ok(row.id)
}

/// Atomically claim the next due job, marking it `running` and incrementing
/// `attempts`. Returns `None` when nothing is due.
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn claim_next(pool: &PgPool, worker_id: &str) -> Result<Option<Job>, sqlx::Error> {
    let row = sqlx::query!(
        r#"UPDATE jobs SET
             status = 'running',
             locked_at = now(),
             locked_by = $1,
             attempts = attempts + 1
           WHERE id = (
             SELECT id FROM jobs
             WHERE status = 'pending' AND run_at <= now()
             ORDER BY run_at
             FOR UPDATE SKIP LOCKED
             LIMIT 1
           )
           RETURNING id, job_type, payload, attempts, max_attempts"#,
        worker_id,
    )
    .fetch_optional(pool)
    .await?;

    Ok(row.map(|r| Job {
        id: r.id,
        job_type: r.job_type,
        payload: r.payload,
        attempts: r.attempts,
        max_attempts: r.max_attempts,
    }))
}

/// Mark a job successfully completed.
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn mark_done(exec: impl PgExecutor<'_>, id: Uuid) -> Result<(), sqlx::Error> {
    sqlx::query!(
        r#"UPDATE jobs SET status = 'done', locked_at = NULL, locked_by = NULL WHERE id = $1"#,
        id,
    )
    .execute(exec)
    .await?;
    Ok(())
}

/// Record a failed attempt. If attempts remain, requeue at `retry_at`
/// (backoff); otherwise mark `failed`.
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn mark_failed(
    exec: impl PgExecutor<'_>,
    id: Uuid,
    error: &str,
    retry_at: DateTime<Utc>,
) -> Result<(), sqlx::Error> {
    sqlx::query!(
        r#"UPDATE jobs SET
             status = CASE WHEN attempts >= max_attempts THEN 'failed' ELSE 'pending' END,
             run_at = CASE WHEN attempts >= max_attempts THEN run_at ELSE $2 END,
             last_error = $3,
             locked_at = NULL,
             locked_by = NULL
           WHERE id = $1"#,
        id,
        retry_at,
        error,
    )
    .execute(exec)
    .await?;
    Ok(())
}
