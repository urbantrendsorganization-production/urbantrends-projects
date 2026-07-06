//! Demo seed (`cargo run -p onboardkit-db --bin seed`).
//!
//! Idempotent: uses deterministic (v5) UUIDs and `ON CONFLICT DO NOTHING`, so it
//! can be run repeatedly. Seeds the "Jubilant Microfinance" tenant (§15) with its
//! branches, a login-ready user for every role, a product catalogue, and ~40
//! onboarding applications spread across every status with a consistent event
//! history, KYC document rows, and client numbers on the approved ones.

use anyhow::Context;
use argon2::Argon2;
use argon2::password_hash::{PasswordHasher, SaltString};
use chrono::{DateTime, Duration, NaiveDate, Utc};
use sqlx::postgres::{PgPool, PgPoolOptions};
use uuid::Uuid;

/// Dev-only shared password for every seeded user. Never used in production.
const DEMO_PASSWORD: &str = "Password123!";
/// Terms version stamped on seeded consents (mirrors `CONSENT_TERMS_VERSION`).
const TERMS_VERSION: &str = "v1";

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
        .max_connections(4)
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

    let products = [
        ("SAV", "Chama Savings Account"),
        ("LOAN", "Biashara Business Loan"),
        ("INS", "Afya Health Cover"),
    ];
    for (code, name) in products {
        sqlx::query!(
            r#"INSERT INTO products (id, tenant_id, code, name, is_active)
               VALUES ($1, $2, $3, $4, TRUE)
               ON CONFLICT (tenant_id, code) DO NOTHING"#,
            product_id(tenant_id, code),
            tenant_id,
            code,
            name,
        )
        .execute(&pool)
        .await
        .with_context(|| format!("seeding product {code}"))?;
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

    let app_count = seed_applications(&pool, tenant_id).await?;

    println!(
        "Seeded tenant 'Jubilant Microfinance': {} branches, {} products, {} users, {} applications.",
        branches.len(),
        products.len(),
        users.len(),
        app_count,
    );
    println!("All demo users share the password: {DEMO_PASSWORD}");
    for user in &users {
        println!("  {:<10} {}", user.role, user.email);
    }

    Ok(())
}

/// Which branch actions an application, and the terminal status it lands in.
struct AppSpec {
    branch: &'static str,
    status: &'static str,
    days_ago: i64,
}

