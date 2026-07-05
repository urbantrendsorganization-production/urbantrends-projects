//! OTP service (CLAUDE.md §8).
//!
//! Port of UrbanTrends' hardened OTP design:
//! - 6-digit numeric codes from the OS CSPRNG (via `getrandom`), rejection
//!   sampled to avoid modulo bias. Never a userspace/thread RNG.
//! - Stored only as a SHA-256 hash; verified with a constant-time compare.
//! - 5-minute TTL, single-use, max 5 verify attempts per code.
//! - Max 3 sends per phone per hour, counted in the store (not in-memory).
//! - Generic verification errors: callers cannot tell *why* a verify failed,
//!   nor whether a code exists for a phone.
//!
//! The service is generic over a [`Clock`] and an [`OtpStore`] so its policy can
//! be unit-tested with a mock clock and an in-memory store. The Postgres-backed
//! store lands in Phase 2 alongside the OTP endpoints.

use async_trait::async_trait;
use chrono::{DateTime, Duration, Utc};
use sha2::{Digest, Sha256};
use subtle::ConstantTimeEq;
use uuid::Uuid;

use crate::phone::{Phone, PhoneError};

/// Purpose of an OTP. Matches the `otp_verifications.purpose` CHECK values.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OtpPurpose {
    ClientOnboarding,
}

impl OtpPurpose {
    #[must_use]
    pub fn as_str(self) -> &'static str {
        match self {
            OtpPurpose::ClientOnboarding => "client_onboarding",
        }
    }
}

/// A source of the current time, injectable so tests can use a mock clock.
pub trait Clock: Send + Sync {
    fn now(&self) -> DateTime<Utc>;
}

/// Wall-clock implementation for production use.
#[derive(Debug, Clone, Copy, Default)]
pub struct SystemClock;

impl Clock for SystemClock {
    fn now(&self) -> DateTime<Utc> {
        Utc::now()
    }
}

/// Tunable policy for the OTP service.
#[derive(Debug, Clone, Copy)]
pub struct OtpConfig {
    pub ttl: Duration,
    pub max_attempts: i32,
    pub max_sends_per_hour: i32,
    pub code_len: u32,
}

impl Default for OtpConfig {
    fn default() -> Self {
        Self {
            ttl: Duration::minutes(5),
            max_attempts: 5,
            max_sends_per_hour: 3,
            code_len: 6,
        }
    }
}

/// A row to be persisted by [`OtpStore::insert`].
#[derive(Debug, Clone)]
pub struct NewOtp {
    pub tenant_id: Uuid,
    pub phone: Phone,
    pub purpose: OtpPurpose,
    pub code_hash: String,
    pub max_attempts: i32,
    pub expires_at: DateTime<Utc>,
    pub created_at: DateTime<Utc>,
}

/// The fields of a stored OTP that verification needs.
#[derive(Debug, Clone)]
pub struct OtpRecord {
    pub id: Uuid,
    pub code_hash: String,
    pub expires_at: DateTime<Utc>,
    pub attempts: i32,
    pub max_attempts: i32,
    pub verified_at: Option<DateTime<Utc>>,
}

/// Persistence backing the OTP service. The production implementation is
/// Postgres; tests use an in-memory store.
#[async_trait]
pub trait OtpStore: Send + Sync {
    /// Count OTP sends for `phone`/`purpose` created at or after `since`.
    async fn count_recent_sends(
        &self,
        tenant_id: Uuid,
        phone: &Phone,
        purpose: OtpPurpose,
        since: DateTime<Utc>,
    ) -> Result<i64, StoreError>;

    /// Persist a new OTP, returning its id.
    async fn insert(&self, new: NewOtp) -> Result<Uuid, StoreError>;

    /// The most recently created OTP for `phone`/`purpose`, if any.
    async fn latest(
        &self,
        tenant_id: Uuid,
        phone: &Phone,
        purpose: OtpPurpose,
    ) -> Result<Option<OtpRecord>, StoreError>;

    /// Record one consumed verification attempt.
    async fn increment_attempts(&self, id: Uuid) -> Result<(), StoreError>;

    /// Mark an OTP as verified (single-use).
    async fn mark_verified(&self, id: Uuid, at: DateTime<Utc>) -> Result<(), StoreError>;
}

/// Opaque storage-backend failure. Never surfaced to end users verbatim.
#[derive(Debug, thiserror::Error)]
#[error("otp store error: {0}")]
pub struct StoreError(pub String);

/// Errors from the OTP service.
#[derive(Debug, thiserror::Error)]
pub enum OtpError {
    #[error("invalid phone number")]
    InvalidPhone,

    /// Too many sends for this phone within the window.
    #[error("too many requests")]
    RateLimited,

