//! `GET /reports/summary` (§7) — admin analytics: onboardings per agent/branch,
//! average time-to-approval (derived from the event log), rejection breakdown.

use axum::extract::{Query, State};
use axum::routing::get;
use axum::{Json, Router};
use chrono::{DateTime, Utc};
use onboardkit_db::reports;
use serde::{Deserialize, Serialize};
use utoipa::ToSchema;
use uuid::Uuid;

use crate::auth::RequireAdmin;
use crate::error::AppResult;
use crate::state::AppState;

#[derive(Deserialize)]
pub(crate) struct ReportQuery {
    from: Option<DateTime<Utc>>,
    to: Option<DateTime<Utc>>,
}

#[derive(Serialize, ToSchema)]
pub(crate) struct AgentStat {
    agent_id: Uuid,
    agent_name: String,
    total: i64,
    approved: i64,
}

#[derive(Serialize, ToSchema)]
pub(crate) struct BranchStat {
    branch_id: Uuid,
    branch_name: String,
    total: i64,
}

#[derive(Serialize, ToSchema)]
pub(crate) struct RejectionReason {
    reason: String,
    count: i64,
}

#[derive(Serialize, ToSchema)]
pub(crate) struct Summary {
    per_agent: Vec<AgentStat>,
    per_branch: Vec<BranchStat>,
    rejection_reasons: Vec<RejectionReason>,
    avg_time_to_approval_secs: Option<f64>,
}

#[utoipa::path(
    get,
    path = "/api/v1/reports/summary",
    tag = "reports",
    security(("bearer_auth" = [])),
    params(
        ("from" = Option<String>, Query, description = "RFC3339 start of window"),
        ("to" = Option<String>, Query, description = "RFC3339 end of window"),
    ),
    responses((status = 200, description = "Onboarding analytics summary", body = Summary)),
)]
#[tracing::instrument(skip_all)]
pub(crate) async fn summary(
    State(state): State<AppState>,
    RequireAdmin(user): RequireAdmin,
    Query(q): Query<ReportQuery>,
) -> AppResult<Json<Summary>> {
    let tenant = user.tenant_id();
    let per_agent = reports::per_agent(&state.pool, tenant, q.from, q.to)
        .await?
        .into_iter()
        .map(|s| AgentStat {
            agent_id: s.agent_id,
            agent_name: s.agent_name,
            total: s.total,
            approved: s.approved,
        })
        .collect();
    let per_branch = reports::per_branch(&state.pool, tenant, q.from, q.to)
        .await?
        .into_iter()
        .map(|s| BranchStat {
            branch_id: s.branch_id,
            branch_name: s.branch_name,
            total: s.total,
        })
        .collect();
    let rejection_reasons = reports::rejection_reasons(&state.pool, tenant)
        .await?
        .into_iter()
        .map(|r| RejectionReason {
            reason: r.reason,
            count: r.count,
        })
        .collect();
    let avg_time_to_approval_secs = reports::avg_time_to_approval_secs(&state.pool, tenant).await?;

    Ok(Json(Summary {
        per_agent,
        per_branch,
        rejection_reasons,
        avg_time_to_approval_secs,
    }))
}

/// Routes owned by this module.
pub fn router() -> Router<AppState> {
    Router::new().route("/reports/summary", get(summary))
}
