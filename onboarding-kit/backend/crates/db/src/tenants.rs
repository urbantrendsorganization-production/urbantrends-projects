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