    /// Generic verification failure — deliberately indistinguishable across
    /// wrong code / expired / already used / too many attempts / no code (§8).
    #[error("verification failed")]
    Verification,

    /// OS entropy source failed.
    #[error("internal error")]
    Rng,

    #[error(transparent)]
    Store(#[from] StoreError),
}

impl From<PhoneError> for OtpError {
    fn from(_: PhoneError) -> Self {
        OtpError::InvalidPhone
    }
}

/// The result of issuing an OTP. `code` is the plaintext to be delivered by SMS
/// and MUST NOT be logged or returned in an API response (§8).
#[derive(Debug, Clone)]
pub struct SendOutcome {
    pub code: String,
    pub expires_at: DateTime<Utc>,
}

/// The OTP service. Cheap to construct; holds a store and clock.
pub struct OtpService<S, C = SystemClock> {
    store: S,
    clock: C,
    config: OtpConfig,
}

impl<S: OtpStore> OtpService<S, SystemClock> {
    /// Construct with the wall clock and default policy.
    pub fn new(store: S) -> Self {
        Self {
            store,
            clock: SystemClock,
            config: OtpConfig::default(),
        }
    }
}

impl<S: OtpStore, C: Clock> OtpService<S, C> {
    /// Construct with an explicit clock and config (used by tests).
    pub fn with_clock(store: S, clock: C, config: OtpConfig) -> Self {
        Self {
            store,
            clock,
            config,
        }
    }

    /// Issue a fresh OTP for `phone`, enforcing the per-phone send rate limit.
    ///
    /// Returns the plaintext code for delivery. The code is never persisted in
    /// plaintext nor logged here.
    ///
    /// # Errors
    /// [`OtpError::InvalidPhone`] for an unparseable number,
    /// [`OtpError::RateLimited`] once the hourly send cap is reached,
    /// [`OtpError::Rng`] on entropy failure, or [`OtpError::Store`].
    pub async fn send(
        &self,
        tenant_id: Uuid,
        raw_phone: &str,
        purpose: OtpPurpose,
    ) -> Result<SendOutcome, OtpError> {
        let phone = Phone::parse(raw_phone)?;
        let now = self.clock.now();
        let since = now - Duration::hours(1);

        let recent = self
            .store
            .count_recent_sends(tenant_id, &phone, purpose, since)
            .await?;
        if recent >= i64::from(self.config.max_sends_per_hour) {
            tracing::warn!(phone = %phone.masked(), "otp send rate limit reached");
            return Err(OtpError::RateLimited);
        }

        let code = generate_numeric_code(self.config.code_len)?;
        let code_hash = sha256_hex(&code);
        let expires_at = now + self.config.ttl;

        self.store
            .insert(NewOtp {
                tenant_id,
                phone: phone.clone(),
                purpose,
                code_hash,
                max_attempts: self.config.max_attempts,
                expires_at,
                created_at: now,
            })
            .await?;

        tracing::info!(phone = %phone.masked(), "otp issued");
        Ok(SendOutcome { code, expires_at })
    }

