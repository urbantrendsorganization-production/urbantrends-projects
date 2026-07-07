//! Postgres-backed [`OtpStore`] — the glue between the OTP service (in
//! `integrations`) and the tenant-scoped OTP queries (in `db`).
//!
//! This lives in `api` because it is the one place that legally depends on both
//! `integrations` and `db` (§2), keeping the OTP persistence queries in `db`
//! where the tenant filter is enforced (§4).

use async_trait::async_trait;
use chrono::{DateTime, Utc};
use onboardkit_integrations::Phone;
use onboardkit_integrations::otp::{NewOtp, OtpPurpose, OtpRecord, OtpStore, StoreError};
use sqlx::postgres::PgPool;
use uuid::Uuid;

/// An [`OtpStore`] backed by Postgres.
pub struct PgOtpStore {
    pool: PgPool,
}

impl PgOtpStore {
    #[must_use]
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }
}

#[allow(clippy::needless_pass_by_value)] // used as a `map_err` fn, which passes by value
fn store_error(err: sqlx::Error) -> StoreError {
    StoreError(err.to_string())
}

#[async_trait]
impl OtpStore for PgOtpStore {
    async fn count_recent_sends(
        &self,
        tenant_id: Uuid,
        phone: &Phone,
        purpose: OtpPurpose,
        since: DateTime<Utc>,
    ) -> Result<i64, StoreError> {
        onboardkit_db::otp::count_recent_sends(
            &self.pool,
            tenant_id,
            phone.as_str(),
            purpose.as_str(),
            since,
        )
        .await
        .map_err(store_error)
    }

    async fn insert(&self, new: NewOtp) -> Result<Uuid, StoreError> {
        onboardkit_db::otp::insert(
            &self.pool,
            new.tenant_id,
            new.phone.as_str(),
            &new.code_hash,
            new.purpose.as_str(),
            new.max_attempts,
            new.expires_at,
            new.created_at,
        )
        .await
        .map_err(store_error)
    }

    async fn latest(
        &self,
        tenant_id: Uuid,
        phone: &Phone,
        purpose: OtpPurpose,
    ) -> Result<Option<OtpRecord>, StoreError> {
        let row =
            onboardkit_db::otp::latest(&self.pool, tenant_id, phone.as_str(), purpose.as_str())
                .await
                .map_err(store_error)?;
        Ok(row.map(|r| OtpRecord {
            id: r.id,
            code_hash: r.code_hash,
            expires_at: r.expires_at,
            attempts: r.attempts,
            max_attempts: r.max_attempts,
            verified_at: r.verified_at,
        }))
    }

    async fn increment_attempts(&self, id: Uuid) -> Result<(), StoreError> {
        onboardkit_db::otp::increment_attempts(&self.pool, id)
            .await
            .map_err(store_error)
    }

    async fn mark_verified(&self, id: Uuid, at: DateTime<Utc>) -> Result<(), StoreError> {
        onboardkit_db::otp::mark_verified(&self.pool, id, at)
            .await
            .map_err(store_error)
    }
}
