//! Application event log + transition recording (§6).
//!
//! Every transition writes exactly one `application_events` row and updates the
//! denormalized `current_status` in the same transaction. The append-only
//! guarantee is enforced by DB triggers (migration 0002).

use chrono::{DateTime, Utc};
use onboardkit_core::{Status, StatusKind};
use sqlx::PgExecutor;
use sqlx::postgres::PgPool;
use uuid::Uuid;

use crate::models::ApplicationEvent;

/// Outcome of a reviewer transition. `client_number` is set only on approval.
#[derive(Debug, Clone)]
pub struct TransitionOutcome {
    pub client_number: Option<String>,
}

/// Record a reviewer-driven transition atomically (§6): update the denormalized
/// status, append exactly one event (with reason/notes if any), and — on
/// approval — assign the tenant-scoped `client_number`. The tenant row is locked
/// first so concurrent approvals never mint duplicate numbers.
///
/// # Errors
/// Returns [`sqlx::Error`] on failure (the whole unit rolls back).
#[allow(clippy::too_many_arguments)]
pub async fn record_transition(
    pool: &PgPool,
    tenant_id: Uuid,
    application_id: Uuid,
    client_id: Uuid,
    actor_user_id: Uuid,
    from: StatusKind,
    to: &Status,
    at: DateTime<Utc>,
) -> Result<TransitionOutcome, sqlx::Error> {
    let mut tx = pool.begin().await?;

    sqlx::query!(
        r#"UPDATE onboarding_applications SET current_status = $3, updated_at = $4
           WHERE id = $1 AND tenant_id = $2"#,
        application_id,
        tenant_id,
        to.kind().as_str(),
        at,
    )
    .execute(&mut *tx)
    .await?;

    let mut client_number = None;
    if to.kind() == StatusKind::Approved {
        // Serialize numbering on the tenant row, then assign the next sequence.
        let prefix = sqlx::query!(
            r#"SELECT name FROM tenants WHERE id = $1 FOR UPDATE"#,
            tenant_id
        )
        .fetch_one(&mut *tx)
        .await?
        .name;
        let prefix = client_number_prefix(&prefix);

        let next = sqlx::query!(
            r#"SELECT COUNT(*) AS "count!" FROM clients
               WHERE tenant_id = $1 AND client_number IS NOT NULL"#,
            tenant_id
        )
        .fetch_one(&mut *tx)
        .await?
        .count
            + 1;
        let number = format!("{prefix}-{next:05}");

        let assigned = sqlx::query!(
            r#"UPDATE clients SET client_number = $3
               WHERE id = $1 AND tenant_id = $2 AND client_number IS NULL
               RETURNING client_number"#,
            client_id,
            tenant_id,
            number,
        )
        .fetch_optional(&mut *tx)
        .await?;
        client_number = assigned.and_then(|r| r.client_number);
    }

    sqlx::query!(
        r#"INSERT INTO application_events
             (tenant_id, application_id, actor_user_id, from_status, to_status, reason)
           VALUES ($1, $2, $3, $4, $5, $6)"#,
        tenant_id,
        application_id,
        actor_user_id,
        from.as_str(),
        to.kind().as_str(),
        to.reason(),
    )
    .execute(&mut *tx)
    .await?;

    tx.commit().await?;
    Ok(TransitionOutcome { client_number })
}

/// Derive a client-number prefix from a tenant name: uppercase initials, max 4
/// letters (e.g. "Jubilant Microfinance" -> "JM").
fn client_number_prefix(name: &str) -> String {
    let initials: String = name
        .split_whitespace()
        .filter_map(|w| w.chars().next())
        .filter(|c| c.is_alphabetic())
        .take(4)
        .collect::<String>()
        .to_uppercase();
    if initials.is_empty() {
        "CLT".to_owned()
    } else {
        initials
    }
}

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
