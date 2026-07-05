//! Authentication endpoints: login, refresh (rotating), logout (CLAUDE.md §7).
//!
//! Refresh tokens are opaque, stored only as sha256 hashes, rotated on every
//! refresh and revocable. Access tokens are short-lived JWTs. Failure responses
//! are deliberately generic so they never reveal whether an email exists.

use std::sync::LazyLock;

use axum::Json;
use axum::Router;
use axum::extract::State;
use axum::http::StatusCode;
use axum::routing::post;
use chrono::{Duration, Utc};
use onboardkit_core::Role;
use onboardkit_db::{refresh_tokens, users};
use onboardkit_integrations::{password, token};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::auth::issue_access_token;
use crate::error::{AppError, AppResult};
use crate::state::AppState;

/// A valid argon2id hash verified against when no user matches, so login timing
/// does not leak whether an email exists (§8).
static DUMMY_HASH: LazyLock<String> =
    LazyLock::new(|| password::hash("timing-equalizer-not-a-real-secret").unwrap_or_default());

#[derive(Deserialize)]
struct LoginRequest {
    email: String,
    password: String,
}

#[derive(Deserialize)]
struct RefreshRequest {
    refresh_token: String,
}

#[derive(Deserialize)]
struct LogoutRequest {
    refresh_token: String,
}

#[derive(Serialize)]
struct TokenResponse {
    access_token: String,
    refresh_token: String,
    token_type: &'static str,
    /// Access-token lifetime in seconds.
    expires_in: i64,
    role: Role,
    user_id: Uuid,
    tenant_id: Uuid,
}

/// Issue an access token + a fresh refresh token for `user`, persisting the
/// refresh token's hash.
async fn issue_tokens(
    state: &AppState,
    user_id: Uuid,
    tenant_id: Uuid,
    branch_id: Option<Uuid>,
    role: Role,
) -> AppResult<TokenResponse> {
    let access = issue_access_token(&state.jwt, user_id, tenant_id, branch_id, role)?;

    let refresh = token::generate_opaque().map_err(|e| AppError::Internal(e.into()))?;
    let refresh_hash = token::sha256_hex(&refresh);
    let ttl_secs = i64::try_from(state.jwt.config.refresh_ttl.as_secs()).unwrap_or(i64::MAX);
    let expires_at = Utc::now() + Duration::seconds(ttl_secs);
    refresh_tokens::insert(&state.pool, user_id, &refresh_hash, expires_at).await?;

    Ok(TokenResponse {
        access_token: access.token,
        refresh_token: refresh,
        token_type: "Bearer",
        expires_in: access.expires_in,
        role,
        user_id,
        tenant_id,
    })
}

/// `POST /auth/login`
#[tracing::instrument(skip_all)]
async fn login(
    State(state): State<AppState>,
    Json(req): Json<LoginRequest>,
) -> AppResult<Json<TokenResponse>> {
    let Some(user) = users::find_active_by_email(&state.pool, &req.email).await? else {
        // Spend comparable time so a missing user is indistinguishable from a
        // wrong password.
        let _ = password::verify(&req.password, &DUMMY_HASH);
        return Err(AppError::Unauthorized);
    };

    if !password::verify(&req.password, &user.password_hash).unwrap_or(false) {
        return Err(AppError::Unauthorized);
    }

    let response = issue_tokens(&state, user.id, user.tenant_id, user.branch_id, user.role).await?;
    tracing::info!(user_id = %user.id, role = user.role.as_str(), "login succeeded");
    Ok(Json(response))
}

/// `POST /auth/refresh` — rotate the refresh token and mint a new access token.
#[tracing::instrument(skip_all)]
async fn refresh(
    State(state): State<AppState>,
    Json(req): Json<RefreshRequest>,
) -> AppResult<Json<TokenResponse>> {
    let now = Utc::now();
    let presented_hash = token::sha256_hex(&req.refresh_token);

    let Some(record) = refresh_tokens::find_by_hash(&state.pool, &presented_hash).await? else {
        return Err(AppError::Unauthorized);
    };
    if !record.is_active(now) {
        return Err(AppError::Unauthorized);
    }

    let Some(user) = users::find_by_id(&state.pool, record.user_id).await? else {
        return Err(AppError::Unauthorized);
    };
    if !user.is_active {
        return Err(AppError::Unauthorized);
    }

    // Rotate: revoke the presented token and issue a new one atomically. A
    // `None` result means the token was already revoked — reuse, treat as auth
    // failure.
    let new_refresh = token::generate_opaque().map_err(|e| AppError::Internal(e.into()))?;
    let new_hash = token::sha256_hex(&new_refresh);
    let ttl_secs = i64::try_from(state.jwt.config.refresh_ttl.as_secs()).unwrap_or(i64::MAX);
    let expires_at = now + Duration::seconds(ttl_secs);

    let rotated =
        refresh_tokens::rotate(&state.pool, record.id, user.id, &new_hash, expires_at, now).await?;
    if rotated.is_none() {
        tracing::warn!(user_id = %user.id, "refresh token reuse detected");
        return Err(AppError::Unauthorized);
    }

    let access = issue_access_token(
        &state.jwt,
        user.id,
        user.tenant_id,
        user.branch_id,
        user.role,
    )?;
    Ok(Json(TokenResponse {
        access_token: access.token,
        refresh_token: new_refresh,
        token_type: "Bearer",
        expires_in: access.expires_in,
        role: user.role,
        user_id: user.id,
        tenant_id: user.tenant_id,
    }))
}

/// `POST /auth/logout` — revoke the presented refresh token. Idempotent.
#[tracing::instrument(skip_all)]
async fn logout(
    State(state): State<AppState>,
    Json(req): Json<LogoutRequest>,
) -> AppResult<StatusCode> {
    let hash = token::sha256_hex(&req.refresh_token);
    let _revoked = refresh_tokens::revoke_by_hash(&state.pool, &hash, Utc::now()).await?;
    Ok(StatusCode::NO_CONTENT)
}

/// Routes owned by this module.
pub fn router() -> Router<AppState> {
    Router::new()
        .route("/auth/login", post(login))
        .route("/auth/refresh", post(refresh))
        .route("/auth/logout", post(logout))
}
