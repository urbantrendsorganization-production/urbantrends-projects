//! Client repository. Tenant-scoped (§4).

use chrono::NaiveDate;
use sqlx::PgExecutor;
use uuid::Uuid;

use crate::models::Client;

/// Fields patchable during a draft. `None` leaves the column unchanged.
#[derive(Debug, Default, Clone)]
pub struct ClientPatch {
    pub full_name: Option<String>,
    pub phone: Option<String>,
    pub national_id_number: Option<String>,
    pub kra_pin: Option<String>,
    pub date_of_birth: Option<NaiveDate>,
    pub address: Option<String>,
    pub next_of_kin: Option<serde_json::Value>,
}

/// Create a client shell with just a name (§7).
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn create(
    exec: impl PgExecutor<'_>,
    tenant_id: Uuid,
    full_name: &str,
) -> Result<Client, sqlx::Error> {
    sqlx::query_as!(
        Client,
        r#"INSERT INTO clients (tenant_id, full_name)
           VALUES ($1, $2)
           RETURNING id, tenant_id, full_name, phone, national_id_number, kra_pin,
                     date_of_birth, address, next_of_kin, client_number, created_at"#,
        tenant_id,
        full_name,
    )
    .fetch_one(exec)
    .await
}

/// Load a client by id within a tenant.
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn get(
    exec: impl PgExecutor<'_>,
    tenant_id: Uuid,
    id: Uuid,
) -> Result<Option<Client>, sqlx::Error> {
    sqlx::query_as!(
        Client,
        r#"SELECT id, tenant_id, full_name, phone, national_id_number, kra_pin,
                  date_of_birth, address, next_of_kin, client_number, created_at
           FROM clients WHERE id = $1 AND tenant_id = $2"#,
        id,
        tenant_id,
    )
    .fetch_optional(exec)
    .await
}

/// Apply a partial update, leaving `None` fields untouched (progressive save).
///
/// # Errors
/// Returns [`sqlx::Error`] on failure (including a unique-phone conflict).
pub async fn patch(
    exec: impl PgExecutor<'_>,
    tenant_id: Uuid,
    id: Uuid,
    patch: &ClientPatch,
) -> Result<Client, sqlx::Error> {
    sqlx::query_as!(
        Client,
        r#"UPDATE clients SET
             full_name          = COALESCE($3, full_name),
             phone              = COALESCE($4, phone),
             national_id_number = COALESCE($5, national_id_number),
             kra_pin            = COALESCE($6, kra_pin),
             date_of_birth      = COALESCE($7, date_of_birth),
             address            = COALESCE($8, address),
             next_of_kin        = COALESCE($9, next_of_kin)
           WHERE id = $1 AND tenant_id = $2
           RETURNING id, tenant_id, full_name, phone, national_id_number, kra_pin,
                     date_of_birth, address, next_of_kin, client_number, created_at"#,
        id,
        tenant_id,
        patch.full_name,
        patch.phone,
        patch.national_id_number,
        patch.kra_pin,
        patch.date_of_birth,
        patch.address,
        patch.next_of_kin,
    )
    .fetch_one(exec)
    .await
}
