//! Shared ownership / state guards for the application endpoints.
//!
//! Every lookup is tenant-scoped (§4). Agent-driven edits are permitted only on
//! applications the agent owns and only while the application is in an editable
//! state (`Draft` / `ReturnedForCorrection`).

use onboardkit_core::{StatusKind, TransitionError};
use onboardkit_db::Application;
use onboardkit_db::applications;
use uuid::Uuid;

use crate::auth::AuthUser;
use crate::error::{AppError, AppResult};
use crate::state::AppState;

/// The four KYC document types required for a complete application (§5, §6).
pub(crate) const REQUIRED_DOC_TYPES: [&str; 4] = ["id_front", "id_back", "selfie", "address_proof"];

/// Load an application within the caller's tenant, or 404.
pub(crate) async fn load_application(
    state: &AppState,
    tenant_id: Uuid,
    id: Uuid,
) -> AppResult<Application> {
    applications::get(&state.pool, tenant_id, id)
        .await?
        .ok_or(AppError::NotFound)
}

/// Load an application the agent owns, or 404 (ownership failures are 404 so the
/// existence of another agent's application never leaks).
pub(crate) async fn load_owned(
    state: &AppState,
    user: &AuthUser,
    id: Uuid,
) -> AppResult<Application> {
    let app = load_application(state, user.tenant_id(), id).await?;
    if app.agent_id != user.user_id() {
        return Err(AppError::NotFound);
    }
    Ok(app)
}

/// Load an application the agent owns and that is still editable, else 404/409.
pub(crate) async fn load_owned_editable(
    state: &AppState,
    user: &AuthUser,
    id: Uuid,
) -> AppResult<Application> {
    let app = load_owned(state, user, id).await?;
    if !matches!(
        app.current_status,
        StatusKind::Draft | StatusKind::ReturnedForCorrection
    ) {
        return Err(AppError::Conflict(
            "This application can no longer be edited.".to_owned(),
        ));
    }
    Ok(app)
}

/// Map a state-machine [`TransitionError`] onto the right HTTP error, without
/// leaking internal detail beyond the already-safe messages.
#[must_use]
pub(crate) fn map_transition_err(err: &TransitionError) -> AppError {
    match err {
        TransitionError::Unauthorized { .. } => AppError::Forbidden,
        TransitionError::InvalidTransition { .. } => AppError::Conflict(err.to_string()),
        TransitionError::EmptyReason => {
            AppError::Validation("A rejection reason is required.".to_owned())
        }
        TransitionError::EmptyNotes => {
            AppError::Validation("Return notes are required.".to_owned())
        }
    }
}
