//! Approved-client export query (§7). Tenant-scoped. The api layer renders these
//! rows to CSV/xlsx, honouring the tenant's column mapping.

use chrono::{DateTime, NaiveDate, Utc};
use sqlx::PgExecutor;
use uuid::Uuid;

/// One approved client, flattened with its onboarding context for export.
#[derive(Debug, Clone)]
pub struct ApprovedClientRow {
    pub client_number: Option<String>,
    pub full_name: String,
    pub phone: Option<String>,
    pub national_id_number: Option<String>,
    pub kra_pin: Option<String>,
    pub date_of_birth: Option<NaiveDate>,
    pub address: Option<String>,
    pub product_code: String,
    pub branch_name: String,
    pub approved_at: DateTime<Utc>,
}

/// List all approved clients in a tenant, ordered by client number.
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn approved_clients(
    exec: impl PgExecutor<'_>,
    tenant_id: Uuid,
) -> Result<Vec<ApprovedClientRow>, sqlx::Error> {
    let rows = sqlx::query!(
        r#"SELECT c.client_number, c.full_name, c.phone, c.national_id_number,
                  c.kra_pin, c.date_of_birth, c.address,
                  a.product_code, b.name AS branch_name, a.updated_at AS approved_at
           FROM clients c
           JOIN onboarding_applications a
             ON a.client_id = c.id AND a.tenant_id = c.tenant_id
           JOIN branches b ON b.id = a.branch_id
           WHERE c.tenant_id = $1 AND a.current_status = 'approved'
           ORDER BY c.client_number"#,
        tenant_id,
    )
    .fetch_all(exec)
    .await?;
    Ok(rows
        .into_iter()
        .map(|r| ApprovedClientRow {
            client_number: r.client_number,
            full_name: r.full_name,
            phone: r.phone,
            national_id_number: r.national_id_number,
            kra_pin: r.kra_pin,
            date_of_birth: r.date_of_birth,
            address: r.address,
            product_code: r.product_code,
            branch_name: r.branch_name,
            approved_at: r.approved_at,
        })
        .collect())
}
