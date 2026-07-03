//! `GET /api/v1/health` — liveness + database readiness.

use axum::Json;
use axum::Router;
use axum::extract::State;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use serde::Serialize;

use crate::state::AppState;

#[derive(Serialize)]
struct HealthResponse {
    status: &'static str,
    service: &'static str,
    version: &'static str,
    database: &'static str,
}

/// Health handler. Returns 200 when the database is reachable, 503 otherwise so
/// that container orchestration can gate traffic on real readiness.
#[tracing::instrument(skip(state))]
async fn health(State(state): State<AppState>) -> Response {
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
