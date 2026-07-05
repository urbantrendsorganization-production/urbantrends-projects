//! User repository.
//!
//! Most repositories filter by `tenant_id` (§4). The two functions here are the
//! deliberate exception: they are the *authentication identity* path, which must
//! resolve a user (and therefore their tenant) before any tenant is known.
//! `email` is globally unique (see migration 0001), so the lookup is safe.

use onboardkit_core::Role;
use sqlx::PgExecutor;
use uuid::Uuid;

use crate::models::User;

/// Find an active user by email for login. Returns `None` if there is no such
/// active user (callers must treat this identically to a bad password — §8).
///
/// # Errors
/// Returns [`sqlx::Error`] on a query failure or an unrecognized role value.
pub async fn find_active_by_email(
    exec: impl PgExecutor<'_>,
    email: &str,
) -> Result<Option<User>, sqlx::Error> {
    let row = sqlx::query!(
        r#"SELECT id, tenant_id, branch_id, full_name, phone, email,
                  password_hash, role, is_active, created_at
           FROM users
           WHERE email = $1 AND is_active = TRUE"#,
        email,
    )
    .fetch_optional(exec)
    .await?;

    match row {
        None => Ok(None),
        Some(r) => Ok(Some(User {
            id: r.id,
            tenant_id: r.tenant_id,
            branch_id: r.branch_id,
            full_name: r.full_name,
            phone: r.phone,
            email: r.email,
            password_hash: r.password_hash,
            role: Role::from_db(&r.role).map_err(decode_error)?,
            is_active: r.is_active,
            created_at: r.created_at,
        })),
    }
}

/// Load a user by id — used after a refresh token resolves to a `user_id`, to
/// recover the tenant/role for the new access token.
///
/// # Errors
/// Returns [`sqlx::Error`] on a query failure or an unrecognized role value.
pub async fn find_by_id(exec: impl PgExecutor<'_>, id: Uuid) -> Result<Option<User>, sqlx::Error> {
    let row = sqlx::query!(
        r#"SELECT id, tenant_id, branch_id, full_name, phone, email,
                  password_hash, role, is_active, created_at
           FROM users
           WHERE id = $1"#,
        id,
    )
    .fetch_optional(exec)
    .await?;

    match row {
        None => Ok(None),
        Some(r) => Ok(Some(User {
            id: r.id,
            tenant_id: r.tenant_id,
            branch_id: r.branch_id,
            full_name: r.full_name,
            phone: r.phone,
            email: r.email,
            password_hash: r.password_hash,
            role: Role::from_db(&r.role).map_err(decode_error)?,
            is_active: r.is_active,
            created_at: r.created_at,
        })),
    }
}

/// Wrap a domain decode failure as a sqlx decode error.
fn decode_error(err: impl std::error::Error + Send + Sync + 'static) -> sqlx::Error {
    sqlx::Error::Decode(Box::new(err))
}
