//! Application repository. Tenant-scoped (§4).
//!
//! `current_status` is stored as TEXT and mapped to [`StatusKind`] here, since
//! `core` cannot derive `sqlx::Type` (§3).

use chrono::{DateTime, Utc};
use onboardkit_core::StatusKind;
use sqlx::PgExecutor;
use sqlx::postgres::PgPool;
use uuid::Uuid;

use crate::models::Application;

/// What a new draft needs.
#[derive(Debug, Clone)]
pub struct NewApplication {
    pub client_id: Uuid,
    pub agent_id: Uuid,
    pub branch_id: Uuid,
    pub product_code: String,
}

/// Filters for the role-scoped queue (§7).
#[derive(Debug, Default, Clone)]
pub struct ApplicationFilter {
    pub agent_id: Option<Uuid>,
    pub branch_id: Option<Uuid>,
    pub status: Option<StatusKind>,
    /// Hide `draft` applications — reviewers never see another actor's drafts (§7).
    pub exclude_draft: bool,
}

fn decode_error(err: impl std::error::Error + Send + Sync + 'static) -> sqlx::Error {
    sqlx::Error::Decode(Box::new(err))
}

/// Create a draft application and its initial `-> draft` event atomically (§6).
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn create_draft(
    pool: &PgPool,
    tenant_id: Uuid,
    new: &NewApplication,
) -> Result<Application, sqlx::Error> {
    let mut tx = pool.begin().await?;

    let row = sqlx::query!(
        r#"INSERT INTO onboarding_applications
             (tenant_id, client_id, agent_id, branch_id, product_code)
           VALUES ($1, $2, $3, $4, $5)
           RETURNING id, tenant_id, client_id, agent_id, branch_id, product_code,
                     current_status, otp_verified_at, consent_at, consent_terms_version,
                     submitted_at, created_at, updated_at"#,
        tenant_id,
        new.client_id,
        new.agent_id,
        new.branch_id,
        new.product_code,
    )
    .fetch_one(&mut *tx)
    .await?;

    sqlx::query!(
        r#"INSERT INTO application_events
             (tenant_id, application_id, actor_user_id, from_status, to_status)
           VALUES ($1, $2, $3, NULL, 'draft')"#,
        tenant_id,
        row.id,
        new.agent_id,
    )
    .execute(&mut *tx)
    .await?;

    tx.commit().await?;

    Ok(Application {
        id: row.id,
        tenant_id: row.tenant_id,
        client_id: row.client_id,
        agent_id: row.agent_id,
        branch_id: row.branch_id,
        product_code: row.product_code,
        current_status: StatusKind::from_db(&row.current_status).map_err(decode_error)?,
        otp_verified_at: row.otp_verified_at,
        consent_at: row.consent_at,
        consent_terms_version: row.consent_terms_version,
        submitted_at: row.submitted_at,
        created_at: row.created_at,
        updated_at: row.updated_at,
    })
}

/// Load an application by id within a tenant.
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn get(
    exec: impl PgExecutor<'_>,
    tenant_id: Uuid,
    id: Uuid,
) -> Result<Option<Application>, sqlx::Error> {
    let row = sqlx::query!(
        r#"SELECT id, tenant_id, client_id, agent_id, branch_id, product_code,
                  current_status, otp_verified_at, consent_at, consent_terms_version,
                  submitted_at, created_at, updated_at
           FROM onboarding_applications
           WHERE id = $1 AND tenant_id = $2"#,
        id,
        tenant_id,
    )
    .fetch_optional(exec)
    .await?;

    match row {
        None => Ok(None),
        Some(r) => Ok(Some(Application {
            id: r.id,
            tenant_id: r.tenant_id,
            client_id: r.client_id,
            agent_id: r.agent_id,
            branch_id: r.branch_id,
            product_code: r.product_code,
            current_status: StatusKind::from_db(&r.current_status).map_err(decode_error)?,
            otp_verified_at: r.otp_verified_at,
            consent_at: r.consent_at,
            consent_terms_version: r.consent_terms_version,
            submitted_at: r.submitted_at,
            created_at: r.created_at,
            updated_at: r.updated_at,
        })),
    }
}

