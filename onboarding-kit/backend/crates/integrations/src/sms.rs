//! SMS provider trait (CLAUDE.md §9).
//!
//! Phase 2 ships the trait + [`MockProvider`] (used for OTP delivery in dev and
//! for tests). The real Africa's Talking / Infobip providers and the failover
//! wrapper land in Phase 3. All sends go through the jobs table — handlers never
//! call a provider inline.

use async_trait::async_trait;

use crate::phone::Phone;

/// Receipt for a sent SMS, recorded on the job row.
#[derive(Debug, Clone)]
pub struct SmsReceipt {
    pub provider: &'static str,
    pub message_id: Option<String>,
}

/// Errors sending SMS.
#[derive(Debug, thiserror::Error)]
pub enum SmsError {
    #[error("sms send failed: {0}")]
    Send(String),
}

/// An SMS delivery backend.
#[async_trait]
pub trait SmsProvider: Send + Sync {
    async fn send(&self, to: &Phone, message: &str) -> Result<SmsReceipt, SmsError>;
}

/// Logs (masked) instead of sending. Used for OTP in dev and in tests.
pub struct MockProvider;

#[async_trait]
impl SmsProvider for MockProvider {
    async fn send(&self, to: &Phone, _message: &str) -> Result<SmsReceipt, SmsError> {
        // Never log the message body (may contain an OTP code) or the full phone.
        tracing::info!(to = %to.masked(), "MOCK sms (not delivered)");
        Ok(SmsReceipt {
            provider: "mock",
            message_id: None,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn mock_sends_ok() {
        let phone = Phone::parse("+254712345678").unwrap();
        let receipt = MockProvider.send(&phone, "code: 123456").await.unwrap();
        assert_eq!(receipt.provider, "mock");
    }
}
