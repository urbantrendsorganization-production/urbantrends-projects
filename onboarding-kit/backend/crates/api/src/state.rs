//! Shared application state passed to every handler via axum's `State`.

use std::sync::Arc;

use jsonwebtoken::{DecodingKey, EncodingKey, Validation};
use onboardkit_integrations::ObjectStore;
use onboardkit_integrations::otp::OtpService;
use sqlx::postgres::PgPool;

use crate::config::{JwtConfig, Settings};
use crate::otp_store::PgOtpStore;

/// The concrete OTP service type used across the app.
pub type Otp = OtpService<PgOtpStore>;

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
    pub storage: Arc<ObjectStore>,
    pub otp: Arc<Otp>,
    pub settings: Arc<Settings>,
}

impl AppState {
    #[must_use]
    pub fn new(pool: PgPool, jwt: JwtState, storage: ObjectStore, settings: Settings) -> Self {
        let otp = OtpService::new(PgOtpStore::new(pool.clone()));
        Self {
            pool,
            jwt: Arc::new(jwt),
            storage: Arc::new(storage),
            otp: Arc::new(otp),
            settings: Arc::new(settings),
        }
    }
}
