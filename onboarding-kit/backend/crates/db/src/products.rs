//! Product repository. Tenant-scoped (§4).

use sqlx::PgExecutor;
use uuid::Uuid;

use crate::models::Product;

/// List products for a tenant.
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn list(exec: impl PgExecutor<'_>, tenant_id: Uuid) -> Result<Vec<Product>, sqlx::Error> {
    sqlx::query_as!(
        Product,
        r#"SELECT id, tenant_id, code, name, is_active, created_at
           FROM products WHERE tenant_id = $1 ORDER BY name"#,
        tenant_id,
    )
    .fetch_all(exec)
    .await
}

/// Create a product.
///
/// # Errors
/// Returns [`sqlx::Error`] on failure (including a duplicate `code`).
pub async fn create(
    exec: impl PgExecutor<'_>,
    tenant_id: Uuid,
    code: &str,
    name: &str,
) -> Result<Product, sqlx::Error> {
    sqlx::query_as!(
        Product,
        r#"INSERT INTO products (tenant_id, code, name) VALUES ($1, $2, $3)
           RETURNING id, tenant_id, code, name, is_active, created_at"#,
        tenant_id,
        code,
        name,
    )
    .fetch_one(exec)
    .await
}

/// Update a product's name/active flag (both optional).
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn update(
    exec: impl PgExecutor<'_>,
    tenant_id: Uuid,
    id: Uuid,
    name: Option<&str>,
    is_active: Option<bool>,
) -> Result<Option<Product>, sqlx::Error> {
    sqlx::query_as!(
        Product,
        r#"UPDATE products SET
             name = COALESCE($3, name),
             is_active = COALESCE($4, is_active)
           WHERE id = $1 AND tenant_id = $2
           RETURNING id, tenant_id, code, name, is_active, created_at"#,
        id,
        tenant_id,
        name,
        is_active,
    )
    .fetch_optional(exec)
    .await
}
