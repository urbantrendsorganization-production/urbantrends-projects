//! `GET /me` — the authenticated caller's identity. Any valid access token.

use axum::Json;
use axum::Router;
use axum::routing::get;
use onboardkit_core::Role;
use serde::Serialize;
use uuid::Uuid;

use crate::auth::AuthUser;
use crate::state::AppState;

#[derive(Serialize)]
struct MeResponse {
    user_id: Uuid,
    tenant_id: Uuid,
    role: Role,
}

async fn me(user: AuthUser) -> Json<MeResponse> {
    Json(MeResponse {
        user_id: user.user_id(),
        tenant_id: user.tenant_id(),
        role: user.role(),
    })
}

/// Routes owned by this module.
pub fn router() -> Router<AppState> {
    Router::new().route("/me", get(me))
}