/// Seed ~40 applications across every status with consistent event history,
/// document rows, and (for approved) tenant-scoped client numbers.
async fn seed_applications(pool: &PgPool, tenant_id: Uuid) -> anyhow::Result<usize> {
    // Nakuru has an agent but no reviewer yet, so its applications only reach
    // `draft`/`submitted` (nothing to review them) — realistic branch scoping.
    let mut specs: Vec<AppSpec> = Vec::new();
    let mut push = |branch: &'static str, status: &'static str, count: usize, start_days: i64| {
        for k in 0..count {
            specs.push(AppSpec {
                branch,
                status,
                days_ago: start_days + i64::try_from(k).unwrap_or(0),
            });
        }
    };
    // status              KIL         THI         NAK
    push("KIL", "approved", 6, 30);
    push("THI", "approved", 6, 25);
    push("KIL", "rejected", 2, 22);
    push("THI", "rejected", 2, 20);
    push("KIL", "returned_for_correction", 2, 18);
    push("THI", "returned_for_correction", 2, 16);
    push("KIL", "under_review", 3, 9);
    push("THI", "under_review", 3, 7);
    push("KIL", "submitted", 2, 5);
    push("THI", "submitted", 2, 4);
    push("NAK", "submitted", 4, 6);
    push("KIL", "draft", 1, 3);
    push("THI", "draft", 1, 2);
    push("NAK", "draft", 4, 1);

    let base = Utc::now();
    let mut approved_seq: i32 = 0;

    for (i, spec) in specs.iter().enumerate() {
        let agent = agent_for(tenant_id, spec.branch);
        let reviewer = reviewer_for(tenant_id, spec.branch);
        let branch = branch_id(tenant_id, spec.branch);
        let product = PRODUCT_CODES[i % PRODUCT_CODES.len()];

        let client_id = det(&format!("client:{i}"));
        let app_id = det(&format!("app:{i}"));
        let created_at = base - Duration::days(spec.days_ago);

        let reached_submit = matches!(
            spec.status,
            "submitted" | "under_review" | "approved" | "rejected" | "returned_for_correction"
        );

        // Approved clients get the tenant-scoped human number (JM-00001, ...).
        let client_number = if spec.status == "approved" {
            approved_seq += 1;
            Some(format!("JM-{approved_seq:05}"))
        } else {
            None
        };

        insert_client(
            pool,
            tenant_id,
            client_id,
            i,
            client_number.as_deref(),
            created_at,
        )
        .await?;

        // Timeline of transitions leading to the target status.
        let t_created = created_at;
        let t_submitted = created_at + Duration::hours(3);
        let t_review = t_submitted + Duration::days(1);
        let t_terminal = t_review + Duration::hours(4);

        let (otp_at, consent_at, submitted_at, updated_at) = if reached_submit {
            (
                Some(t_submitted - Duration::minutes(20)),
                Some(t_submitted - Duration::minutes(10)),
                Some(t_submitted),
                if spec.status == "submitted" {
                    t_submitted
                } else if spec.status == "under_review" {
                    t_review
                } else {
                    t_terminal
                },
            )
        } else {
            (None, None, None, t_created)
        };

        insert_application(
            pool,
            tenant_id,
            AppRow {
                id: app_id,
                client_id,
                agent_id: agent,
                branch_id: branch,
                product_code: product,
                status: spec.status,
                otp_at,
                consent_at,
                submitted_at,
                created_at: t_created,
                updated_at,
            },
        )
        .await?;

        // Documents: submitted+ apps have all four processed; drafts are partial.
        let docs: &[(&str, bool)] = if reached_submit {
            &[
                ("id_front", true),
                ("id_back", true),
                ("selfie", true),
                ("address_proof", true),
            ]
        } else {
            &[("id_front", false), ("selfie", false)]
        };
        for (doc_type, processed) in docs {
            insert_document(pool, tenant_id, app_id, doc_type, *processed, created_at).await?;
        }

        // Event history — one row per transition, chronological (§6).
        insert_event(
            pool, tenant_id, app_id, 0, agent, None, "draft", None, t_created,
        )
        .await?;
        if reached_submit {
            insert_event(
                pool,
                tenant_id,
                app_id,
                1,
                agent,
                Some("draft"),
                "submitted",
                None,
                t_submitted,
            )
            .await?;
        }
        if matches!(
            spec.status,
            "under_review" | "approved" | "rejected" | "returned_for_correction"
        ) {
            insert_event(
                pool,
                tenant_id,
                app_id,
                2,
                reviewer,
                Some("submitted"),
                "under_review",
                None,
                t_review,
            )
            .await?;
        }
        match spec.status {
            "approved" => {
                insert_event(
                    pool,
                    tenant_id,
                    app_id,
                    3,
                    reviewer,
                    Some("under_review"),
                    "approved",
                    None,
                    t_terminal,
                )
                .await?;
            }
            "rejected" => {
                let reason = REJECTION_REASONS[i % REJECTION_REASONS.len()];
                insert_event(
                    pool,
                    tenant_id,
                    app_id,
                    3,
                    reviewer,
                    Some("under_review"),
                    "rejected",
                    Some(reason),
                    t_terminal,
                )
                .await?;
            }
            "returned_for_correction" => {
                let notes = RETURN_NOTES[i % RETURN_NOTES.len()];
                insert_event(
                    pool,
                    tenant_id,
                    app_id,
                    3,
                    reviewer,
                    Some("under_review"),
                    "returned_for_correction",
                    Some(notes),
                    t_terminal,
                )
                .await?;
            }
            _ => {}
        }
    }

    Ok(specs.len())
}

/// Flattened application row, to keep the insert call under the arg-count lint.
struct AppRow {
    id: Uuid,
    client_id: Uuid,
    agent_id: Uuid,
    branch_id: Uuid,
    product_code: &'static str,
    status: &'static str,
    otp_at: Option<DateTime<Utc>>,
    consent_at: Option<DateTime<Utc>>,
    submitted_at: Option<DateTime<Utc>>,
    created_at: DateTime<Utc>,
    updated_at: DateTime<Utc>,
}

