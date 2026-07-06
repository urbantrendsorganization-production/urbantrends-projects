//! `GET /api/v1/health` — liveness + database readiness.

use axum::Json;
use axum::Router;
use axum::extract::State;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use serde::Serialize;
use utoipa::ToSchema;

use crate::state::AppState;

#[derive(Serialize, ToSchema)]
pub(crate) struct HealthResponse {
    #[schema(value_type = String)]
    status: &'static str,
    #[schema(value_type = String)]
    service: &'static str,
    #[schema(value_type = String)]
    version: &'static str,
    #[schema(value_type = String)]
    database: &'static str,
}

/// Health handler. Returns 200 when the database is reachable, 503 otherwise so
/// that container orchestration can gate traffic on real readiness.
#[utoipa::path(
    get,
    path = "/api/v1/health",
    tag = "health",
    responses(
        (status = 200, description = "Service and database healthy", body = HealthResponse),
        (status = 503, description = "Database unreachable", body = HealthResponse),
    ),
)]
#[tracing::instrument(skip(state))]
pub(crate) async fn health(State(state): State<AppState>) -> Response {
    match sqlx::query_scalar::<_, i32>("SELECT 1")
        .fetch_one(&state.pool)
        .await
    {
        Ok(_) => (
            StatusCode::OK,
            Json(HealthResponse {
                status: "ok",
                service: "onboardkit-api",
                version: env!("CARGO_PKG_VERSION"),
                database: "up",
            }),
        )
            .into_response(),
        Err(error) => {
            tracing::warn!(error = ?error, "health check: database ping failed");
            (
                StatusCode::SERVICE_UNAVAILABLE,
                Json(HealthResponse {
                    status: "degraded",
                    service: "onboardkit-api",
                    version: env!("CARGO_PKG_VERSION"),
                    database: "down",
                }),
            )
                .into_response()
        }
    }
}

/// Routes owned by this module.
pub fn router() -> Router<AppState> {
    Router::new().route("/health", get(health))
}
