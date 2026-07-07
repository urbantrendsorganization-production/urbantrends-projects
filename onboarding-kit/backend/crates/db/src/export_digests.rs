//! Nightly export-digest ledger (§10). One row per tenant per EAT date records
//! where that day's approved-clients export was archived. The `(tenant_id,
//! digest_date)` UNIQUE constraint makes the digest job idempotent under
//! at-least-once delivery.

use chrono::NaiveDate;
use sqlx::PgExecutor;
use uuid::Uuid;

/// Whether a digest has already been recorded for this tenant + date.
///
/// # Errors
/// Returns [`sqlx::Error`] on a query failure.
pub async fn exists(
    exec: impl PgExecutor<'_>,
    tenant_id: Uuid,
    digest_date: NaiveDate,
) -> Result<bool, sqlx::Error> {
    let row = sqlx::query_scalar!(
        r#"SELECT EXISTS(
               SELECT 1 FROM export_digests
               WHERE tenant_id = $1 AND digest_date = $2
           ) AS "exists!""#,
        tenant_id,
        digest_date,
    )
    .fetch_one(exec)
    .await?;
    Ok(row)
}

/// Record a completed digest. Returns `true` if this call inserted the row,
/// `false` if a row for `(tenant_id, digest_date)` already existed (a
/// concurrent/duplicate run) — the caller may treat both as success.
///
/// # Errors
/// Returns [`sqlx::Error`] on a query failure.
pub async fn record(
    exec: impl PgExecutor<'_>,
    tenant_id: Uuid,
    digest_date: NaiveDate,
    storage_key: &str,
    row_count: i32,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query!(
        r#"INSERT INTO export_digests (tenant_id, digest_date, storage_key, row_count)
           VALUES ($1, $2, $3, $4)
           ON CONFLICT (tenant_id, digest_date) DO NOTHING"#,
        tenant_id,
        digest_date,
        storage_key,
        row_count,
    )
    .execute(exec)
    .await?;
    Ok(result.rows_affected() == 1)
}

#[cfg(test)]
mod tests {
    use super::*;
    use sqlx::PgPool;

    async fn a_tenant(pool: &PgPool) -> Uuid {
        // Unchecked query so no offline-cache entry is needed for the test.
        sqlx::query_scalar("INSERT INTO tenants (name) VALUES ('Test') RETURNING id")
            .fetch_one(pool)
            .await
            .unwrap()
    }

    #[sqlx::test(migrations = "../../migrations")]
    async fn record_is_idempotent(pool: PgPool) {
        let tenant = a_tenant(&pool).await;
        let date = NaiveDate::from_ymd_opt(2026, 7, 5).unwrap();

        assert!(!exists(&pool, tenant, date).await.unwrap());
        // First record inserts.
        assert!(record(&pool, tenant, date, "k1", 3).await.unwrap());
        assert!(exists(&pool, tenant, date).await.unwrap());
        // Second record for the same (tenant, date) is a conflict → false, and
        // must not overwrite the first row.
        assert!(!record(&pool, tenant, date, "k2", 9).await.unwrap());

        // A different date is a distinct digest.
        let other = NaiveDate::from_ymd_opt(2026, 7, 6).unwrap();
        assert!(record(&pool, tenant, other, "k3", 1).await.unwrap());
    }
}
