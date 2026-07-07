//! JWT authentication skeleton (CLAUDE.md §7).
//!
//! Phase 0 ships only access-token *validation* and a claims extractor — token
//! issuance, refresh rotation and RBAC scoping land in Phase 1.

use axum::extract::FromRequestParts;
use axum::http::header::AUTHORIZATION;
use axum::http::request::Parts;
use chrono::Utc;
use jsonwebtoken::{Header, decode, encode};
use onboardkit_core::Role;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::error::AppError;
use crate::state::{AppState, JwtState};

/// Access-token claims. `sub` is the user id; `tenant_id` is resolved from the
/// user row at login and never from client input (CLAUDE.md §4).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Claims {
    pub sub: Uuid,
    pub tenant_id: Uuid,
    /// The user's branch (agents/reviewers); `None` for tenant-wide admins.
    #[serde(default)]
    pub branch_id: Option<Uuid>,
    pub role: Role,
    /// Expiry, seconds since the Unix epoch.
    pub exp: i64,
    /// Issued-at, seconds since the Unix epoch.
    pub iat: i64,
}

/// An authenticated caller, extracted from a validated `Bearer` access token.
///
/// Usage: add `user: AuthUser` as a handler argument to require authentication.
#[derive(Debug, Clone)]
pub struct AuthUser {
    pub claims: Claims,
}

impl AuthUser {
    #[must_use]
    pub fn user_id(&self) -> Uuid {
        self.claims.sub
    }

    #[must_use]
    pub fn tenant_id(&self) -> Uuid {
        self.claims.tenant_id
    }

    #[must_use]
    pub fn branch_id(&self) -> Option<Uuid> {
        self.claims.branch_id
    }

    #[must_use]
    pub fn role(&self) -> Role {
        self.claims.role
    }
}

impl FromRequestParts<AppState> for AuthUser {
    type Rejection = AppError;

    async fn from_request_parts(
        parts: &mut Parts,
        state: &AppState,
    ) -> Result<Self, Self::Rejection> {
        let header = parts
            .headers
            .get(AUTHORIZATION)
            .ok_or(AppError::Unauthorized)?
            .to_str()
            .map_err(|_| AppError::Unauthorized)?;

        let token = header
            .strip_prefix("Bearer ")
            .map(str::trim)
            .filter(|token| !token.is_empty())
            .ok_or(AppError::Unauthorized)?;

        let data = decode::<Claims>(token, &state.jwt.decoding, &state.jwt.validation)
            .map_err(|_| AppError::Unauthorized)?;

        Ok(AuthUser {
            claims: data.claims,
        })
    }
}

/// A freshly issued access token and its lifetime in seconds.
#[derive(Debug, Clone)]
pub struct IssuedAccess {
    pub token: String,
    pub expires_in: i64,
}

/// Issue a signed access JWT for a user. The tenant always comes from the user
/// row, never from client input (CLAUDE.md §4).
///
/// # Errors
/// Returns [`AppError::Internal`] if signing fails.
pub fn issue_access_token(
    jwt: &JwtState,
    user_id: Uuid,
    tenant_id: Uuid,
    branch_id: Option<Uuid>,
    role: Role,
) -> Result<IssuedAccess, AppError> {
    let ttl = i64::try_from(jwt.config.access_ttl.as_secs()).unwrap_or(i64::MAX);
    let now = Utc::now().timestamp();
    let claims = Claims {
        sub: user_id,
        tenant_id,
        branch_id,
        role,
        iat: now,
        exp: now + ttl,
    };
    let token = encode(&Header::default(), &claims, &jwt.encoding)
        .map_err(|error| AppError::Internal(error.into()))?;
    Ok(IssuedAccess {
        token,
        expires_in: ttl,
    })
}

/// Generate the RBAC extractors. Each wraps [`AuthUser`] and rejects with 403
/// unless the caller holds the required role (CLAUDE.md §7). RBAC lives here in
/// the extractor layer, not ad hoc inside handlers.
macro_rules! role_guard {
    ($(#[$meta:meta])* $name:ident, $role:expr) => {
        $(#[$meta])*
        #[derive(Debug, Clone)]
        pub struct $name(pub AuthUser);

        impl FromRequestParts<AppState> for $name {
            type Rejection = AppError;

            async fn from_request_parts(
                parts: &mut Parts,
                state: &AppState,
            ) -> Result<Self, Self::Rejection> {
                let user = AuthUser::from_request_parts(parts, state).await?;
                if user.role() == $role {
                    Ok($name(user))
                } else {
                    Err(AppError::Forbidden)
                }
            }
        }
    };
}

role_guard!(
    /// Requires an authenticated agent.
    RequireAgent,
    Role::Agent
);
role_guard!(
    /// Requires an authenticated reviewer.
    RequireReviewer,
    Role::Reviewer
);
role_guard!(
    /// Requires an authenticated admin.
    RequireAdmin,
    Role::Admin
);

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use chrono::Utc;
    use jsonwebtoken::{Header, encode};
    use uuid::Uuid;

    use super::Claims;
    use crate::config::JwtConfig;
    use crate::state::JwtState;
    use onboardkit_core::Role;

    fn jwt_state() -> JwtState {
        JwtState::new(JwtConfig {
            secret: "test-secret-that-is-at-least-32-bytes!!".to_string(),
            access_ttl: Duration::from_secs(901),
            refresh_ttl: Duration::from_secs(901),
        })
    }

    fn claims(exp_offset_secs: i64) -> Claims {
        let now = Utc::now().timestamp();
        Claims {
            sub: Uuid::new_v4(),
            tenant_id: Uuid::new_v4(),
            branch_id: None,
            role: Role::Agent,
            iat: now,
            exp: now + exp_offset_secs,
        }
    }

    #[test]
    fn valid_token_decodes_back_to_claims() {
        let state = jwt_state();
        let original = claims(900);
        let token = encode(&Header::default(), &original, &state.encoding).expect("encode");

        let decoded = jsonwebtoken::decode::<Claims>(&token, &state.decoding, &state.validation)
            .expect("decode")
            .claims;

        assert_eq!(decoded.sub, original.sub);
        assert_eq!(decoded.tenant_id, original.tenant_id);
        assert_eq!(decoded.role, Role::Agent);
    }

    #[test]
    fn expired_token_is_rejected() {
        let state = jwt_state();
        // Beyond jsonwebtoken's default 60s leeway.
        let token = encode(&Header::default(), &claims(-120), &state.encoding).expect("encode");

        let result = jsonwebtoken::decode::<Claims>(&token, &state.decoding, &state.validation);
        assert!(result.is_err(), "expired token must not validate");
    }

    #[test]
    fn wrong_secret_is_rejected() {
        let token =
            encode(&Header::default(), &claims(900), &jwt_state().encoding).expect("encode");

        let other = JwtState::new(JwtConfig {
            secret: "a-completely-different-secret-32bytes!".to_string(),
            access_ttl: Duration::from_secs(901),
            refresh_ttl: Duration::from_secs(901),
        });
        let result = jsonwebtoken::decode::<Claims>(&token, &other.decoding, &other.validation);
        assert!(result.is_err(), "token signed with another key must fail");
    }
}
