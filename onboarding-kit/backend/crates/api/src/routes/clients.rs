//! `POST /clients` — an agent creates a client shell to begin onboarding (§7).

use axum::extract::State;
use axum::routing::post;
use axum::{Json, Router};

use onboardkit_db::clients;
use serde::Deserialize;

use crate::auth::RequireAgent;
use crate::error::{AppError, AppResult};
use crate::routes::dto::{ClientResponse, client_dto};
use crate::state::AppState;

#[derive(Deserialize)]
struct CreateClientRequest {
    full_name: String,
}

/// `POST /clients` (agent) — create a client with just a name; details are
/// filled in progressively during the draft.
#[tracing::instrument(skip_all)]
async fn create(
    State(state): State<AppState>,
    RequireAgent(user): RequireAgent,
    Json(req): Json<CreateClientRequest>,
) -> AppResult<(axum::http::StatusCode, Json<ClientResponse>)> {
    let full_name = req.full_name.trim();
    if full_name.is_empty() {
        return Err(AppError::Validation(
            "A client name is required.".to_owned(),
        ));
    }

    let client = clients::create(&state.pool, user.tenant_id(), full_name).await?;
    tracing::info!(client_id = %client.id, "client created");
    Ok((axum::http::StatusCode::CREATED, Json(client_dto(client))))
}

/// Routes owned by this module.
pub fn router() -> Router<AppState> {
    Router::new().route("/clients", post(create))
}
