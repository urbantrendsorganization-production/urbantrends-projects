//! Integration tests for the Phase 2 application endpoints (§7). These exercise
//! the non-storage paths (create/list/detail/submit + RBAC); the upload/OTP
//! flows need MinIO and are covered by the local docker-compose smoke test.

use std::time::Duration;

use axum::Router;
use axum::body::Body;
use axum::http::{Request, StatusCode};
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

fn app(pool: PgPool) -> Router {
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
        rate_limit: RateLimit::disabled(),
    };
    build_router(AppState::new(pool, jwt_state(), storage, settings))
}

struct Seeded {
    tenant_id: Uuid,
    branch_id: Uuid,
    email: String,
}

/// Insert a tenant + branch (once) and a user with the given role in that branch.
async fn seed_user(pool: &PgPool, tenant_id: Uuid, branch_id: Uuid, role: &str) -> Seeded {
    let user_id = Uuid::new_v4();
    let email = format!("{role}.{user_id}@example.com");
    let hash = onboardkit_integrations::password::hash(PASSWORD).expect("hash");

    sqlx::query("INSERT INTO tenants (id, name) VALUES ($1, $2) ON CONFLICT DO NOTHING")
        .bind(tenant_id)
        .bind("Test Tenant")
        .execute(pool)
        .await
        .expect("tenant");
    sqlx::query(
        "INSERT INTO branches (id, tenant_id, name, code) VALUES ($1, $2, $3, $4)
         ON CONFLICT DO NOTHING",
    )
    .bind(branch_id)
    .bind(tenant_id)
    .bind("Kilimani")
    .bind(&branch_id.to_string()[..8])
    .execute(pool)
    .await
    .expect("branch");
    sqlx::query(
        "INSERT INTO users (id, tenant_id, branch_id, full_name, phone, email, password_hash, role)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
    )
    .bind(user_id)
    .bind(tenant_id)
    .bind(branch_id)
    .bind("Test User")
    .bind(format!("+2547{:08}", rand_digits()))
    .bind(&email)
    .bind(&hash)
    .bind(role)
    .execute(pool)
    .await
    .expect("user");

    Seeded {
        tenant_id,
        branch_id,
        email,
    }
}

fn rand_digits() -> u32 {
    // Cheap unique-ish suffix so seeded phone numbers never collide.
    u32::try_from(Uuid::new_v4().as_u128() % 100_000_000).unwrap_or(0)
}

