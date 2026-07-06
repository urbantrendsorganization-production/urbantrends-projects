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

// Column set, cell rendering, header resolution, and CSV rendering are shared
// with the worker's nightly digest via `onboardkit_db::exports`. The xlsx path
// stays here (the worker archives CSV only).

#[derive(Deserialize)]
pub(crate) struct ExportQuery {
    format: Option<String>,
}

#[utoipa::path(
    get,
    path = "/api/v1/exports/approved-clients",
    tag = "exports",
    security(("bearer_auth" = [])),
    params(("format" = Option<String>, Query, description = "csv (default) or xlsx")),
    responses(
        (status = 200, description = "Approved-clients export (CSV or XLSX attachment)", content_type = "text/csv"),
        (status = 422, description = "Unsupported format"),
    ),
)]
#[tracing::instrument(skip_all)]
pub(crate) async fn approved_clients(
    State(state): State<AppState>,
    RequireAdmin(user): RequireAdmin,
    Query(q): Query<ExportQuery>,
) -> AppResult<Response> {
    let rows = exports::approved_clients(&state.pool, user.tenant_id()).await?;
    let mapping = tenants::export_column_mapping(&state.pool, user.tenant_id()).await?;
    let headers = exports::headers(&mapping);

    match q.format.as_deref().unwrap_or("csv") {
        "xlsx" => xlsx_response(&headers, &rows),
        "csv" => csv_response(&headers, &rows),
        other => Err(AppError::Validation(format!(
            "Unsupported export format '{other}'. Use csv or xlsx."
        ))),
    }
}

fn csv_response(headers: &[String], rows: &[ApprovedClientRow]) -> AppResult<Response> {
    let bytes = exports::render_csv(headers, rows).map_err(|e| AppError::Internal(e.into()))?;
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
        for (c, (key, _)) in exports::COLUMNS.iter().enumerate() {
            let col = u16::try_from(c).unwrap_or(u16::MAX);
            sheet
                .write_string(excel_row, col, exports::cell(row, key))
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
