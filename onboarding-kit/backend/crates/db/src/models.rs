//! Domain row types returned by the repositories.
//!
//! These map database rows into typed Rust values. Enumerated columns (like
//! `role`) are stored as TEXT and converted to `onboardkit-core` enums here,
//! because `core` cannot depend on sqlx (§3).

use chrono::{DateTime, NaiveDate, Utc};
use onboardkit_core::{Role, StatusKind};
use uuid::Uuid;

/// A user account (§5).
#[derive(Debug, Clone)]
pub struct User {
    pub id: Uuid,
    pub tenant_id: Uuid,
    pub branch_id: Option<Uuid>,
    pub full_name: String,
    pub phone: String,
    pub email: String,
    pub password_hash: String,
    pub role: Role,
    pub is_active: bool,
    pub created_at: DateTime<Utc>,
}

/// A refresh token record. The opaque token itself is never stored — only its
/// sha256 hash (§7).
#[derive(Debug, Clone)]
pub struct RefreshToken {
    pub id: Uuid,
    pub user_id: Uuid,
    pub expires_at: DateTime<Utc>,
    pub revoked_at: Option<DateTime<Utc>>,
    pub created_at: DateTime<Utc>,
}

impl RefreshToken {
    /// A token is usable only while unrevoked and unexpired.
    #[must_use]
    pub fn is_active(&self, now: DateTime<Utc>) -> bool {
        self.revoked_at.is_none() && self.expires_at > now
    }
}

/// A tenant (§5).
#[derive(Debug, Clone)]
pub struct Tenant {
    pub id: Uuid,
    pub name: String,
}

/// A branch office (§5).
#[derive(Debug, Clone)]
pub struct Branch {
    pub id: Uuid,
    pub tenant_id: Uuid,
    pub name: String,
    pub code: String,
    pub created_at: DateTime<Utc>,
}

/// A product offered by the tenant (migration 0004).
#[derive(Debug, Clone)]
pub struct Product {
    pub id: Uuid,
    pub tenant_id: Uuid,
    pub code: String,
    pub name: String,
    pub is_active: bool,
    pub created_at: DateTime<Utc>,
}

/// A client being onboarded (§5). Most fields are optional until filled in
/// during the draft.
#[derive(Debug, Clone)]
pub struct Client {
    pub id: Uuid,
    pub tenant_id: Uuid,
    pub full_name: String,
    pub phone: Option<String>,
    pub national_id_number: Option<String>,
    pub kra_pin: Option<String>,
    pub date_of_birth: Option<NaiveDate>,
    pub address: Option<String>,
    pub next_of_kin: Option<serde_json::Value>,
    pub client_number: Option<String>,
    pub created_at: DateTime<Utc>,
}

/// An onboarding application (§5). `current_status` is the denormalized
/// discriminant; the event log is the source of truth (§6).
#[derive(Debug, Clone)]
pub struct Application {
    pub id: Uuid,
    pub tenant_id: Uuid,
    pub client_id: Uuid,
    pub agent_id: Uuid,
    pub branch_id: Uuid,
    pub product_code: String,
    pub current_status: StatusKind,
    pub otp_verified_at: Option<DateTime<Utc>>,
    pub consent_at: Option<DateTime<Utc>>,
    pub consent_terms_version: Option<String>,
    pub submitted_at: Option<DateTime<Utc>>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

/// A KYC document (§5).
#[derive(Debug, Clone)]
pub struct KycDocument {
    pub id: Uuid,
    pub tenant_id: Uuid,
    pub application_id: Uuid,
    pub doc_type: String,
    pub storage_key: String,
    pub original_filename: String,
    pub content_type: String,
    pub size_bytes: i64,
    pub processed: bool,
    pub thumbnail_key: Option<String>,
    pub uploaded_at: DateTime<Utc>,
}

/// The fields of an OTP row needed to back the OTP service's store (§8).
#[derive(Debug, Clone)]
pub struct OtpRow {
    pub id: Uuid,
    pub code_hash: String,
    pub expires_at: DateTime<Utc>,
    pub attempts: i32,
    pub max_attempts: i32,
    pub verified_at: Option<DateTime<Utc>>,
}

/// A single row from the append-only event log (§5), for history views.
#[derive(Debug, Clone)]
pub struct ApplicationEvent {
    pub id: Uuid,
    pub application_id: Uuid,
    pub actor_user_id: Uuid,
    pub from_status: Option<String>,
    pub to_status: String,
    pub reason: Option<String>,
    pub created_at: DateTime<Utc>,
}
