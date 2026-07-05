//! Demo seed (`cargo run -p onboardkit-db --bin seed`).
//!
//! Idempotent: uses deterministic (v5) UUIDs and `ON CONFLICT DO NOTHING`, so it
//! can be run repeatedly. Phase 1 seeds the "Jubilant Microfinance" tenant with
//! its branches and a login-ready user for every role (§15). The full ~40
//! applications with history land in Phase 5.

use anyhow::Context;
use argon2::Argon2;
use argon2::password_hash::{PasswordHasher, SaltString};
use sqlx::postgres::PgPoolOptions;
use uuid::Uuid;

/// Dev-only shared password for every seeded user. Never used in production.
const DEMO_PASSWORD: &str = "Password123!";

struct SeedUser {
    email: &'static str,
    full_name: &'static str,
    role: &'static str,
    branch_code: Option<&'static str>,
    phone: &'static str,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let _ = dotenvy::dotenv();
    let database_url = std::env::var("DATABASE_URL").context("DATABASE_URL must be set")?;

    let pool = PgPoolOptions::new()
        .max_connections(2)
        .connect(&database_url)
        .await
        .context("connecting to the database")?;

    onboardkit_db::run_migrations(&pool)
        .await
        .context("running migrations before seeding")?;

    let tenant_id = det("tenant:jubilant");
    sqlx::query!(
        r#"INSERT INTO tenants (id, name) VALUES ($1, $2)
           ON CONFLICT (id) DO NOTHING"#,
        tenant_id,
        "Jubilant Microfinance",
    )
    .execute(&pool)
    .await
    .context("seeding tenant")?;

    let branches = [("KIL", "Kilimani"), ("THI", "Thika"), ("NAK", "Nakuru")];
    for (code, name) in branches {
        sqlx::query!(
            r#"INSERT INTO branches (id, tenant_id, name, code) VALUES ($1, $2, $3, $4)
               ON CONFLICT (id) DO NOTHING"#,
            branch_id(tenant_id, code),
            tenant_id,
            name,
            code,
        )
        .execute(&pool)
        .await
        .with_context(|| format!("seeding branch {code}"))?;
    }

    let users = [
        SeedUser {
            email: "admin@jubilant.co.ke",
            full_name: "Amina Otieno",
            role: "admin",
            branch_code: None,
            phone: "+254700000001",
        },
        SeedUser {
            email: "reviewer.kilimani@jubilant.co.ke",
            full_name: "Brian Mwangi",
            role: "reviewer",
            branch_code: Some("KIL"),
            phone: "+254700000002",
        },
        SeedUser {
            email: "reviewer.thika@jubilant.co.ke",
            full_name: "Cynthia Wanjiru",
            role: "reviewer",
            branch_code: Some("THI"),
            phone: "+254700000003",
        },
        SeedUser {
            email: "agent.kilimani@jubilant.co.ke",
            full_name: "David Kamau",
            role: "agent",
            branch_code: Some("KIL"),
            phone: "+254700000004",
        },
        SeedUser {
            email: "agent.thika@jubilant.co.ke",
            full_name: "Esther Njeri",
            role: "agent",
            branch_code: Some("THI"),
            phone: "+254700000005",
        },
        SeedUser {
            email: "agent.nakuru@jubilant.co.ke",
            full_name: "Felix Kiptoo",
            role: "agent",
            branch_code: Some("NAK"),
            phone: "+254700000006",
        },
    ];

    for user in &users {
        let password_hash = hash_password(DEMO_PASSWORD)?;
        let branch = user.branch_code.map(|code| branch_id(tenant_id, code));
        sqlx::query!(
            r#"INSERT INTO users
                 (id, tenant_id, branch_id, full_name, phone, email, password_hash, role)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
               ON CONFLICT (email) DO NOTHING"#,
            det(&format!("user:{}", user.email)),
            tenant_id,
            branch,
            user.full_name,
            user.phone,
            user.email,
            password_hash,
            user.role,
        )
        .execute(&pool)
        .await
        .with_context(|| format!("seeding user {}", user.email))?;
    }

    println!(
        "Seeded tenant 'Jubilant Microfinance' with {} branches and {} users.",
        branches.len(),
        users.len()
    );
    println!("All demo users share the password: {DEMO_PASSWORD}");
    for user in &users {
        println!("  {:<10} {}", user.role, user.email);
    }

    Ok(())
}

/// Deterministic namespaced UUID so re-runs are idempotent.
fn det(name: &str) -> Uuid {
    Uuid::new_v5(&Uuid::NAMESPACE_OID, name.as_bytes())
}

fn branch_id(tenant_id: Uuid, code: &str) -> Uuid {
    Uuid::new_v5(&tenant_id, format!("branch:{code}").as_bytes())
}

/// argon2id hash, mirroring `onboardkit_integrations::password::hash` (which the
/// db crate cannot depend on — §2). Produces interoperable PHC strings.
fn hash_password(password: &str) -> anyhow::Result<String> {
    let mut salt_bytes = [0u8; 16];
    getrandom::fill(&mut salt_bytes).map_err(|e| anyhow::anyhow!("entropy: {e}"))?;
    let salt = SaltString::encode_b64(&salt_bytes).map_err(|e| anyhow::anyhow!("salt: {e}"))?;
    let hashed = Argon2::default()
        .hash_password(password.as_bytes(), &salt)
        .map_err(|e| anyhow::anyhow!("hash: {e}"))?;
    Ok(hashed.to_string())
}
