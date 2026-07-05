//! Admin endpoints. Phase 1 ships a single stubbed, admin-only endpoint to
//! anchor the RBAC layer; the real CRUD (branches, users, products) and reports
//! land in Phase 4 (§18).

use axum::Json;
use axum::Router;
use axum::routing::get;
use serde::Serialize;
use uuid::Uuid;

use crate::auth::RequireAdmin;
use crate::state::AppState;

#[derive(Serialize)]
struct AdminOverview {
    tenant_id: Uuid,
    message: &'static str,
}

/// `GET /admin/overview` — admin only. Placeholder until Phase 4.
async fn overview(RequireAdmin(user): RequireAdmin) -> Json<AdminOverview> {
    Json(AdminOverview {
        tenant_id: user.tenant_id(),
        message: "admin panel endpoints are stubbed in Phase 1",
    })
}

/// Routes owned by this module.
pub fn router() -> Router<AppState> {
    Router::new().route("/admin/overview", get(overview))
}
