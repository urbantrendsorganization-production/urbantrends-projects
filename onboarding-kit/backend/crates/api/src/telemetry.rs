//! `tracing` initialisation: pretty logs in dev, JSON in prod (CLAUDE.md §3).

use tracing_subscriber::{EnvFilter, fmt, prelude::*};

/// Install the global tracing subscriber. Idempotent-safe callers should only
/// call this once at process start.
pub fn init(is_production: bool) {
    let filter = EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| EnvFilter::new("info,sqlx=warn,tower_http=info"));

    let registry = tracing_subscriber::registry().with(filter);
    if is_production {
        registry
            .with(fmt::layer().json().with_current_span(true))
            .init();
    } else {
        registry.with(fmt::layer().pretty()).init();
    }
}
