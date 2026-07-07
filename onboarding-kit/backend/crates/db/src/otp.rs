//! OTP verification repository (§8). Tenant-scoped.
//!
//! These functions back the OTP service's store (the api provides the glue that
//! implements `onboardkit_integrations::otp::OtpStore`).

use chrono::{DateTime, Utc};
use sqlx::PgExecutor;
use uuid::Uuid;

use crate::models::OtpRow;

/// Count OTP sends for a phone/purpose at or after `since` (send rate limit).
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn count_recent_sends(
    exec: impl PgExecutor<'_>,
    tenant_id: Uuid,
    phone: &str,
    purpose: &str,
    since: DateTime<Utc>,
) -> Result<i64, sqlx::Error> {
    let row = sqlx::query!(
        r#"SELECT COUNT(*) AS "count!"
           FROM otp_verifications
           WHERE tenant_id = $1 AND phone = $2 AND purpose = $3 AND created_at >= $4"#,
        tenant_id,
        phone,
        purpose,
        since,
    )
    .fetch_one(exec)
    .await?;
    Ok(row.count)
}

/// Insert a new OTP, returning its id.
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
#[allow(clippy::too_many_arguments)]
pub async fn insert(
    exec: impl PgExecutor<'_>,
    tenant_id: Uuid,
    phone: &str,
    code_hash: &str,
    purpose: &str,
    max_attempts: i32,
    expires_at: DateTime<Utc>,
    created_at: DateTime<Utc>,
) -> Result<Uuid, sqlx::Error> {
    let row = sqlx::query!(
        r#"INSERT INTO otp_verifications
             (tenant_id, phone, code_hash, purpose, max_attempts, expires_at, created_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7)
           RETURNING id"#,
        tenant_id,
        phone,
        code_hash,
        purpose,
        max_attempts,
        expires_at,
        created_at,
    )
    .fetch_one(exec)
    .await?;
    Ok(row.id)
}

/// The most recently created OTP for a phone/purpose.
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn latest(
    exec: impl PgExecutor<'_>,
    tenant_id: Uuid,
    phone: &str,
    purpose: &str,
) -> Result<Option<OtpRow>, sqlx::Error> {
    sqlx::query_as!(
        OtpRow,
        r#"SELECT id, code_hash, expires_at, attempts, max_attempts, verified_at
           FROM otp_verifications
           WHERE tenant_id = $1 AND phone = $2 AND purpose = $3
           ORDER BY created_at DESC
           LIMIT 1"#,
        tenant_id,
        phone,
        purpose,
    )
    .fetch_optional(exec)
    .await
}

/// Record one consumed verification attempt.
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn increment_attempts(exec: impl PgExecutor<'_>, id: Uuid) -> Result<(), sqlx::Error> {
    sqlx::query!(
        r#"UPDATE otp_verifications SET attempts = attempts + 1 WHERE id = $1"#,
        id,
    )
    .execute(exec)
    .await?;
    Ok(())
}

/// Mark an OTP as verified (single-use).
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn mark_verified(
    exec: impl PgExecutor<'_>,
    id: Uuid,
    at: DateTime<Utc>,
) -> Result<(), sqlx::Error> {
    sqlx::query!(
        r#"UPDATE otp_verifications SET verified_at = $2 WHERE id = $1"#,
        id,
        at,
    )
    .execute(exec)
    .await?;
    Ok(())
}
