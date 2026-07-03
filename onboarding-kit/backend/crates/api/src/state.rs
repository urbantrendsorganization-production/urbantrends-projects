//! Shared application state passed to every handler via axum's `State`.

use std::sync::Arc;

use jsonwebtoken::{DecodingKey, EncodingKey, Validation};
use sqlx::postgres::PgPool;

use crate::config::JwtConfig;

/// JWT keys and validation rules derived once at startup from [`JwtConfig`].
#[derive(Clone)]
pub struct JwtState {
    pub encoding: EncodingKey,
    pub decoding: DecodingKey,
    pub validation: Validation,
    pub config: JwtConfig,
}

impl JwtState {
    #[must_use]
    pub fn new(config: JwtConfig) -> Self {
        let encoding = EncodingKey::from_secret(config.secret.as_bytes());
        let decoding = DecodingKey::from_secret(config.secret.as_bytes());
        let mut validation = Validation::new(jsonwebtoken::Algorithm::HS256);
        validation.validate_exp = true;
        Self {
            encoding,
            decoding,
            validation,
            config,
        }
    }
}

/// Cloneable, cheap-to-share application state.
#[derive(Clone)]
pub struct AppState {
    pub pool: PgPool,
    pub jwt: Arc<JwtState>,
}

impl AppState {
    #[must_use]
    pub fn new(pool: PgPool, jwt: JwtState) -> Self {
        Self {
            pool,
            jwt: Arc::new(jwt),
        }
    }
}