const PRODUCT_CODES: [&str; 3] = ["SAV", "LOAN", "INS"];

const FIRST_NAMES: [&str; 20] = [
    "Grace", "Peter", "Mary", "John", "Faith", "James", "Joyce", "Samuel", "Lucy", "Daniel",
    "Mercy", "Kevin", "Ann", "Dennis", "Rose", "Victor", "Jane", "Collins", "Susan", "Brian",
];
const LAST_NAMES: [&str; 20] = [
    "Wanjiru",
    "Ochieng",
    "Mutua",
    "Kariuki",
    "Achieng",
    "Kiptoo",
    "Njoroge",
    "Wafula",
    "Chebet",
    "Omondi",
    "Muthoni",
    "Barasa",
    "Wangui",
    "Kirui",
    "Adhiambo",
    "Gitau",
    "Cheruiyot",
    "Onyango",
    "Nyambura",
    "Maina",
];
const ESTATES: [&str; 6] = [
    "Kawangware",
    "Pipeline",
    "Githurai",
    "Section 58",
    "Kaptembwo",
    "Ngara",
];
const REJECTION_REASONS: [&str; 4] = [
    "ID photo blurred and unreadable",
    "Selfie does not match ID document",
    "KRA PIN does not match submitted ID",
    "Proof of address is older than 3 months",
];
const RETURN_NOTES: [&str; 4] = [
    "Please retake the back of the ID — glare obscures the number",
    "Proof of address is unclear, kindly resend a full-page copy",
    "Confirm the next-of-kin phone number, current one is unreachable",
    "Selfie is too dark, retake in better lighting",
];

fn agent_for(tenant_id: Uuid, branch: &str) -> Uuid {
    let email = match branch {
        "KIL" => "agent.kilimani@jubilant.co.ke",
        "THI" => "agent.thika@jubilant.co.ke",
        _ => "agent.nakuru@jubilant.co.ke",
    };
    let _ = tenant_id;
    det(&format!("user:{email}"))
}

fn reviewer_for(tenant_id: Uuid, branch: &str) -> Uuid {
    let email = match branch {
        "THI" => "reviewer.thika@jubilant.co.ke",
        // Nakuru has no reviewer; its apps never reach review, so this is unused.
        _ => "reviewer.kilimani@jubilant.co.ke",
    };
    let _ = tenant_id;
    det(&format!("user:{email}"))
}

