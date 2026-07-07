//! Auth + RBAC integration tests against a real Postgres (CLAUDE.md §16).
//!
//! Each `#[sqlx::test]` gets an isolated, migrated database. Requests are driven
//! through the real router via `tower`'s `oneshot`, so the full extractor →
//! handler → repository path is exercised, including RBAC denial cases.

use std::time::Duration;

use axum::Router;
use axum::body::Body;
use axum::http::{Request, StatusCode};
use onboardkit_api::auth::{RequireAgent, RequireReviewer, issue_access_token};
use onboardkit_api::build_router;
use onboardkit_api::config::{JwtConfig, RateLimit, Settings};
use onboardkit_api::state::{AppState, JwtState};
use onboardkit_integrations::{ObjectStore, StorageConfig};
use serde_json::{Value, json};
use sqlx::PgPool;
use tower::ServiceExt;
use uuid::Uuid;

const PASSWORD: &str = "Sup3rSecret!";

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

fn test_settings() -> Settings {
    Settings {
        dev_expose_otp: true,
        terms_version: "v1".to_owned(),
        rate_limit: RateLimit::disabled(),
    }
}

fn app(pool: PgPool) -> Router {
    build_router(AppState::new(
        pool,
        jwt_state(),
        test_storage(),
        test_settings(),
    ))
}

struct Seeded {
    user_id: Uuid,
    tenant_id: Uuid,
    email: String,
}

/// Insert a tenant, branch and one active user with the given role.
async fn seed_user(pool: &PgPool, role: &str) -> Seeded {
    let tenant_id = Uuid::new_v4();
    let branch_id = Uuid::new_v4();
    let user_id = Uuid::new_v4();
    let email = format!("{role}.{user_id}@example.com");
    let hash = onboardkit_integrations::password::hash(PASSWORD).expect("hash");

    sqlx::query("INSERT INTO tenants (id, name) VALUES ($1, $2)")
        .bind(tenant_id)
        .bind("Test Tenant")
        .execute(pool)
        .await
        .expect("insert tenant");
    sqlx::query("INSERT INTO branches (id, tenant_id, name, code) VALUES ($1, $2, $3, $4)")
        .bind(branch_id)
        .bind(tenant_id)
        .bind("Test Branch")
        .bind(&user_id.to_string()[..8])
        .execute(pool)
        .await
        .expect("insert branch");
    sqlx::query(
        "INSERT INTO users (id, tenant_id, branch_id, full_name, phone, email, password_hash, role)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
    )
    .bind(user_id)
    .bind(tenant_id)
    .bind(branch_id)
    .bind("Test User")
    .bind("+254712345678")
    .bind(&email)
    .bind(&hash)
    .bind(role)
    .execute(pool)
    .await
    .expect("insert user");

    Seeded {
        user_id,
        tenant_id,
        email,
    }
}

async fn send(app: &Router, req: Request<Body>) -> (StatusCode, Value) {
    let response = app.clone().oneshot(req).await.expect("router response");
    let status = response.status();
    let bytes = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("read body");
    let value = if bytes.is_empty() {
        Value::Null
    } else {
        serde_json::from_slice(&bytes).unwrap_or(Value::Null)
    };
    (status, value)
}

fn post_json(uri: &str, body: &Value) -> Request<Body> {
    Request::builder()
        .method("POST")
        .uri(uri)
        .header("content-type", "application/json")
        .body(Body::from(serde_json::to_vec(body).unwrap()))
        .unwrap()
}

fn get_auth(uri: &str, bearer: &str) -> Request<Body> {
    Request::builder()
        .method("GET")
        .uri(uri)
        .header("authorization", format!("Bearer {bearer}"))
        .body(Body::empty())
        .unwrap()
}

// ---- Login ---------------------------------------------------------------

#[sqlx::test(migrations = "../../migrations")]
async fn login_succeeds_and_returns_tokens(pool: PgPool) {
    let user = seed_user(&pool, "agent").await;
    let app = app(pool);

    let (status, body) = send(
        &app,
        post_json(
            "/api/v1/auth/login",
            &json!({ "email": user.email, "password": PASSWORD }),
        ),
    )
    .await;

    assert_eq!(status, StatusCode::OK);
    assert!(body["access_token"].as_str().is_some());
    assert!(body["refresh_token"].as_str().is_some());
    assert_eq!(body["role"], "agent");
    assert_eq!(body["user_id"], user.user_id.to_string());
}

