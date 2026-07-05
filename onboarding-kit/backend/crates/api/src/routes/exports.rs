//! `GET /exports/approved-clients?format=csv|xlsx` (§7). Admin-only. Column
//! headers honour the tenant's `export_column_mapping` (rename by internal key).

use axum::Router;
use axum::extract::{Query, State};
use axum::http::header::{CONTENT_DISPOSITION, CONTENT_TYPE};
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use onboardkit_db::exports::{self, ApprovedClientRow};
use onboardkit_db::tenants;
use serde::Deserialize;

use crate::auth::RequireAdmin;
use crate::error::{AppError, AppResult};
use crate::state::AppState;

/// Default export columns: `(internal_key, default_header)`, in order.
const COLUMNS: [(&str, &str); 10] = [
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

fn cell(row: &ApprovedClientRow, key: &str) -> String {
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

#[derive(Deserialize)]
struct ExportQuery {
    format: Option<String>,
}

#[tracing::instrument(skip_all)]
async fn approved_clients(
    State(state): State<AppState>,
    RequireAdmin(user): RequireAdmin,
    Query(q): Query<ExportQuery>,
) -> AppResult<Response> {
    let rows = exports::approved_clients(&state.pool, user.tenant_id()).await?;
    let mapping = tenants::export_column_mapping(&state.pool, user.tenant_id()).await?;

    // Header for each column: tenant override by internal key, else the default.
    let headers: Vec<String> = COLUMNS
        .iter()
        .map(|(key, default)| {
            mapping
                .get(*key)
                .and_then(serde_json::Value::as_str)
                .unwrap_or(default)
                .to_owned()
        })
        .collect();

    match q.format.as_deref().unwrap_or("csv") {
        "xlsx" => xlsx_response(&headers, &rows),
        "csv" => csv_response(&headers, &rows),
        other => Err(AppError::Validation(format!(
            "Unsupported export format '{other}'. Use csv or xlsx."
        ))),
    }
}

fn csv_response(headers: &[String], rows: &[ApprovedClientRow]) -> AppResult<Response> {
    let mut wtr = csv::Writer::from_writer(Vec::new());
    wtr.write_record(headers)
        .map_err(|e| AppError::Internal(e.into()))?;
    for row in rows {
        let record: Vec<String> = COLUMNS.iter().map(|(key, _)| cell(row, key)).collect();
        wtr.write_record(&record)
            .map_err(|e| AppError::Internal(e.into()))?;
    }
    let bytes = wtr.into_inner().map_err(|e| AppError::Internal(e.into()))?;
    Ok((
        [
            (CONTENT_TYPE, "text/csv; charset=utf-8"),
            (
                CONTENT_DISPOSITION,
                "attachment; filename=\"approved-clients.csv\"",
            ),
        ],
        bytes,
    )
        .into_response())
}

fn xlsx_response(headers: &[String], rows: &[ApprovedClientRow]) -> AppResult<Response> {
    use rust_xlsxwriter::{Format, Workbook};

    let mut workbook = Workbook::new();
    let sheet = workbook.add_worksheet();
    let bold = Format::new().set_bold();

    for (c, header) in headers.iter().enumerate() {
        let col = u16::try_from(c).unwrap_or(u16::MAX);
        sheet
            .write_string_with_format(0, col, header, &bold)
            .map_err(|e| AppError::Internal(e.into()))?;
    }
    for (r, row) in rows.iter().enumerate() {
        let excel_row = u32::try_from(r + 1).unwrap_or(u32::MAX);
        for (c, (key, _)) in COLUMNS.iter().enumerate() {
            let col = u16::try_from(c).unwrap_or(u16::MAX);
            sheet
                .write_string(excel_row, col, cell(row, key))
                .map_err(|e| AppError::Internal(e.into()))?;
        }
    }
    let bytes = workbook
        .save_to_buffer()
        .map_err(|e| AppError::Internal(e.into()))?;
    Ok((
        [
            (
                CONTENT_TYPE,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            (
                CONTENT_DISPOSITION,
                "attachment; filename=\"approved-clients.xlsx\"",
            ),
        ],
        bytes,
    )
        .into_response())
}

/// Routes owned by this module.
pub fn router() -> Router<AppState> {
    Router::new().route("/exports/approved-clients", get(approved_clients))
}
