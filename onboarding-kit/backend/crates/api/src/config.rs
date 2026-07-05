//! Application configuration, loaded from the environment only (CLAUDE.md §3).

use std::net::SocketAddr;
use std::time::Duration;

/// Deployment environment, controls logging format among other things.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AppEnv {
    Development,
    Production,
}

impl AppEnv {
    #[must_use]
    pub fn is_production(self) -> bool {
        matches!(self, AppEnv::Production)
    }
}

/// JWT signing/verification configuration (CLAUDE.md §7).
#[derive(Debug, Clone)]
pub struct JwtConfig {
    pub secret: String,
    pub access_ttl: Duration,
    pub refresh_ttl: Duration,
}

/// Runtime settings for the onboarding flow.
#[derive(Debug, Clone)]
pub struct Settings {
    /// Dev-only: return OTP codes in API responses so the flow is testable
    /// without live SMS. MUST default off (§8).
    pub dev_expose_otp: bool,
    /// The consent terms version clients must accept.
    pub terms_version: String,
}

/// Fully-resolved application configuration.
#[derive(Debug, Clone)]
pub struct Config {
    pub app_env: AppEnv,
    pub bind_addr: SocketAddr,
    pub database_url: String,
    pub db_max_connections: u32,
    pub jwt: JwtConfig,
    pub storage: onboardkit_integrations::StorageConfig,
    pub settings: Settings,
}

impl Config {
    /// Load configuration from environment variables.
    ///
    /// # Errors
    /// Returns an error if a required variable is missing or a typed variable
    /// (port, address, TTL) cannot be parsed.
    pub fn from_env() -> anyhow::Result<Self> {
        let app_env = match std::env::var("APP_ENV").as_deref() {
            Ok("production") => AppEnv::Production,
            _ => AppEnv::Development,
        };

        let host = std::env::var("API_HOST").unwrap_or_else(|_| "0.0.0.0".to_string());
        let port = parse_env("API_PORT", 8080u16)?;
        let bind_addr: SocketAddr = format!("{host}:{port}")
            .parse()
            .map_err(|_| anyhow::anyhow!("invalid API_HOST/API_PORT: {host}:{port}"))?;

        let database_url = require_env("DATABASE_URL")?;
        let db_max_connections = parse_env("DB_MAX_CONNECTIONS", 10u32)?;

        let secret = require_env("JWT_SECRET")?;
        if secret.len() < 32 {
            anyhow::bail!("JWT_SECRET must be at least 32 characters");
        }
        let access_ttl = Duration::from_secs(parse_env("JWT_ACCESS_TTL_SECS", 900u64)?);
        let refresh_ttl = Duration::from_secs(parse_env("JWT_REFRESH_TTL_SECS", 1_209_600u64)?);

        let storage = onboardkit_integrations::StorageConfig {
            endpoint: require_env("S3_ENDPOINT")?,
            region: std::env::var("S3_REGION").unwrap_or_else(|_| "us-east-1".to_string()),
            bucket: require_env("S3_BUCKET")?,
            access_key_id: require_env("S3_ACCESS_KEY_ID")?,
            secret_access_key: require_env("S3_SECRET_ACCESS_KEY")?,
            force_path_style: parse_env("S3_FORCE_PATH_STYLE", true)?,
        };

        let settings = Settings {
            dev_expose_otp: parse_env("DEV_EXPOSE_OTP", false)?,
            terms_version: std::env::var("CONSENT_TERMS_VERSION")
                .unwrap_or_else(|_| "v1".to_string()),
        };

        Ok(Self {
            app_env,
            bind_addr,
            database_url,
            db_max_connections,
            jwt: JwtConfig {
                secret,
                access_ttl,
                refresh_ttl,
            },
            storage,
            settings,
        })
    }
}

fn require_env(key: &str) -> anyhow::Result<String> {
    std::env::var(key)
        .map_err(|_| anyhow::anyhow!("required environment variable {key} is not set"))
}

fn parse_env<T>(key: &str, default: T) -> anyhow::Result<T>
where
    T: std::str::FromStr,
    T::Err: std::fmt::Display,
{
    match std::env::var(key) {
        Ok(raw) => raw
            .parse::<T>()
            .map_err(|error| anyhow::anyhow!("invalid value for {key}: {error}")),
        Err(_) => Ok(default),
    }
}