#[sqlx::test(migrations = "../../migrations")]
async fn login_with_wrong_password_is_unauthorized(pool: PgPool) {
    let user = seed_user(&pool, "agent").await;
    let app = app(pool);

    let (status, _) = send(
        &app,
        post_json(
            "/api/v1/auth/login",
            &json!({ "email": user.email, "password": "wrong" }),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
}

#[sqlx::test(migrations = "../../migrations")]
async fn login_with_unknown_email_is_unauthorized(pool: PgPool) {
    let app = app(pool);
    let (status, _) = send(
        &app,
        post_json(
            "/api/v1/auth/login",
            &json!({ "email": "nobody@example.com", "password": PASSWORD }),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
}

// ---- /me ------------------------------------------------------------------

#[sqlx::test(migrations = "../../migrations")]
async fn me_requires_authentication(pool: PgPool) {
    let app = app(pool);
    let req = Request::builder()
        .uri("/api/v1/me")
        .body(Body::empty())
        .unwrap();
    let (status, _) = send(&app, req).await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
}

#[sqlx::test(migrations = "../../migrations")]
async fn me_returns_identity_for_valid_token(pool: PgPool) {
    let user = seed_user(&pool, "reviewer").await;
    let app = app(pool);
    let (_, login) = send(
        &app,
        post_json(
            "/api/v1/auth/login",
            &json!({ "email": user.email, "password": PASSWORD }),
        ),
    )
    .await;
    let token = login["access_token"].as_str().unwrap();

    let (status, body) = send(&app, get_auth("/api/v1/me", token)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["role"], "reviewer");
    assert_eq!(body["user_id"], user.user_id.to_string());
    assert_eq!(body["tenant_id"], user.tenant_id.to_string());
}

#[sqlx::test(migrations = "../../migrations")]
async fn garbage_token_is_unauthorized(pool: PgPool) {
    let app = app(pool);
    let (status, _) = send(&app, get_auth("/api/v1/me", "not.a.jwt")).await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
}

// ---- Refresh rotation -----------------------------------------------------

#[sqlx::test(migrations = "../../migrations")]
async fn refresh_rotates_and_rejects_reused_token(pool: PgPool) {
    let user = seed_user(&pool, "agent").await;
    let app = app(pool);

    let (_, login) = send(
        &app,
        post_json(
            "/api/v1/auth/login",
            &json!({ "email": user.email, "password": PASSWORD }),
        ),
    )
    .await;
    let first_refresh = login["refresh_token"].as_str().unwrap().to_owned();

    // First refresh succeeds and returns a new refresh token.
    let (status, refreshed) = send(
        &app,
        post_json(
            "/api/v1/auth/refresh",
            &json!({ "refresh_token": first_refresh }),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let second_refresh = refreshed["refresh_token"].as_str().unwrap().to_owned();
    assert_ne!(first_refresh, second_refresh);

    // Reusing the now-rotated first token is rejected.
    let (status, _) = send(
        &app,
        post_json(
            "/api/v1/auth/refresh",
            &json!({ "refresh_token": first_refresh }),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);

    // The new token still works.
    let (status, _) = send(
        &app,
        post_json(
            "/api/v1/auth/refresh",
            &json!({ "refresh_token": second_refresh }),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
}

#[sqlx::test(migrations = "../../migrations")]
async fn logout_revokes_refresh_token(pool: PgPool) {
    let user = seed_user(&pool, "agent").await;
    let app = app(pool);

    let (_, login) = send(
        &app,
        post_json(
            "/api/v1/auth/login",
            &json!({ "email": user.email, "password": PASSWORD }),
        ),
    )
    .await;
    let refresh = login["refresh_token"].as_str().unwrap().to_owned();

    let (status, _) = send(
        &app,
        post_json("/api/v1/auth/logout", &json!({ "refresh_token": refresh })),
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT);

    // A revoked token can no longer be refreshed.
    let (status, _) = send(
        &app,
        post_json("/api/v1/auth/refresh", &json!({ "refresh_token": refresh })),
    )
    .await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
}

// ---- RBAC -----------------------------------------------------------------

async fn token_for(pool: &PgPool, role: &str) -> String {
    let user = seed_user(pool, role).await;
    let core_role = onboardkit_core::Role::from_db(role).unwrap();
    issue_access_token(&jwt_state(), user.user_id, user.tenant_id, None, core_role)
        .expect("issue")
        .token
}

#[sqlx::test(migrations = "../../migrations")]
async fn admin_overview_allows_admin_only(pool: PgPool) {
    let admin = token_for(&pool, "admin").await;
    let agent = token_for(&pool, "agent").await;
    let reviewer = token_for(&pool, "reviewer").await;
    let app = app(pool);

    let (status, _) = send(&app, get_auth("/api/v1/admin/overview", &admin)).await;
    assert_eq!(status, StatusCode::OK, "admin allowed");

    for (label, token) in [("agent", &agent), ("reviewer", &reviewer)] {
        let (status, _) = send(&app, get_auth("/api/v1/admin/overview", token)).await;
        assert_eq!(status, StatusCode::FORBIDDEN, "{label} must be forbidden");
    }

    // No token at all.
    let req = Request::builder()
        .uri("/api/v1/admin/overview")
        .body(Body::empty())
        .unwrap();
    let (status, _) = send(&app, req).await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
}

/// Exercises the `RequireAgent` / `RequireReviewer` guards directly through a
/// tiny test-only router, since their real endpoints arrive in later phases.
#[sqlx::test(migrations = "../../migrations")]
async fn agent_and_reviewer_guards_scope_correctly(pool: PgPool) {
    use axum::routing::get;

    async fn agent_ok(_: RequireAgent) -> StatusCode {
        StatusCode::OK
    }
    async fn reviewer_ok(_: RequireReviewer) -> StatusCode {
        StatusCode::OK
    }

    let agent = token_for(&pool, "agent").await;
    let reviewer = token_for(&pool, "reviewer").await;

    let guarded: Router = Router::new()
        .route("/agent", get(agent_ok))
        .route("/reviewer", get(reviewer_ok))
        .with_state(AppState::new(
            pool,
            jwt_state(),
            test_storage(),
            test_settings(),
        ));

    // Agent token: allowed on /agent, forbidden on /reviewer.
    let (status, _) = send(&guarded, get_auth("/agent", &agent)).await;
    assert_eq!(status, StatusCode::OK);
    let (status, _) = send(&guarded, get_auth("/reviewer", &agent)).await;
    assert_eq!(status, StatusCode::FORBIDDEN);

    // Reviewer token: the mirror image.
    let (status, _) = send(&guarded, get_auth("/reviewer", &reviewer)).await;
    assert_eq!(status, StatusCode::OK);
    let (status, _) = send(&guarded, get_auth("/agent", &reviewer)).await;
    assert_eq!(status, StatusCode::FORBIDDEN);
}
