//! `POST /applications/:id/review` (§7) — reviewer transitions: start_review,
//! approve (assigns client_number + SMS), reject (reason), return (notes).

use axum::extract::{Path, State};
use axum::routing::post;
use axum::{Json, Router};
use chrono::Utc;
use onboardkit_core::jobs::{SendSmsPayload, job_type};
use onboardkit_core::{Actor, Role, TransitionAction, apply_transition};
use onboardkit_db::{clients, events, jobs};
use serde::Deserialize;
use uuid::Uuid;

use crate::auth::RequireReviewer;
use crate::error::{AppError, AppResult};
use crate::routes::dto::{ApplicationResponse, application_dto};
use crate::routes::guard::{load_application, map_transition_err};
use crate::state::AppState;

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum ReviewAction {
    StartReview,
    Approve,
    Reject,
    Return,
}

#[derive(Deserialize)]
struct ReviewRequest {
    action: ReviewAction,
    #[serde(default)]
    reason: Option<String>,
    #[serde(default)]
    notes: Option<String>,
}

/// `POST /applications/:id/review` — perform a reviewer transition (§6). The
/// reviewer may only act on applications within their own branch.
#[tracing::instrument(skip_all)]
async fn review(
    State(state): State<AppState>,
    RequireReviewer(user): RequireReviewer,
    Path(id): Path<Uuid>,
    Json(req): Json<ReviewRequest>,
) -> AppResult<Json<ApplicationResponse>> {
    let app = load_application(&state, user.tenant_id(), id).await?;
    // Branch scoping — a reviewer never sees other branches' work (§7). 404 so
    // existence never leaks across branches.
    if user.branch_id() != Some(app.branch_id) {
        return Err(AppError::NotFound);
    }

    let action = match req.action {
        ReviewAction::StartReview => TransitionAction::StartReview,
        ReviewAction::Approve => TransitionAction::Approve,
        ReviewAction::Reject => TransitionAction::Reject {
            reason: req.reason.clone().unwrap_or_default(),
        },
        ReviewAction::Return => TransitionAction::Return {
            notes: req.notes.clone().unwrap_or_default(),
        },
    };

    let actor = Actor::new(Role::Reviewer, false);
    let transition =
        apply_transition(app.current_status, action, actor).map_err(|e| map_transition_err(&e))?;

    let outcome = events::record_transition(
        &state.pool,
        user.tenant_id(),
        app.id,
        app.client_id,
        user.user_id(),
        app.current_status,
        &transition.to,
        Utc::now(),
    )
    .await?;

    // Notify the client on terminal / actionable outcomes (§6 side effects). SMS
    // always goes through the jobs table — handlers never call providers inline.
    if let Some(message) = notification_message(&transition.to, outcome.client_number.as_deref()) {
        enqueue_client_sms(&state, user.tenant_id(), app.client_id, message).await?;
    }

    let updated = load_application(&state, user.tenant_id(), app.id).await?;
    tracing::info!(application_id = %app.id, to = transition.to.kind().as_str(), "review transition applied");
    Ok(Json(application_dto(updated)))
}

/// Build the client-facing SMS for a transition, or `None` when none is due.
fn notification_message(
    to: &onboardkit_core::Status,
    client_number: Option<&str>,
) -> Option<String> {
    use onboardkit_core::Status;
    match to {
        Status::Approved => Some(format!(
            "Your account has been approved. Your client number is {}.",
            client_number.unwrap_or("(pending)")
        )),
        Status::Rejected { reason } => Some(format!(
            "Your application was not approved. Reason: {reason}"
        )),
        Status::ReturnedForCorrection { notes } => {
            Some(format!("Your application needs corrections: {notes}"))
        }
        _ => None,
    }
}

/// Enqueue an SMS to the client's phone (skipped if the client has none).
async fn enqueue_client_sms(
    state: &AppState,
    tenant_id: Uuid,
    client_id: Uuid,
    message: String,
) -> AppResult<()> {
    let Some(client) = clients::get(&state.pool, tenant_id, client_id).await? else {
        return Ok(());
    };
    let Some(phone) = client.phone.filter(|p| !p.is_empty()) else {
        tracing::warn!("client has no phone; skipping notification SMS");
        return Ok(());
    };
    let payload = serde_json::to_value(SendSmsPayload {
        to_phone: phone,
        message,
    })
    .map_err(|e| AppError::Internal(e.into()))?;
    jobs::enqueue(&state.pool, job_type::SEND_SMS, payload).await?;
    Ok(())
}

/// Routes owned by this module.
pub fn router() -> Router<AppState> {
    Router::new().route("/applications/{id}/review", post(review))
}
