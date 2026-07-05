//! Client phone OTP endpoints (§7, §8). The OTP is sent to the *client's* phone
//! (never the agent's) and, on success, stamps `otp_verified_at`.

use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::routing::post;
use axum::{Json, Router};
use chrono::{DateTime, Utc};
use onboardkit_db::{applications, clients};
use onboardkit_integrations::otp::{OtpError, OtpPurpose};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::auth::RequireAgent;
use crate::error::{AppError, AppResult};
use crate::routes::guard::load_owned_editable;
use crate::state::AppState;

/// Collapse OTP errors onto safe HTTP responses. Verification failures are
/// deliberately generic so nothing about the check leaks (§8).
fn map_otp_err(err: &OtpError) -> AppError {
    match err {
        OtpError::InvalidPhone => AppError::Validation("Invalid phone number.".to_owned()),
        OtpError::RateLimited => AppError::TooManyRequests,
        OtpError::Verification => {
            AppError::BadRequest("The verification code is invalid or has expired.".to_owned())
        }
        OtpError::Rng => AppError::Internal(anyhow::anyhow!("otp rng failure")),
        OtpError::Store(e) => AppError::Internal(anyhow::anyhow!(e.0.clone())),
    }
}

/// Resolve the client's phone for an application, or a validation error.
async fn client_phone(state: &AppState, tenant_id: Uuid, client_id: Uuid) -> AppResult<String> {
    let client = clients::get(&state.pool, tenant_id, client_id)
        .await?
        .ok_or(AppError::NotFound)?;
    client
        .phone
        .filter(|p| !p.is_empty())
        .ok_or_else(|| AppError::Validation("The client has no phone number yet.".to_owned()))
}

#[derive(Serialize)]
struct SendResponse {
    expires_at: DateTime<Utc>,
    /// Present only in dev when `DEV_EXPOSE_OTP=true` (§8). Never in production.
    #[serde(skip_serializing_if = "Option::is_none")]
    dev_code: Option<String>,
}

/// `POST /applications/:id/otp/send` — issue an OTP to the client's phone.
#[tracing::instrument(skip_all)]
async fn send(
    State(state): State<AppState>,
    RequireAgent(user): RequireAgent,
    Path(id): Path<Uuid>,
) -> AppResult<Json<SendResponse>> {
    let app = load_owned_editable(&state, &user, id).await?;
    let phone = client_phone(&state, user.tenant_id(), app.client_id).await?;

    let outcome = state
        .otp
        .send(user.tenant_id(), &phone, OtpPurpose::ClientOnboarding)
        .await
        .map_err(|e| map_otp_err(&e))?;

    // Phase 3 wires the send_sms job; until then the dev flag surfaces the code.
    let dev_code = state.settings.dev_expose_otp.then_some(outcome.code);
    Ok(Json(SendResponse {
        expires_at: outcome.expires_at,
        dev_code,
    }))
}

#[derive(Deserialize)]
struct VerifyRequest {
    code: String,
}

/// `POST /applications/:id/otp/verify` — verify the code and stamp
/// `otp_verified_at` on success.
#[tracing::instrument(skip_all)]
async fn verify(
    State(state): State<AppState>,
    RequireAgent(user): RequireAgent,
    Path(id): Path<Uuid>,
    Json(req): Json<VerifyRequest>,
) -> AppResult<StatusCode> {
    let app = load_owned_editable(&state, &user, id).await?;
    let phone = client_phone(&state, user.tenant_id(), app.client_id).await?;

    state
        .otp
        .verify(
            user.tenant_id(),
            &phone,
            &req.code,
            OtpPurpose::ClientOnboarding,
        )
        .await
        .map_err(|e| map_otp_err(&e))?;

    applications::set_otp_verified(&state.pool, user.tenant_id(), app.id, Utc::now()).await?;
    tracing::info!(application_id = %app.id, "client otp verified");
    Ok(StatusCode::NO_CONTENT)
}

/// Routes owned by this module.
pub fn router() -> Router<AppState> {
    Router::new()
        .route("/applications/{id}/otp/send", post(send))
        .route("/applications/{id}/otp/verify", post(verify))
}