async fn send(app: &Router, req: Request<Body>) -> (StatusCode, Value) {
    let response = app.clone().oneshot(req).await.expect("response");
    let status = response.status();
    let bytes = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("body");
    let value = if bytes.is_empty() {
        Value::Null
    } else {
        serde_json::from_slice(&bytes).unwrap_or(Value::Null)
    };
    (status, value)
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

async fn login(app: &Router, email: &str) -> String {
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
    assert_eq!(status, StatusCode::OK, "login failed: {body}");
    body["access_token"].as_str().unwrap().to_owned()
}

#[sqlx::test(migrations = "../../migrations")]
async fn agent_creates_client_application_and_sees_it_in_queue(pool: PgPool) {
    let tenant = Uuid::new_v4();
    let branch = Uuid::new_v4();
    let agent = seed_user(&pool, tenant, branch, "agent").await;
    let app = app(pool);
    let token = login(&app, &agent.email).await;

    let (status, client) = send(
        &app,
        post(
            "/api/v1/clients",
            &token,
            &json!({ "full_name": "Jane Wanjiru" }),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{client}");
    let client_id = client["id"].as_str().unwrap();

    let (status, appn) = send(
        &app,
        post(
            "/api/v1/applications",
            &token,
            &json!({ "client_id": client_id, "product_code": "SAVINGS" }),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{appn}");
    assert_eq!(appn["status"], "draft");

    let (status, list) = send(&app, get("/api/v1/applications", &token)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(list["meta"]["total"], 1);
    assert_eq!(list["data"][0]["client_id"], client_id);
}

#[sqlx::test(migrations = "../../migrations")]
async fn submit_incomplete_application_is_rejected(pool: PgPool) {
    let tenant = Uuid::new_v4();
    let branch = Uuid::new_v4();
    let agent = seed_user(&pool, tenant, branch, "agent").await;
    let app = app(pool);
    let token = login(&app, &agent.email).await;

    let (_, client) = send(
        &app,
        post(
            "/api/v1/clients",
            &token,
            &json!({ "full_name": "Peter Otieno" }),
        ),
    )
    .await;
    let (_, appn) = send(
        &app,
        post(
            "/api/v1/applications",
            &token,
            &json!({ "client_id": client["id"], "product_code": "SAVINGS" }),
        ),
    )
    .await;

    let id = appn["id"].as_str().unwrap();
    let (status, body) = send(
        &app,
        post(
            &format!("/api/v1/applications/{id}/submit"),
            &token,
            &json!({}),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
    assert_eq!(body["error"]["code"], "validation_error");
}

/// Insert a client with a phone and a `submitted` application owned by a fresh
/// agent in `branch`. Returns the application id.
async fn seed_submitted_application(pool: &PgPool, tenant_id: Uuid, branch_id: Uuid) -> Uuid {
    sqlx::query("INSERT INTO tenants (id, name) VALUES ($1, 'Test Tenant') ON CONFLICT DO NOTHING")
        .bind(tenant_id)
        .execute(pool)
        .await
        .expect("tenant");
    sqlx::query(
        "INSERT INTO branches (id, tenant_id, name, code) VALUES ($1, $2, 'Thika', $3)
         ON CONFLICT DO NOTHING",
    )
    .bind(branch_id)
    .bind(tenant_id)
    .bind(&branch_id.to_string()[..8])
    .execute(pool)
    .await
    .expect("branch");

    let agent_id = Uuid::new_v4();
    sqlx::query(
        "INSERT INTO users (id, tenant_id, branch_id, full_name, phone, email, password_hash, role)
         VALUES ($1, $2, $3, 'Agent', $4, $5, 'x', 'agent')",
    )
    .bind(agent_id)
    .bind(tenant_id)
    .bind(branch_id)
    .bind(format!("+2547{:08}", rand_digits()))
    .bind(format!("agent.{agent_id}@example.com"))
    .execute(pool)
    .await
    .expect("agent");

    let client_id = Uuid::new_v4();
    sqlx::query("INSERT INTO clients (id, tenant_id, full_name, phone) VALUES ($1, $2, $3, $4)")
        .bind(client_id)
        .bind(tenant_id)
        .bind("Grace Njeri")
        .bind(format!("+2547{:08}", rand_digits()))
        .execute(pool)
        .await
        .expect("client");

    let app_id = Uuid::new_v4();
    sqlx::query(
        "INSERT INTO onboarding_applications
           (id, tenant_id, client_id, agent_id, branch_id, product_code, current_status, submitted_at)
         VALUES ($1, $2, $3, $4, $5, 'SAVINGS', 'submitted', now())",
    )
    .bind(app_id)
    .bind(tenant_id)
    .bind(client_id)
    .bind(agent_id)
    .bind(branch_id)
    .execute(pool)
    .await
    .expect("application");
    app_id
}

#[sqlx::test(migrations = "../../migrations")]
async fn reviewer_starts_review_then_approves_and_assigns_client_number(pool: PgPool) {
    let tenant = Uuid::new_v4();
    let branch = Uuid::new_v4();
    let reviewer = seed_user(&pool, tenant, branch, "reviewer").await;
    let app_id = seed_submitted_application(&pool, tenant, branch).await;
    let app = app(pool);
    let token = login(&app, &reviewer.email).await;

    let uri = format!("/api/v1/applications/{app_id}/review");
    let (status, body) = send(
        &app,
        post(&uri, &token, &json!({ "action": "start_review" })),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["status"], "under_review");

    let (status, body) = send(&app, post(&uri, &token, &json!({ "action": "approve" }))).await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["status"], "approved");

    // The client now has a tenant-scoped number ("Test Tenant" -> "TT-00001").
    let (status, detail) = send(&app, get(&format!("/api/v1/applications/{app_id}"), &token)).await;
    assert_eq!(status, StatusCode::OK);
    let number = detail["client"]["client_number"].as_str().unwrap();
    assert!(number.starts_with("TT-"), "unexpected number {number}");
}

#[sqlx::test(migrations = "../../migrations")]
async fn reject_without_reason_is_rejected(pool: PgPool) {
    let tenant = Uuid::new_v4();
    let branch = Uuid::new_v4();
    let reviewer = seed_user(&pool, tenant, branch, "reviewer").await;
    let app_id = seed_submitted_application(&pool, tenant, branch).await;
    let app = app(pool);
    let token = login(&app, &reviewer.email).await;

    let uri = format!("/api/v1/applications/{app_id}/review");
    // Move to under_review first (reject is only valid from there).
    send(
        &app,
        post(&uri, &token, &json!({ "action": "start_review" })),
    )
    .await;
    let (status, body) = send(&app, post(&uri, &token, &json!({ "action": "reject" }))).await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
}

#[sqlx::test(migrations = "../../migrations")]
async fn reviewer_cannot_review_another_branch(pool: PgPool) {
    let tenant = Uuid::new_v4();
    let branch_a = Uuid::new_v4();
    let branch_b = Uuid::new_v4();
    // Reviewer belongs to branch B; the application is in branch A.
    let reviewer = seed_user(&pool, tenant, branch_b, "reviewer").await;
    let app_id = seed_submitted_application(&pool, tenant, branch_a).await;
    let app = app(pool);
    let token = login(&app, &reviewer.email).await;

    let (status, _) = send(
        &app,
        post(
            &format!("/api/v1/applications/{app_id}/review"),
            &token,
            &json!({ "action": "start_review" }),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
}

#[sqlx::test(migrations = "../../migrations")]
async fn reviewer_cannot_create_clients(pool: PgPool) {
    let tenant = Uuid::new_v4();
    let branch = Uuid::new_v4();
    let reviewer = seed_user(&pool, tenant, branch, "reviewer").await;
    let app = app(pool);
    let token = login(&app, &reviewer.email).await;

    let (status, _) = send(
        &app,
        post("/api/v1/clients", &token, &json!({ "full_name": "X" })),
    )
    .await;
    assert_eq!(status, StatusCode::FORBIDDEN);
}

#[sqlx::test(migrations = "../../migrations")]
async fn agent_cannot_view_another_agents_application(pool: PgPool) {
    let tenant = Uuid::new_v4();
    let branch = Uuid::new_v4();
    let agent_a = seed_user(&pool, tenant, branch, "agent").await;
    let agent_b = seed_user(&pool, agent_a.tenant_id, agent_a.branch_id, "agent").await;
    let app = app(pool);
    let token_a = login(&app, &agent_a.email).await;
    let token_b = login(&app, &agent_b.email).await;

    let (_, client) = send(
        &app,
        post(
            "/api/v1/clients",
            &token_a,
            &json!({ "full_name": "Owned" }),
        ),
    )
    .await;
    let (_, appn) = send(
        &app,
        post(
            "/api/v1/applications",
            &token_a,
            &json!({ "client_id": client["id"], "product_code": "SAVINGS" }),
        ),
    )
    .await;
    let id = appn["id"].as_str().unwrap();

    // Agent B must not see agent A's application — 404, never 403 (no leak).
    let (status, _) = send(&app, get(&format!("/api/v1/applications/{id}"), &token_b)).await;
    assert_eq!(status, StatusCode::NOT_FOUND);

    // And it must not appear in agent B's queue.
    let (_, list) = send(&app, get("/api/v1/applications", &token_b)).await;
    assert_eq!(list["meta"]["total"], 0);
}
