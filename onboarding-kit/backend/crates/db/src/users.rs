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

/// What an admin supplies to create a user. `password_hash` is argon2id, hashed
/// in the api layer (`db` cannot depend on `integrations` — §2).
#[derive(Debug, Clone)]
pub struct NewUser {
    pub branch_id: Option<Uuid>,
    pub full_name: String,
    pub phone: String,
    pub email: String,
    pub password_hash: String,
    pub role: Role,
}

/// List all users in a tenant (admin, tenant-wide — §7), newest first.
///
/// # Errors
/// Returns [`sqlx::Error`] on a query failure or an unrecognized role value.
pub async fn list(exec: impl PgExecutor<'_>, tenant_id: Uuid) -> Result<Vec<User>, sqlx::Error> {
    let rows = sqlx::query!(
        r#"SELECT id, tenant_id, branch_id, full_name, phone, email,
                  password_hash, role, is_active, created_at
           FROM users WHERE tenant_id = $1 ORDER BY created_at DESC"#,
        tenant_id,
    )
    .fetch_all(exec)
    .await?;

    rows.into_iter()
        .map(|r| {
            Ok(User {
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
            })
        })
        .collect()
}

/// Create a user in a tenant (admin — §7).
///
/// # Errors
/// Returns [`sqlx::Error`] on failure (including a duplicate email).
pub async fn create(
    exec: impl PgExecutor<'_>,
    tenant_id: Uuid,
    new: &NewUser,
) -> Result<Uuid, sqlx::Error> {
    let row = sqlx::query!(
        r#"INSERT INTO users
             (tenant_id, branch_id, full_name, phone, email, password_hash, role)
           VALUES ($1, $2, $3, $4, $5, $6, $7)
           RETURNING id"#,
        tenant_id,
        new.branch_id,
        new.full_name,
        new.phone,
        new.email,
        new.password_hash,
        new.role.as_str(),
    )
    .fetch_one(exec)
    .await?;
    Ok(row.id)
}

/// Update a user's branch / active flag (admin — §7). Both optional.
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn update(
    exec: impl PgExecutor<'_>,
    tenant_id: Uuid,
    id: Uuid,
    branch_id: Option<Uuid>,
    is_active: Option<bool>,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query!(
        r#"UPDATE users SET
             branch_id = COALESCE($3, branch_id),
             is_active = COALESCE($4, is_active)
           WHERE id = $1 AND tenant_id = $2"#,
        id,
        tenant_id,
        branch_id,
        is_active,
    )
    .execute(exec)
    .await?;
    Ok(result.rows_affected() > 0)
}

/// Wrap a domain decode failure as a sqlx decode error.
fn decode_error(err: impl std::error::Error + Send + Sync + 'static) -> sqlx::Error {
    sqlx::Error::Decode(Box::new(err))
}
