//! Refresh-token repository (§7).
//!
//! Tokens are opaque secrets; only their sha256 hash is ever stored. Lookups are
//! by hash (the token is the secret), part of the authentication path, so they
//! are not tenant-scoped — the token already identifies exactly one user.

use chrono::{DateTime, Utc};
use sqlx::PgExecutor;
use sqlx::postgres::PgPool;
use uuid::Uuid;

use crate::models::RefreshToken;

/// Insert a new refresh token, returning its id.
///
/// # Errors
/// Returns [`sqlx::Error`] on failure (e.g. a hash collision on the unique
/// index).
pub async fn insert(
    exec: impl PgExecutor<'_>,
    user_id: Uuid,
    token_hash: &str,
    expires_at: DateTime<Utc>,
) -> Result<Uuid, sqlx::Error> {
    let rec = sqlx::query!(
        r#"INSERT INTO refresh_tokens (user_id, token_hash, expires_at)
           VALUES ($1, $2, $3)
           RETURNING id"#,
        user_id,
        token_hash,
        expires_at,
    )
    .fetch_one(exec)
    .await?;
    Ok(rec.id)
}

/// Look up a refresh token by its sha256 hash.
///
/// # Errors
/// Returns [`sqlx::Error`] on a query failure.
pub async fn find_by_hash(
    exec: impl PgExecutor<'_>,
    token_hash: &str,
) -> Result<Option<RefreshToken>, sqlx::Error> {
    sqlx::query_as!(
        RefreshToken,
        r#"SELECT id, user_id, expires_at, revoked_at, created_at
           FROM refresh_tokens
           WHERE token_hash = $1"#,
        token_hash,
    )
    .fetch_optional(exec)
    .await
}

/// Revoke a token by its hash (logout). Returns whether a live token was
/// revoked. Idempotent: revoking an already-revoked/absent token returns false.
///
/// # Errors
/// Returns [`sqlx::Error`] on a query failure.
pub async fn revoke_by_hash(
    exec: impl PgExecutor<'_>,
    token_hash: &str,
    now: DateTime<Utc>,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query!(
        r#"UPDATE refresh_tokens
           SET revoked_at = $2
           WHERE token_hash = $1 AND revoked_at IS NULL"#,
        token_hash,
        now,
    )
    .execute(exec)
    .await?;
    Ok(result.rows_affected() > 0)
}

/// Atomically rotate a refresh token: revoke the old one and issue a new one in
/// a single transaction (§3, §7).
///
/// Returns `Some(new_id)` on success, or `None` if the old token was already
/// revoked — which signals refresh-token reuse (possible theft) and must be
/// treated as an auth failure by the caller.
///
/// # Errors
/// Returns [`sqlx::Error`] on a query/transaction failure.
pub async fn rotate(
    pool: &PgPool,
    old_id: Uuid,
    user_id: Uuid,
    new_token_hash: &str,
    expires_at: DateTime<Utc>,
    now: DateTime<Utc>,
) -> Result<Option<Uuid>, sqlx::Error> {
    let mut tx = pool.begin().await?;

    let revoked = sqlx::query!(
        r#"UPDATE refresh_tokens
           SET revoked_at = $2
           WHERE id = $1 AND revoked_at IS NULL"#,
        old_id,
        now,
    )
    .execute(&mut *tx)
    .await?;

    if revoked.rows_affected() == 0 {
        // Old token was already revoked: reuse detected. Roll back, no new token.
        tx.rollback().await?;
        return Ok(None);
    }

    let rec = sqlx::query!(
        r#"INSERT INTO refresh_tokens (user_id, token_hash, expires_at)
           VALUES ($1, $2, $3)
           RETURNING id"#,
        user_id,
        new_token_hash,
        expires_at,
    )
    .fetch_one(&mut *tx)
    .await?;

    tx.commit().await?;
    Ok(Some(rec.id))
}
