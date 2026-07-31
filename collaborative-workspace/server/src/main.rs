//! Collaborative workspace sync server.
//!
//! Phase 1: a bare y-sync relay. Terminates WebSockets, groups peers into rooms, and keeps
//! an authoritative Yrs replica per room so late joiners converge. No persistence, no auth,
//! no Redis fan-out — those are later phases.

mod sync;
mod ws;

use std::net::SocketAddr;

use axum::Router;
use axum::routing::get;
use tracing_subscriber::EnvFilter;

use sync::Rooms;

const DEFAULT_PORT: u16 = 4000;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")),
        )
        .init();

    let port = match std::env::var("PORT") {
        Ok(value) => value.parse::<u16>()?,
        Err(_) => DEFAULT_PORT,
    };
    let addr = SocketAddr::from(([127, 0, 0, 1], port));

    let app = Router::new()
        .route("/healthz", get(|| async { "ok" }))
        .route("/ws/{room}", get(ws::upgrade))
        .with_state(Rooms::new());

    let listener = tokio::net::TcpListener::bind(addr).await?;
    tracing::info!("sync relay listening on ws://{addr}/ws/{{room}}");

    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await?;

    Ok(())
}

async fn shutdown_signal() {
    if let Err(err) = tokio::signal::ctrl_c().await {
        tracing::error!(error = %err, "failed to listen for shutdown signal");
    }
}
