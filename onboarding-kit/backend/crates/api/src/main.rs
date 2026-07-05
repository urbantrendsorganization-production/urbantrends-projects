//! API binary entrypoint (`cargo run -p onboardkit-api --bin api`).

#![warn(clippy::pedantic)]
#![allow(clippy::doc_markdown)]

use std::net::SocketAddr;

use onboardkit_api::config::Config;
use onboardkit_api::state::{AppState, JwtState};
use onboardkit_api::{build_router, shutdown_signal, telemetry};
use onboardkit_db::PoolConfig;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Load .env in development; a missing file is not an error (prod uses real env).
    let _ = dotenvy::dotenv();

    let config = Config::from_env()?;
    telemetry::init(config.app_env.is_production());

    tracing::info!(
        env = ?config.app_env,
        bind = %config.bind_addr,
        "starting onboardkit-api"
    );

    let pool = onboardkit_db::connect(
        &config.database_url,
        &PoolConfig {
            max_connections: config.db_max_connections,
            ..PoolConfig::default()
        },
    )
    .await?;

    // Self-provision the schema on boot so a fresh database is ready to serve.
    onboardkit_db::run_migrations(&pool).await?;
    tracing::info!("migrations applied");

    let storage = onboardkit_integrations::ObjectStore::new(&config.storage);
    if let Err(error) = storage.ensure_bucket().await {
        tracing::warn!(%error, "could not ensure object storage bucket (continuing)");
    }

    let state = AppState::new(
        pool,
        JwtState::new(config.jwt.clone()),
        storage,
        config.settings.clone(),
    );
    let app = build_router(state);

    let listener = tokio::net::TcpListener::bind(config.bind_addr).await?;
    tracing::info!(addr = %config.bind_addr, "listening");

    // `ConnectInfo` supplies the peer address the rate limiter keys on when no
    // forwarded header is present (§13).
    axum::serve(
        listener,
        app.into_make_service_with_connect_info::<SocketAddr>(),
    )
    .with_graceful_shutdown(shutdown_signal())
    .await?;

    tracing::info!("onboardkit-api stopped");
    Ok(())
}