async fn insert_client(
    pool: &PgPool,
    tenant_id: Uuid,
    id: Uuid,
    idx: usize,
    client_number: Option<&str>,
    created_at: DateTime<Utc>,
) -> anyhow::Result<()> {
    let first = FIRST_NAMES[idx % FIRST_NAMES.len()];
    let last = LAST_NAMES[(idx * 7) % LAST_NAMES.len()];
    let full_name = format!("{first} {last}");
    let phone = format!("+2547{:08}", 10_000_000 + idx);
    let national_id = format!("{}", 20_000_000 + idx * 137);
    let kra_pin = format!("A{:09}Z", 100_000_000 + idx * 991);
    let dob = NaiveDate::from_ymd_opt(
        1980 + (idx % 20) as i32,
        1 + (idx % 12) as u32,
        1 + (idx % 27) as u32,
    )
    .unwrap_or_else(|| NaiveDate::from_ymd_opt(1990, 1, 1).expect("static date"));
    let address = format!("{}, {}", ESTATES[idx % ESTATES.len()], "Kenya");
    let relationship = ["Spouse", "Parent", "Sibling", "Child"][idx % 4];
    let nok = serde_json::json!({
        "name": format!("{} {}", FIRST_NAMES[(idx + 5) % FIRST_NAMES.len()], last),
        "phone": format!("+2547{:08}", 20_000_000 + idx),
        "relationship": relationship,
    });

    sqlx::query!(
        r#"INSERT INTO clients
             (id, tenant_id, full_name, phone, national_id_number, kra_pin,
              date_of_birth, address, next_of_kin, client_number, created_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
           ON CONFLICT (id) DO NOTHING"#,
        id,
        tenant_id,
        full_name,
        phone,
        national_id,
        kra_pin,
        dob,
        address,
        nok,
        client_number,
        created_at,
    )
    .execute(pool)
    .await
    .context("seeding client")?;
    Ok(())
}

async fn insert_application(pool: &PgPool, tenant_id: Uuid, a: AppRow) -> anyhow::Result<()> {
    sqlx::query!(
        r#"INSERT INTO onboarding_applications
             (id, tenant_id, client_id, agent_id, branch_id, product_code,
              current_status, otp_verified_at, consent_at, consent_terms_version,
              submitted_at, created_at, updated_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
           ON CONFLICT (id) DO NOTHING"#,
        a.id,
        tenant_id,
        a.client_id,
        a.agent_id,
        a.branch_id,
        a.product_code,
        a.status,
        a.otp_at,
        a.consent_at,
        a.consent_at.map(|_| TERMS_VERSION),
        a.submitted_at,
        a.created_at,
        a.updated_at,
    )
    .execute(pool)
    .await
    .context("seeding application")?;
    Ok(())
}

#[allow(clippy::too_many_arguments)]
async fn insert_event(
    pool: &PgPool,
    tenant_id: Uuid,
    app_id: Uuid,
    seq: u8,
    actor: Uuid,
    from_status: Option<&str>,
    to_status: &str,
    reason: Option<&str>,
    created_at: DateTime<Utc>,
) -> anyhow::Result<()> {
    let id = Uuid::new_v5(&app_id, format!("event:{seq}").as_bytes());
    sqlx::query!(
        r#"INSERT INTO application_events
             (id, tenant_id, application_id, actor_user_id, from_status, to_status,
              reason, created_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
           ON CONFLICT (id) DO NOTHING"#,
        id,
        tenant_id,
        app_id,
        actor,
        from_status,
        to_status,
        reason,
        created_at,
    )
    .execute(pool)
    .await
    .context("seeding application event")?;
    Ok(())
}

async fn insert_document(
    pool: &PgPool,
    tenant_id: Uuid,
    app_id: Uuid,
    doc_type: &str,
    processed: bool,
    uploaded_at: DateTime<Utc>,
) -> anyhow::Result<()> {
    let id = Uuid::new_v5(&app_id, format!("doc:{doc_type}").as_bytes());
    let obj = Uuid::new_v5(&id, b"object");
    let (ext, content_type) = if doc_type == "address_proof" {
        ("pdf", "application/pdf")
    } else {
        ("jpg", "image/jpeg")
    };
    let storage_key = format!("tenants/{tenant_id}/applications/{app_id}/{doc_type}/{obj}.{ext}");
    let thumbnail_key = if processed && doc_type != "address_proof" {
        Some(format!(
            "tenants/{tenant_id}/applications/{app_id}/{doc_type}/{obj}.thumb.jpg"
        ))
    } else {
        None
    };
    let original = format!("{doc_type}.{ext}");
    let size: i64 = 240_000 + i64::from(processed) * 10_000;

    sqlx::query!(
        r#"INSERT INTO kyc_documents
             (id, tenant_id, application_id, doc_type, storage_key, original_filename,
              content_type, size_bytes, processed, thumbnail_key, uploaded_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
           ON CONFLICT (id) DO NOTHING"#,
        id,
        tenant_id,
        app_id,
        doc_type,
        storage_key,
        original,
        content_type,
        size,
        processed,
        thumbnail_key,
        uploaded_at,
    )
    .execute(pool)
    .await
    .context("seeding kyc document")?;
    Ok(())
}

/// Deterministic namespaced UUID so re-runs are idempotent.
fn det(name: &str) -> Uuid {
    Uuid::new_v5(&Uuid::NAMESPACE_OID, name.as_bytes())
}

fn branch_id(tenant_id: Uuid, code: &str) -> Uuid {
    Uuid::new_v5(&tenant_id, format!("branch:{code}").as_bytes())
}

fn product_id(tenant_id: Uuid, code: &str) -> Uuid {
    Uuid::new_v5(&tenant_id, format!("product:{code}").as_bytes())
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
