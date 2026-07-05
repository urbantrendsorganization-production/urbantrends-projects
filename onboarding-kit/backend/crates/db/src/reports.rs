//! Reporting aggregations (§7). Tenant-scoped. Time-to-approval is derived from
//! the append-only event log, which is the source of truth (§6).

use chrono::{DateTime, Utc};
use sqlx::PgExecutor;
use uuid::Uuid;

/// Onboarding counts for one agent.
#[derive(Debug, Clone)]
pub struct AgentStat {
    pub agent_id: Uuid,
    pub agent_name: String,
    pub total: i64,
    pub approved: i64,
}

/// Onboarding counts for one branch.
#[derive(Debug, Clone)]
pub struct BranchStat {
    pub branch_id: Uuid,
    pub branch_name: String,
    pub total: i64,
}

/// One rejection reason and how often it occurred.
#[derive(Debug, Clone)]
pub struct RejectionReason {
    pub reason: String,
    pub count: i64,
}

/// Onboardings per agent within an optional date window (on application creation).
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn per_agent(
    exec: impl PgExecutor<'_>,
    tenant_id: Uuid,
    from: Option<DateTime<Utc>>,
    to: Option<DateTime<Utc>>,
) -> Result<Vec<AgentStat>, sqlx::Error> {
    let rows = sqlx::query!(
        r#"SELECT u.id AS "agent_id!", u.full_name AS "agent_name!",
                  COUNT(a.id) AS "total!",
                  COUNT(a.id) FILTER (WHERE a.current_status = 'approved') AS "approved!"
           FROM users u
           LEFT JOIN onboarding_applications a
             ON a.agent_id = u.id AND a.tenant_id = u.tenant_id
             AND ($2::timestamptz IS NULL OR a.created_at >= $2)
             AND ($3::timestamptz IS NULL OR a.created_at <= $3)
           WHERE u.tenant_id = $1 AND u.role = 'agent'
           GROUP BY u.id, u.full_name
           ORDER BY "total!" DESC, u.full_name"#,
        tenant_id,
        from,
        to,
    )
    .fetch_all(exec)
    .await?;
    Ok(rows
        .into_iter()
        .map(|r| AgentStat {
            agent_id: r.agent_id,
            agent_name: r.agent_name,
            total: r.total,
            approved: r.approved,
        })
        .collect())
}

/// Onboardings per branch within an optional date window.
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn per_branch(
    exec: impl PgExecutor<'_>,
    tenant_id: Uuid,
    from: Option<DateTime<Utc>>,
    to: Option<DateTime<Utc>>,
) -> Result<Vec<BranchStat>, sqlx::Error> {
    let rows = sqlx::query!(
        r#"SELECT b.id AS "branch_id!", b.name AS "branch_name!", COUNT(a.id) AS "total!"
           FROM branches b
           LEFT JOIN onboarding_applications a
             ON a.branch_id = b.id AND a.tenant_id = b.tenant_id
             AND ($2::timestamptz IS NULL OR a.created_at >= $2)
             AND ($3::timestamptz IS NULL OR a.created_at <= $3)
           WHERE b.tenant_id = $1
           GROUP BY b.id, b.name
           ORDER BY "total!" DESC, b.name"#,
        tenant_id,
        from,
        to,
    )
    .fetch_all(exec)
    .await?;
    Ok(rows
        .into_iter()
        .map(|r| BranchStat {
            branch_id: r.branch_id,
            branch_name: r.branch_name,
            total: r.total,
        })
        .collect())
}

/// Average time-to-approval in seconds (submitted event → first approved event),
/// or `None` if nothing has been approved yet.
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn avg_time_to_approval_secs(
    exec: impl PgExecutor<'_>,
    tenant_id: Uuid,
) -> Result<Option<f64>, sqlx::Error> {
    let row = sqlx::query!(
        r#"SELECT AVG(EXTRACT(EPOCH FROM (appr.at - sub.at)))::float8 AS avg_secs
           FROM (SELECT application_id, MIN(created_at) AS at
                   FROM application_events
                   WHERE tenant_id = $1 AND to_status = 'approved'
                   GROUP BY application_id) appr
           JOIN (SELECT application_id, MIN(created_at) AS at
                   FROM application_events
                   WHERE tenant_id = $1 AND to_status = 'submitted'
                   GROUP BY application_id) sub
             ON appr.application_id = sub.application_id"#,
        tenant_id,
    )
    .fetch_one(exec)
    .await?;
    Ok(row.avg_secs)
}

/// Rejection reasons and their frequencies.
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn rejection_reasons(
    exec: impl PgExecutor<'_>,
    tenant_id: Uuid,
) -> Result<Vec<RejectionReason>, sqlx::Error> {
    let rows = sqlx::query!(
        r#"SELECT COALESCE(reason, '(unspecified)') AS "reason!", COUNT(*) AS "count!"
           FROM application_events
           WHERE tenant_id = $1 AND to_status = 'rejected'
           GROUP BY reason
           ORDER BY "count!" DESC"#,
        tenant_id,
    )
    .fetch_all(exec)
    .await?;
    Ok(rows
        .into_iter()
        .map(|r| RejectionReason {
            reason: r.reason,
            count: r.count,
        })
        .collect())
}
