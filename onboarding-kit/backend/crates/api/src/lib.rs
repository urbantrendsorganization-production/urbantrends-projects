//! `onboardkit-api` — Axum HTTP layer: routes, extractors, middleware, `AppError`.
//!
//! The binary (`src/main.rs`) wires configuration, the database pool and this
//! router together. Keeping the router assembly in the library lets integration
//! tests build the app without spawning a process (CLAUDE.md §16).

#![warn(clippy::pedantic)]
#![allow(clippy::module_name_repetitions, clippy::doc_markdown)]

pub mod auth;
pub mod config;
pub mod error;
pub mod routes;
pub mod state;
pub mod telemetry;

use axum::Router;
use tokio::signal;
use tower_http::trace::TraceLayer;

pub use error::{AppError, AppResult};
pub use state::AppState;

/// Build the full application router with all middleware and state attached.
pub fn build_router(state: AppState) -> Router {
    let api_v1 = Router::new().merge(routes::health::router());

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
