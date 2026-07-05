//! Tenant repository. Minimal for now — the runtime is single-tenant (§4).

use sqlx::PgExecutor;
use uuid::Uuid;

use crate::models::Tenant;

/// Load a tenant by id.
///
/// # Errors
/// Returns [`sqlx::Error`] on a query failure.
pub async fn find_by_id(
    exec: impl PgExecutor<'_>,
    id: Uuid,
) -> Result<Option<Tenant>, sqlx::Error> {
    sqlx::query_as!(Tenant, r#"SELECT id, name FROM tenants WHERE id = $1"#, id,)
        .fetch_optional(exec)
        .await
}
