//! `onboardkit-api` — Axum HTTP layer: routes, extractors, middleware, `AppError`.
//!
//! The binary (`src/main.rs`) wires configuration, the database pool and this
//! router together. Keeping the router assembly in the library lets integration
//! tests build the app without spawning a process (CLAUDE.md §16).

#![warn(clippy::pedantic)]
#![allow(
    clippy::module_name_repetitions,
    clippy::doc_markdown,
    // TTL constants are intentionally expressed in seconds for direct comparison
    // with the CLAUDE.md §11 limits (PUT ≤ 10 min, GET ≤ 5 min).
    clippy::duration_suboptimal_units
)]

pub mod auth;
pub mod config;
pub mod error;
pub mod openapi;
pub mod otp_store;
pub mod routes;
pub mod state;
pub mod telemetry;

use std::sync::Arc;
use std::time::Duration;

use axum::Router;
use tokio::signal;
use tower_governor::GovernorLayer;
use tower_governor::governor::GovernorConfigBuilder;
use tower_governor::key_extractor::SmartIpKeyExtractor;
use tower_http::trace::TraceLayer;

pub use error::{AppError, AppResult};
pub use state::AppState;

/// Build the full application router with all middleware and state attached.
pub fn build_router(state: AppState) -> Router {
    let rate_limit = state.settings.rate_limit;

    // `/auth/*` and `/otp/*` carry the brute-force / flooding risk (§13), so the
    // IP rate limiter is scoped to just these two route groups. Everything else
    // is already behind auth + RBAC.
    let mut sensitive = Router::new()
        .merge(routes::auth::router())
        .merge(routes::otp::router());
    if rate_limit.enabled && rate_limit.per_minute > 0 && rate_limit.burst > 0 {
        // Replenish one cell every (60_000 / per_minute) ms, up to `burst`
        // capacity. Keyed by SmartIpKeyExtractor: reads X-Forwarded-For /
        // X-Real-Ip behind the reverse proxy, else the ConnectInfo peer address.
        let period = Duration::from_millis(u64::from(60_000 / rate_limit.per_minute.max(1)));
        if let Some(config) = GovernorConfigBuilder::default()
            .period(period)
            .burst_size(rate_limit.burst)
            .key_extractor(SmartIpKeyExtractor)
            .finish()
        {
            sensitive = sensitive.layer(GovernorLayer {
                config: Arc::new(config),
            });
        } else {
            tracing::warn!("invalid rate-limit config; limiter not attached");
        }
    }

    let api_v1 = Router::new()
        .route("/openapi.json", axum::routing::get(openapi::openapi_json))
        .merge(routes::health::router())
        .merge(routes::session::router())
        .merge(routes::admin::router())
        .merge(routes::clients::router())
        .merge(routes::applications::router())
        .merge(routes::documents::router())
        .merge(routes::consent::router())
        .merge(routes::review::router())
        .merge(routes::reports::router())
        .merge(routes::exports::router())
        .merge(sensitive);

    Router::new()
        .nest("/api/v1", api_v1)
        .layer(TraceLayer::new_for_http())
        .with_state(state)
}

/// Resolve when the process receives Ctrl-C or (on Unix) `SIGTERM`. Passed to
/// `axum::serve(...).with_graceful_shutdown(...)`.
pub async fn shutdown_signal() {
    let ctrl_c = async {
        if let Err(error) = signal::ctrl_c().await {
            tracing::error!(%error, "failed to install Ctrl-C handler");
        }
    };

    #[cfg(unix)]
    let terminate = async {
        match signal::unix::signal(signal::unix::SignalKind::terminate()) {
            Ok(mut stream) => {
                stream.recv().await;
            }
            Err(error) => tracing::error!(%error, "failed to install SIGTERM handler"),
        }
    };

    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        () = ctrl_c => {},
        () = terminate => {},
    }

    tracing::info!("shutdown signal received");
}
