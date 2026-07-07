//! `GET /me` — the authenticated caller's identity. Any valid access token.

use axum::Json;
use axum::Router;
use axum::routing::get;
use onboardkit_core::Role;
use serde::Serialize;
use utoipa::ToSchema;
use uuid::Uuid;

use crate::auth::AuthUser;
use crate::state::AppState;

#[derive(Serialize, ToSchema)]
pub(crate) struct MeResponse {
    user_id: Uuid,
    tenant_id: Uuid,
    #[schema(value_type = String)]
    role: Role,
}

#[utoipa::path(
    get,
    path = "/api/v1/me",
    tag = "session",
    security(("bearer_auth" = [])),
    responses(
        (status = 200, description = "The authenticated caller", body = MeResponse),
        (status = 401, description = "Missing or invalid access token"),
    ),
)]
pub(crate) async fn me(user: AuthUser) -> Json<MeResponse> {
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
