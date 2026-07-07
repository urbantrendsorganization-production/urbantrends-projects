//! Rate-limiting integration tests (CLAUDE.md §13). Drives the real router with
//! the governor layer enabled and asserts per-IP throttling on `/auth/*`. The
//! limiter runs ahead of the handler, so an otherwise-401 login still counts.

use std::time::Duration;

use axum::Router;
use axum::body::Body;
use axum::http::{Request, StatusCode};
use onboardkit_api::build_router;
use onboardkit_api::config::{JwtConfig, RateLimit, Settings};
use onboardkit_api::state::{AppState, JwtState};
use onboardkit_integrations::{ObjectStore, StorageConfig};
use sqlx::PgPool;
use tower::ServiceExt;

fn jwt_state() -> JwtState {
    JwtState::new(JwtConfig {
        secret: "test-secret-that-is-at-least-32-bytes!!".to_owned(),
        access_ttl: Duration::from_secs(900),
        refresh_ttl: Duration::from_secs(1_209_600),
    })
}

fn test_storage() -> ObjectStore {
    ObjectStore::new(&StorageConfig {
        endpoint: "http://localhost:9000".to_owned(),
        region: "us-east-1".to_owned(),
        bucket: "test-bucket".to_owned(),
        access_key_id: "test".to_owned(),
        secret_access_key: "test".to_owned(),
        force_path_style: true,
    })
}

/// Router with rate limiting on: burst 1, so the second request from an IP in
/// the same window is rejected. Keeps the test deterministic (no timing race).
fn app(pool: PgPool) -> Router {
    let settings = Settings {
        dev_expose_otp: true,
        terms_version: "v1".to_owned(),
        rate_limit: RateLimit {
            enabled: true,
            per_minute: 1,
            burst: 1,
        },
    };
    build_router(AppState::new(pool, jwt_state(), test_storage(), settings))
}

/// A login POST tagged with a client IP via `X-Real-Ip` (which
/// `SmartIpKeyExtractor` honours), so no `ConnectInfo` is needed under `oneshot`.
fn login_from(ip: &str) -> Request<Body> {
    Request::builder()
        .method("POST")
        .uri("/api/v1/auth/login")
        .header("content-type", "application/json")
        .header("x-real-ip", ip)
        .body(Body::from(
            r#"{"email":"nobody@example.com","password":"wrong"}"#,
        ))
        .expect("build request")
}

async fn status(app: &Router, req: Request<Body>) -> StatusCode {
    app.clone()
        .oneshot(req)
        .await
        .expect("router response")
        .status()
}

#[sqlx::test(migrations = "../../migrations")]
async fn second_request_from_same_ip_is_throttled(pool: PgPool) {
    let app = app(pool);

    // First request from IP A passes the limiter (handler answers 401).
    let first = status(&app, login_from("9.9.9.9")).await;
    assert_ne!(
        first,
        StatusCode::TOO_MANY_REQUESTS,
        "first should not be limited"
    );
    assert_eq!(first, StatusCode::UNAUTHORIZED);

    // Second request from the same IP, same window → 429.
    let second = status(&app, login_from("9.9.9.9")).await;
    assert_eq!(second, StatusCode::TOO_MANY_REQUESTS);
}

#[sqlx::test(migrations = "../../migrations")]
async fn limit_is_per_ip(pool: PgPool) {
    let app = app(pool);

    // Exhaust IP A's single cell.
    let _ = status(&app, login_from("10.0.0.1")).await;
    assert_eq!(
        status(&app, login_from("10.0.0.1")).await,
        StatusCode::TOO_MANY_REQUESTS
    );

    // A different IP has its own bucket and is not affected.
    assert_eq!(
        status(&app, login_from("10.0.0.2")).await,
        StatusCode::UNAUTHORIZED
    );
}
