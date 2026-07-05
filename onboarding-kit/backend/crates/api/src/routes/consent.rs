//! `POST /applications/:id/consent` (§7) — record the client's acceptance of a
//! specific terms version.

use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::routing::post;
use axum::{Json, Router};
use chrono::Utc;
use onboardkit_db::applications;
use serde::Deserialize;
use uuid::Uuid;

use crate::auth::RequireAgent;
use crate::error::{AppError, AppResult};
use crate::routes::guard::load_owned_editable;
use crate::state::AppState;

#[derive(Deserialize)]
struct ConsentRequest {
    terms_version: String,
    accepted: bool,
}

/// `POST /applications/:id/consent` (agent owner) — stamp `consent_at` and the
/// accepted terms version.
#[tracing::instrument(skip_all)]
async fn consent(
    State(state): State<AppState>,
    RequireAgent(user): RequireAgent,
    Path(id): Path<Uuid>,
    Json(req): Json<ConsentRequest>,
) -> AppResult<StatusCode> {
    let app = load_owned_editable(&state, &user, id).await?;

    if !req.accepted {
        return Err(AppError::Validation(
            "Consent must be explicitly accepted.".to_owned(),
        ));
    }
    if req.terms_version != state.settings.terms_version {
        return Err(AppError::Validation(
            "The terms version is out of date. Please reload and try again.".to_owned(),
        ));
    }

    applications::set_consent(
        &state.pool,
        user.tenant_id(),
        app.id,
        &req.terms_version,
        Utc::now(),
    )
    .await?;
    tracing::info!(application_id = %app.id, "consent recorded");
    Ok(StatusCode::NO_CONTENT)
}

/// Routes owned by this module.
pub fn router() -> Router<AppState> {
    Router::new().route("/applications/{id}/consent", post(consent))
}
