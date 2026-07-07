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

/// All tenant ids, oldest first. Used by the worker's nightly digest cron tick
/// to fan out one job per tenant (§10). The runtime is single-tenant today (§4),
/// but the digest is tenant-agnostic so it needs no change when that grows.
///
/// # Errors
/// Returns [`sqlx::Error`] on a query failure.
pub async fn all_ids(exec: impl PgExecutor<'_>) -> Result<Vec<Uuid>, sqlx::Error> {
    sqlx::query_scalar!(r#"SELECT id FROM tenants ORDER BY created_at"#)
        .fetch_all(exec)
        .await
}

/// The tenant's export column-mapping spec (§7), a JSON object mapping internal
/// column keys to exported header labels. Empty (`{}`) means use defaults.
///
/// # Errors
/// Returns [`sqlx::Error`] on a query failure.
pub async fn export_column_mapping(
    exec: impl PgExecutor<'_>,
    id: Uuid,
) -> Result<serde_json::Value, sqlx::Error> {
    let row = sqlx::query!(
        r#"SELECT export_column_mapping FROM tenants WHERE id = $1"#,
        id,
    )
    .fetch_one(exec)
    .await?;
    Ok(row.export_column_mapping)
}
