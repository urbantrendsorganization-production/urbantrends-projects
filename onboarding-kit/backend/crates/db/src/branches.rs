//! Branch repository. Tenant-scoped (§4).

use sqlx::PgExecutor;
use uuid::Uuid;

use crate::models::Branch;

/// List all branches for a tenant, newest first.
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn list(exec: impl PgExecutor<'_>, tenant_id: Uuid) -> Result<Vec<Branch>, sqlx::Error> {
    sqlx::query_as!(
        Branch,
        r#"SELECT id, tenant_id, name, code, created_at
           FROM branches WHERE tenant_id = $1 ORDER BY name"#,
        tenant_id,
    )
    .fetch_all(exec)
    .await
}

/// Create a branch.
///
/// # Errors
/// Returns [`sqlx::Error`] on failure (including a duplicate `code`).
pub async fn create(
    exec: impl PgExecutor<'_>,
    tenant_id: Uuid,
    name: &str,
    code: &str,
) -> Result<Branch, sqlx::Error> {
    sqlx::query_as!(
        Branch,
        r#"INSERT INTO branches (tenant_id, name, code) VALUES ($1, $2, $3)
           RETURNING id, tenant_id, name, code, created_at"#,
        tenant_id,
        name,
        code,
    )
    .fetch_one(exec)
    .await
}

/// Update a branch's name/code (both optional; `None` leaves unchanged).
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn update(
    exec: impl PgExecutor<'_>,
    tenant_id: Uuid,
    id: Uuid,
    name: Option<&str>,
    code: Option<&str>,
) -> Result<Option<Branch>, sqlx::Error> {
    sqlx::query_as!(
        Branch,
        r#"UPDATE branches SET
             name = COALESCE($3, name),
             code = COALESCE($4, code)
           WHERE id = $1 AND tenant_id = $2
           RETURNING id, tenant_id, name, code, created_at"#,
        id,
        tenant_id,
        name,
        code,
    )
    .fetch_optional(exec)
    .await
}
