//! Approved-client export query + shared CSV rendering (§7). Tenant-scoped. The
//! api layer adds xlsx on top; the worker's nightly digest reuses the CSV path.
//! Both honour the tenant's column mapping via [`headers`].

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

/// Export columns in order: `(internal_key, default_header)`. Shared by the api
/// (`GET /exports/...`) and the worker's nightly digest so both honour the same
/// column set and tenant header overrides.
pub const COLUMNS: [(&str, &str); 10] = [
    ("client_number", "Client Number"),
    ("full_name", "Full Name"),
    ("phone", "Phone"),
    ("national_id_number", "National ID"),
    ("kra_pin", "KRA PIN"),
    ("date_of_birth", "Date of Birth"),
    ("address", "Address"),
    ("product_code", "Product"),
    ("branch_name", "Branch"),
    ("approved_at", "Approved At"),
];

/// The cell value for one export column of one row.
#[must_use]
pub fn cell(row: &ApprovedClientRow, key: &str) -> String {
    match key {
        "client_number" => row.client_number.clone().unwrap_or_default(),
        "full_name" => row.full_name.clone(),
        "phone" => row.phone.clone().unwrap_or_default(),
        "national_id_number" => row.national_id_number.clone().unwrap_or_default(),
        "kra_pin" => row.kra_pin.clone().unwrap_or_default(),
        "date_of_birth" => row.date_of_birth.map(|d| d.to_string()).unwrap_or_default(),
        "address" => row.address.clone().unwrap_or_default(),
        "product_code" => row.product_code.clone(),
        "branch_name" => row.branch_name.clone(),
        "approved_at" => row.approved_at.to_rfc3339(),
        _ => String::new(),
    }
}

/// Resolve ordered header labels, applying the tenant's `export_column_mapping`
/// (internal key → header override) and falling back to each column's default.
#[must_use]
pub fn headers(mapping: &serde_json::Value) -> Vec<String> {
    COLUMNS
        .iter()
        .map(|(key, default)| {
            mapping
                .get(*key)
                .and_then(serde_json::Value::as_str)
                .unwrap_or(default)
                .to_owned()
        })
        .collect()
}

/// Render the approved-client rows to CSV bytes under the given headers.
///
/// # Errors
/// Returns [`csv::Error`] if serialization fails (effectively never for these
/// plain string records).
pub fn render_csv(headers: &[String], rows: &[ApprovedClientRow]) -> Result<Vec<u8>, csv::Error> {
    let mut wtr = csv::Writer::from_writer(Vec::new());
    wtr.write_record(headers)?;
    for row in rows {
        let record: Vec<String> = COLUMNS.iter().map(|(key, _)| cell(row, key)).collect();
        wtr.write_record(&record)?;
    }
    // `IntoInnerError` wraps the underlying io error; surface it as a csv::Error.
    wtr.into_inner()
        .map_err(|e| csv::Error::from(e.into_error()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn sample_row() -> ApprovedClientRow {
        ApprovedClientRow {
            client_number: Some("JM-00001".into()),
            full_name: "Jane Doe".into(),
            phone: Some("+254700000001".into()),
            national_id_number: Some("12345678".into()),
            kra_pin: None,
            date_of_birth: None,
            address: Some("Nairobi".into()),
            product_code: "SAV".into(),
            branch_name: "Kilimani".into(),
            approved_at: Utc.with_ymd_and_hms(2026, 7, 5, 8, 0, 0).unwrap(),
        }
    }

    #[test]
    fn headers_apply_tenant_overrides() {
        let mapping = serde_json::json!({ "full_name": "Client Name" });
        let h = headers(&mapping);
        assert_eq!(h.len(), COLUMNS.len());
        assert_eq!(h[0], "Client Number"); // default kept
        assert_eq!(h[1], "Client Name"); // overridden
    }

    #[test]
    fn render_csv_emits_header_plus_row() {
        let h = headers(&serde_json::json!({}));
        let bytes = render_csv(&h, &[sample_row()]).unwrap();
        let text = String::from_utf8(bytes).unwrap();
        let lines: Vec<&str> = text.lines().collect();
        assert_eq!(lines.len(), 2);
        assert!(lines[0].starts_with("Client Number,Full Name,Phone"));
        assert!(lines[1].contains("JM-00001"));
        assert!(lines[1].contains("Jane Doe"));
    }

    #[test]
    fn render_csv_empty_is_header_only() {
        let h = headers(&serde_json::json!({}));
        let bytes = render_csv(&h, &[]).unwrap();
        assert_eq!(String::from_utf8(bytes).unwrap().lines().count(), 1);
    }
}
