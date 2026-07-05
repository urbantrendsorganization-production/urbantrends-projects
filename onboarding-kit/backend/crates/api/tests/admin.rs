//! Integration tests for the Phase 4 admin CRUD, reports, and export endpoints.

use std::time::Duration;

use axum::Router;
use axum::body::Body;
use axum::http::{Request, StatusCode};
use onboardkit_api::build_router;
use onboardkit_api::config::{JwtConfig, Settings};
use onboardkit_api::state::{AppState, JwtState};
use onboardkit_integrations::{ObjectStore, StorageConfig};
use serde_json::{Value, json};
use sqlx::PgPool;
use tower::ServiceExt;
use uuid::Uuid;

const PASSWORD: &str = "Sup3rSecret!";

fn app(pool: PgPool) -> Router {
    let jwt = JwtState::new(JwtConfig {
        secret: "test-secret-that-is-at-least-32-bytes!!".to_owned(),
        access_ttl: Duration::from_secs(900),
        refresh_ttl: Duration::from_secs(1_209_600),
    });
    let storage = ObjectStore::new(&StorageConfig {
        endpoint: "http://localhost:9000".to_owned(),
        region: "us-east-1".to_owned(),
        bucket: "test-bucket".to_owned(),
        access_key_id: "test".to_owned(),
        secret_access_key: "test".to_owned(),
        force_path_style: true,
    });
    let settings = Settings {
        dev_expose_otp: true,
        terms_version: "v1".to_owned(),
    };
    build_router(AppState::new(pool, jwt, storage, settings))
}

/// Seed a tenant + an admin user; returns the admin's email.
async fn seed_admin(pool: &PgPool) -> String {
    let tenant = Uuid::new_v4();
    let user = Uuid::new_v4();
    let email = format!("admin.{user}@example.com");
    let hash = onboardkit_integrations::password::hash(PASSWORD).expect("hash");
    sqlx::query("INSERT INTO tenants (id, name) VALUES ($1, 'Jubilant Microfinance')")
        .bind(tenant)
        .execute(pool)
        .await
        .expect("tenant");
    sqlx::query(
        "INSERT INTO users (id, tenant_id, full_name, phone, email, password_hash, role)
         VALUES ($1, $2, 'Admin', '+254712345678', $3, $4, 'admin')",
    )
    .bind(user)
    .bind(tenant)
    .bind(&email)
    .bind(&hash)
    .execute(pool)
    .await
    .expect("admin");
    email
}

async fn send(app: &Router, req: Request<Body>) -> (StatusCode, Value) {
    let response = app.clone().oneshot(req).await.expect("response");
    let status = response.status();
    let bytes = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("body");
    let value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
    (status, value)
}

async fn raw(app: &Router, req: Request<Body>) -> (StatusCode, String, Vec<u8>) {
    let response = app.clone().oneshot(req).await.expect("response");
    let status = response.status();
    let ct = response
        .headers()
        .get("content-type")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_owned();
    let bytes = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("body")
        .to_vec();
    (status, ct, bytes)
}

fn post(uri: &str, token: &str, body: &Value) -> Request<Body> {
    Request::builder()
        .method("POST")
        .uri(uri)
        .header("content-type", "application/json")
        .header("authorization", format!("Bearer {token}"))
        .body(Body::from(serde_json::to_vec(body).unwrap()))
        .unwrap()
}

fn get(uri: &str, token: &str) -> Request<Body> {
    Request::builder()
        .method("GET")
        .uri(uri)
        .header("authorization", format!("Bearer {token}"))
        .body(Body::empty())
        .unwrap()
}

