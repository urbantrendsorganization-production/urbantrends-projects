//! Application event log + transition recording (§6).
//!
//! Every transition writes exactly one `application_events` row and updates the
//! denormalized `current_status` in the same transaction. The append-only
//! guarantee is enforced by DB triggers (migration 0002).

use chrono::{DateTime, Utc};
use onboardkit_core::StatusKind;
use sqlx::PgExecutor;
use sqlx::postgres::PgPool;
use uuid::Uuid;

use crate::models::ApplicationEvent;

/// Record a submit transition (`Draft`/`ReturnedForCorrection` -> `Submitted`):
/// update status, stamp `submitted_at`, and append the event, atomically.
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn record_submit(
    pool: &PgPool,
    tenant_id: Uuid,
    application_id: Uuid,
    actor_user_id: Uuid,
    from: StatusKind,
    at: DateTime<Utc>,
) -> Result<(), sqlx::Error> {
    let mut tx = pool.begin().await?;

    sqlx::query!(
        r#"UPDATE onboarding_applications
           SET current_status = 'submitted', submitted_at = $3
           WHERE id = $1 AND tenant_id = $2"#,
        application_id,
        tenant_id,
        at,
    )
    .execute(&mut *tx)
    .await?;

    sqlx::query!(
        r#"INSERT INTO application_events
             (tenant_id, application_id, actor_user_id, from_status, to_status)
           VALUES ($1, $2, $3, $4, 'submitted')"#,
        tenant_id,
        application_id,
        actor_user_id,
        from.as_str(),
    )
    .execute(&mut *tx)
    .await?;

    tx.commit().await?;
    Ok(())
}

/// List an application's event history, oldest first.
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn list(
    exec: impl PgExecutor<'_>,
    tenant_id: Uuid,
    application_id: Uuid,
) -> Result<Vec<ApplicationEvent>, sqlx::Error> {
    sqlx::query_as!(
        ApplicationEvent,
        r#"SELECT id, application_id, actor_user_id, from_status, to_status, reason, created_at
           FROM application_events
           WHERE tenant_id = $1 AND application_id = $2
           ORDER BY created_at ASC"#,
        tenant_id,
        application_id,
    )
    .fetch_all(exec)
    .await
}