    /// Verify a submitted `code` for `phone`. All failure modes collapse to
    /// [`OtpError::Verification`] so nothing about the check leaks (§8).
    ///
    /// # Errors
    /// [`OtpError::InvalidPhone`], [`OtpError::Verification`], or
    /// [`OtpError::Store`].
    pub async fn verify(
        &self,
        tenant_id: Uuid,
        raw_phone: &str,
        code: &str,
        purpose: OtpPurpose,
    ) -> Result<(), OtpError> {
        let phone = Phone::parse(raw_phone)?;
        let now = self.clock.now();

        let record = self
            .store
            .latest(tenant_id, &phone, purpose)
            .await?
            .ok_or(OtpError::Verification)?;

        // Already used, expired, or locked out — all indistinguishable.
        if record.verified_at.is_some()
            || now >= record.expires_at
            || record.attempts >= record.max_attempts
        {
            return Err(OtpError::Verification);
        }

        // Consume one attempt before comparing so brute force is bounded even if
        // the process dies mid-verify.
        self.store.increment_attempts(record.id).await?;

        let candidate = sha256_hex(code.trim());
        let matches: bool = candidate
            .as_bytes()
            .ct_eq(record.code_hash.as_bytes())
            .into();
        if !matches {
            return Err(OtpError::Verification);
        }

        self.store.mark_verified(record.id, now).await?;
        tracing::info!(phone = %phone.masked(), "otp verified");
        Ok(())
    }
}

/// SHA-256 of `input`, lowercase hex.
fn sha256_hex(input: &str) -> String {
    hex::encode(Sha256::digest(input.as_bytes()))
}

/// A zero-padded numeric code of `len` digits from the OS CSPRNG, rejection
/// sampled to remove modulo bias.
fn generate_numeric_code(len: u32) -> Result<String, OtpError> {
    let limit: u64 = 10u64.pow(len);
    // Largest multiple of `limit` that fits in u64; values at/above are rejected.
    let ceiling = u64::MAX - (u64::MAX % limit);
    loop {
        let mut buf = [0u8; 8];
        getrandom::fill(&mut buf).map_err(|_| OtpError::Rng)?;
        let n = u64::from_le_bytes(buf);
        if n < ceiling {
            return Ok(format!("{:0width$}", n % limit, width = len as usize));
        }
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Mutex;

    use super::*;

    // ---- Mock clock ------------------------------------------------------

    #[derive(Clone)]
    struct MockClock {
        now: std::sync::Arc<Mutex<DateTime<Utc>>>,
    }

    impl MockClock {
        fn new() -> Self {
            Self {
                now: std::sync::Arc::new(Mutex::new(
                    DateTime::parse_from_rfc3339("2026-01-01T00:00:00Z")
                        .unwrap()
                        .with_timezone(&Utc),
                )),
            }
        }
        fn advance(&self, by: Duration) {
            let mut guard = self.now.lock().unwrap();
            *guard += by;
        }
    }

    impl Clock for MockClock {
        fn now(&self) -> DateTime<Utc> {
            *self.now.lock().unwrap()
        }
    }

    // ---- In-memory store -------------------------------------------------

    #[derive(Clone)]
    struct Row {
        id: Uuid,
        tenant_id: Uuid,
        phone: String,
        purpose: OtpPurpose,
        code_hash: String,
        max_attempts: i32,
        attempts: i32,
        expires_at: DateTime<Utc>,
        verified_at: Option<DateTime<Utc>>,
        created_at: DateTime<Utc>,
    }

    #[derive(Clone, Default)]
    struct MemStore {
        rows: std::sync::Arc<Mutex<Vec<Row>>>,
    }

    #[async_trait]
    impl OtpStore for MemStore {
        async fn count_recent_sends(
            &self,
            tenant_id: Uuid,
            phone: &Phone,
            purpose: OtpPurpose,
            since: DateTime<Utc>,
        ) -> Result<i64, StoreError> {
            let rows = self.rows.lock().unwrap();
            let count = rows
                .iter()
                .filter(|r| {
                    r.tenant_id == tenant_id
                        && r.phone == phone.as_str()
                        && r.purpose == purpose
                        && r.created_at >= since
                })
                .count();
            Ok(i64::try_from(count).unwrap())
        }

        async fn insert(&self, new: NewOtp) -> Result<Uuid, StoreError> {
            let id = Uuid::new_v4();
            self.rows.lock().unwrap().push(Row {
                id,
                tenant_id: new.tenant_id,
                phone: new.phone.as_str().to_owned(),
                purpose: new.purpose,
                code_hash: new.code_hash,
                max_attempts: new.max_attempts,
                attempts: 0,
                expires_at: new.expires_at,
                verified_at: None,
                created_at: new.created_at,
            });
            Ok(id)
        }

        async fn latest(
            &self,
            tenant_id: Uuid,
            phone: &Phone,
            purpose: OtpPurpose,
        ) -> Result<Option<OtpRecord>, StoreError> {
            let rows = self.rows.lock().unwrap();
            let latest = rows
                .iter()
                .filter(|r| {
                    r.tenant_id == tenant_id && r.phone == phone.as_str() && r.purpose == purpose
                })
                .max_by_key(|r| r.created_at);
            Ok(latest.map(|r| OtpRecord {
                id: r.id,
                code_hash: r.code_hash.clone(),
                expires_at: r.expires_at,
                attempts: r.attempts,
                max_attempts: r.max_attempts,
                verified_at: r.verified_at,
            }))
        }

        async fn increment_attempts(&self, id: Uuid) -> Result<(), StoreError> {
            let mut rows = self.rows.lock().unwrap();
            if let Some(row) = rows.iter_mut().find(|r| r.id == id) {
                row.attempts += 1;
            }
            Ok(())
        }

        async fn mark_verified(&self, id: Uuid, at: DateTime<Utc>) -> Result<(), StoreError> {
            let mut rows = self.rows.lock().unwrap();
            if let Some(row) = rows.iter_mut().find(|r| r.id == id) {
                row.verified_at = Some(at);
            }
            Ok(())
        }
    }

    const PHONE: &str = "+254712345678";
    const PURPOSE: OtpPurpose = OtpPurpose::ClientOnboarding;

    fn service() -> (OtpService<MemStore, MockClock>, MockClock, Uuid) {
        let clock = MockClock::new();
        let store = MemStore::default();
        let svc = OtpService::with_clock(store, clock.clone(), OtpConfig::default());
        (svc, clock, Uuid::new_v4())
    }

    #[tokio::test]
    async fn generated_code_is_six_numeric_digits() {
        for _ in 0..50 {
            let code = generate_numeric_code(6).unwrap();
            assert_eq!(code.len(), 6);
            assert!(code.chars().all(|c| c.is_ascii_digit()));
        }
    }

    #[tokio::test]
    async fn send_then_verify_succeeds() {
        let (svc, _clock, tenant) = service();
        let outcome = svc.send(tenant, PHONE, PURPOSE).await.expect("send");
        svc.verify(tenant, PHONE, &outcome.code, PURPOSE)
            .await
            .expect("verify");
    }

    #[tokio::test]
    async fn wrong_code_fails_and_is_generic() {
        let (svc, _clock, tenant) = service();
        svc.send(tenant, PHONE, PURPOSE).await.expect("send");
        let err = svc
            .verify(tenant, PHONE, "000000", PURPOSE)
            .await
            .unwrap_err();
        assert!(matches!(err, OtpError::Verification));
    }

    #[tokio::test]
    async fn code_is_single_use() {
        let (svc, _clock, tenant) = service();
        let outcome = svc.send(tenant, PHONE, PURPOSE).await.expect("send");
        svc.verify(tenant, PHONE, &outcome.code, PURPOSE)
            .await
            .expect("first verify");
        let err = svc
            .verify(tenant, PHONE, &outcome.code, PURPOSE)
            .await
            .unwrap_err();
        assert!(matches!(err, OtpError::Verification), "reuse must fail");
    }

    #[tokio::test]
    async fn expired_code_fails() {
        let (svc, clock, tenant) = service();
        let outcome = svc.send(tenant, PHONE, PURPOSE).await.expect("send");
        clock.advance(Duration::minutes(5) + Duration::seconds(1));
        let err = svc
            .verify(tenant, PHONE, &outcome.code, PURPOSE)
            .await
            .unwrap_err();
        assert!(matches!(err, OtpError::Verification));
    }

    #[tokio::test]
    async fn locks_out_after_max_attempts() {
        let (svc, _clock, tenant) = service();
        let outcome = svc.send(tenant, PHONE, PURPOSE).await.expect("send");
        // 5 wrong attempts consume the budget.
        for _ in 0..5 {
            let _ = svc.verify(tenant, PHONE, "999999", PURPOSE).await;
        }
        // Even the correct code is now refused.
        let err = svc
            .verify(tenant, PHONE, &outcome.code, PURPOSE)
            .await
            .unwrap_err();
        assert!(matches!(err, OtpError::Verification));
    }

    #[tokio::test]
    async fn enforces_send_rate_limit_per_hour() {
        let (svc, clock, tenant) = service();
        for _ in 0..3 {
            svc.send(tenant, PHONE, PURPOSE).await.expect("send");
        }
        let err = svc.send(tenant, PHONE, PURPOSE).await.unwrap_err();
        assert!(matches!(err, OtpError::RateLimited));

        // After the window slides past an hour, sends are allowed again.
        clock.advance(Duration::hours(1) + Duration::minutes(1));
        svc.send(tenant, PHONE, PURPOSE)
            .await
            .expect("send after window");
    }

    #[tokio::test]
    async fn verify_with_no_code_is_generic_failure() {
        let (svc, _clock, tenant) = service();
        let err = svc
            .verify(tenant, PHONE, "123456", PURPOSE)
            .await
            .unwrap_err();
        assert!(matches!(err, OtpError::Verification));
    }

    #[tokio::test]
    async fn invalid_phone_rejected() {
        let (svc, _clock, tenant) = service();
        let err = svc.send(tenant, "nonsense", PURPOSE).await.unwrap_err();
        assert!(matches!(err, OtpError::InvalidPhone));
    }

    #[tokio::test]
    async fn latest_code_supersedes_previous() {
        let (svc, _clock, tenant) = service();
        let first = svc.send(tenant, PHONE, PURPOSE).await.expect("send 1");
        let second = svc.send(tenant, PHONE, PURPOSE).await.expect("send 2");
        // The superseded code no longer verifies (unless the two happen to
        // collide, which is a 1-in-a-million event we tolerate in a unit test).
        if first.code != second.code {
            let err = svc
                .verify(tenant, PHONE, &first.code, PURPOSE)
                .await
                .unwrap_err();
            assert!(matches!(err, OtpError::Verification));
        }
        svc.verify(tenant, PHONE, &second.code, PURPOSE)
            .await
            .expect("latest verifies");
    }
}