/// List applications for a tenant with optional filters, newest first.
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn list(
    exec: impl PgExecutor<'_>,
    tenant_id: Uuid,
    filter: &ApplicationFilter,
    limit: i64,
    offset: i64,
) -> Result<Vec<Application>, sqlx::Error> {
    let status = filter.status.map(|s| s.as_str().to_owned());
    let rows = sqlx::query!(
        r#"SELECT id, tenant_id, client_id, agent_id, branch_id, product_code,
                  current_status, otp_verified_at, consent_at, consent_terms_version,
                  submitted_at, created_at, updated_at
           FROM onboarding_applications
           WHERE tenant_id = $1
             AND ($2::uuid IS NULL OR agent_id = $2)
             AND ($3::uuid IS NULL OR branch_id = $3)
             AND ($4::text IS NULL OR current_status = $4)
             AND (NOT $5::bool OR current_status <> 'draft')
           ORDER BY created_at DESC
           LIMIT $6 OFFSET $7"#,
        tenant_id,
        filter.agent_id,
        filter.branch_id,
        status,
        filter.exclude_draft,
        limit,
        offset,
    )
    .fetch_all(exec)
    .await?;

    rows.into_iter()
        .map(|r| {
            Ok(Application {
                id: r.id,
                tenant_id: r.tenant_id,
                client_id: r.client_id,
                agent_id: r.agent_id,
                branch_id: r.branch_id,
                product_code: r.product_code,
                current_status: StatusKind::from_db(&r.current_status).map_err(decode_error)?,
                otp_verified_at: r.otp_verified_at,
                consent_at: r.consent_at,
                consent_terms_version: r.consent_terms_version,
                submitted_at: r.submitted_at,
                created_at: r.created_at,
                updated_at: r.updated_at,
            })
        })
        .collect()
}

/// Count applications matching a filter (for pagination meta).
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn count(
    exec: impl PgExecutor<'_>,
    tenant_id: Uuid,
    filter: &ApplicationFilter,
) -> Result<i64, sqlx::Error> {
    let status = filter.status.map(|s| s.as_str().to_owned());
    let row = sqlx::query!(
        r#"SELECT COUNT(*) AS "count!"
           FROM onboarding_applications
           WHERE tenant_id = $1
             AND ($2::uuid IS NULL OR agent_id = $2)
             AND ($3::uuid IS NULL OR branch_id = $3)
             AND ($4::text IS NULL OR current_status = $4)
             AND (NOT $5::bool OR current_status <> 'draft')"#,
        tenant_id,
        filter.agent_id,
        filter.branch_id,
        status,
        filter.exclude_draft,
    )
    .fetch_one(exec)
    .await?;
    Ok(row.count)
}

/// Stamp the OTP verification time on an application.
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn set_otp_verified(
    exec: impl PgExecutor<'_>,
    tenant_id: Uuid,
    id: Uuid,
    at: DateTime<Utc>,
) -> Result<(), sqlx::Error> {
    sqlx::query!(
        r#"UPDATE onboarding_applications SET otp_verified_at = $3
           WHERE id = $1 AND tenant_id = $2"#,
        id,
        tenant_id,
        at,
    )
    .execute(exec)
    .await?;
    Ok(())
}

/// Record consent acceptance on an application.
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn set_consent(
    exec: impl PgExecutor<'_>,
    tenant_id: Uuid,
    id: Uuid,
    terms_version: &str,
    at: DateTime<Utc>,
) -> Result<(), sqlx::Error> {
    sqlx::query!(
        r#"UPDATE onboarding_applications
           SET consent_at = $3, consent_terms_version = $4
           WHERE id = $1 AND tenant_id = $2"#,
        id,
        tenant_id,
        at,
        terms_version,
    )
    .execute(exec)
    .await?;
    Ok(())
}