async fn admin_token(app: &Router, email: &str) -> String {
    let (status, body) = send(
        app,
        Request::builder()
            .method("POST")
            .uri("/api/v1/auth/login")
            .header("content-type", "application/json")
            .body(Body::from(
                serde_json::to_vec(&json!({ "email": email, "password": PASSWORD })).unwrap(),
            ))
            .unwrap(),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    body["access_token"].as_str().unwrap().to_owned()
}

#[sqlx::test(migrations = "../../migrations")]
async fn admin_can_crud_branches_products_and_users(pool: PgPool) {
    let email = seed_admin(&pool).await;
    let app = app(pool);
    let token = admin_token(&app, &email).await;

    // Branch
    let (status, branch) = send(
        &app,
        post(
            "/api/v1/branches",
            &token,
            &json!({ "name": "Kilimani", "code": "KLM" }),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{branch}");
    let branch_id = branch["id"].as_str().unwrap();

    // Duplicate code -> 409
    let (status, _) = send(
        &app,
        post(
            "/api/v1/branches",
            &token,
            &json!({ "name": "Dup", "code": "KLM" }),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT);

    // Product
    let (status, _) = send(
        &app,
        post(
            "/api/v1/products",
            &token,
            &json!({ "code": "SAVINGS", "name": "Savings Account" }),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED);

    // User (agent) in the branch
    let (status, u) = send(
        &app,
        post(
            "/api/v1/users",
            &token,
            &json!({
                "branch_id": branch_id,
                "full_name": "New Agent",
                "phone": "0712000111",
                "email": "new.agent@jubilant.co.ke",
                "password": "Password123!",
                "role": "agent"
            }),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{u}");
    assert_eq!(u["role"], "agent");

    // Lists reflect the creations
    let (_, users) = send(&app, get("/api/v1/users", &token)).await;
    assert!(users.as_array().unwrap().len() >= 2); // admin + new agent
}

#[sqlx::test(migrations = "../../migrations")]
async fn reports_summary_and_export_are_admin_only(pool: PgPool) {
    let email = seed_admin(&pool).await;
    let app = app(pool);
    let token = admin_token(&app, &email).await;

    let (status, summary) = send(&app, get("/api/v1/reports/summary", &token)).await;
    assert_eq!(status, StatusCode::OK, "{summary}");
    assert!(summary["per_agent"].is_array());
    assert!(summary["rejection_reasons"].is_array());

    // CSV export returns a CSV attachment with the header row.
    let (status, ct, bytes) = raw(
        &app,
        get("/api/v1/exports/approved-clients?format=csv", &token),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert!(ct.contains("text/csv"), "content-type was {ct}");
    let text = String::from_utf8(bytes).unwrap();
    assert!(
        text.starts_with("Client Number,Full Name"),
        "csv header: {text:?}"
    );

    // XLSX export returns a spreadsheet (ZIP magic bytes PK\x03\x04).
    let (status, ct, bytes) = raw(
        &app,
        get("/api/v1/exports/approved-clients?format=xlsx", &token),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert!(ct.contains("spreadsheetml"), "content-type was {ct}");
    assert_eq!(&bytes[..2], b"PK");
}

#[sqlx::test(migrations = "../../migrations")]
async fn non_admin_cannot_reach_admin_endpoints(pool: PgPool) {
    // Seed an agent instead of an admin.
    let tenant = Uuid::new_v4();
    let branch = Uuid::new_v4();
    let user = Uuid::new_v4();
    let email = format!("agent.{user}@example.com");
    let hash = onboardkit_integrations::password::hash(PASSWORD).expect("hash");
    sqlx::query("INSERT INTO tenants (id, name) VALUES ($1, 'T')")
        .bind(tenant)
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query("INSERT INTO branches (id, tenant_id, name, code) VALUES ($1, $2, 'B', 'B1')")
        .bind(branch)
        .bind(tenant)
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query(
        "INSERT INTO users (id, tenant_id, branch_id, full_name, phone, email, password_hash, role)
         VALUES ($1, $2, $3, 'A', '+254712345678', $4, $5, 'agent')",
    )
    .bind(user)
    .bind(tenant)
    .bind(branch)
    .bind(&email)
    .bind(&hash)
    .execute(&pool)
    .await
    .unwrap();

    let app = app(pool);
    let token = admin_token(&app, &email).await;
    for uri in [
        "/api/v1/branches",
        "/api/v1/users",
        "/api/v1/reports/summary",
    ] {
        let (status, _) = send(&app, get(uri, &token)).await;
        assert_eq!(status, StatusCode::FORBIDDEN, "{uri} should be admin-only");
    }
}
