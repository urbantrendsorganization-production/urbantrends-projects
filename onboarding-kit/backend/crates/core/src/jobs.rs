//! Background job type names and payloads (CLAUDE.md §10).
//!
//! Shared between the api (which enqueues) and the worker (which executes). Pure
//! serde types — no sqlx here.

use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// Job type discriminators, stored in `jobs.job_type`.
pub mod job_type {
    pub const PROCESS_IMAGE: &str = "process_image";
    pub const SEND_SMS: &str = "send_sms";
    pub const SEND_EMAIL: &str = "send_email";
    pub const NIGHTLY_EXPORT_DIGEST: &str = "nightly_export_digest";
}

/// Payload for `process_image`: which document to (re)process.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProcessImagePayload {
    pub document_id: Uuid,
}

/// Payload for `send_sms`. The message may contain a one-time code, so job
/// payloads are never logged (§3, §8).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SendSmsPayload {
    pub to_phone: String,
    pub message: String,
}

/// Payload for `send_email` — a fully rendered message ready to deliver.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SendEmailPayload {
    pub to: String,
    pub subject: String,
    pub text: String,
    pub html: String,
}
