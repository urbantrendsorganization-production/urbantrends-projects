//! SMS provider trait (CLAUDE.md §9).
//!
//! [`MockProvider`] is used for OTP delivery in dev/demo and tests. The real
//! [`AfricasTalkingProvider`] (primary) and [`InfobipProvider`] (fallback) are
//! composed by [`FallbackProvider`] and selected via [`provider_from_env`]. All
//! sends go through the jobs table — handlers never call a provider inline.

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

/// Credentials for the live providers, read from the environment (§13: secrets
/// via env only). Absent/blank fields mean that provider is not configured.
#[derive(Debug, Clone, Default)]
pub struct LiveSmsConfig {
    pub at_username: Option<String>,
    pub at_api_key: Option<String>,
    pub at_sender_id: Option<String>,
    pub infobip_base_url: Option<String>,
    pub infobip_api_key: Option<String>,
    pub infobip_sender: Option<String>,
}

impl LiveSmsConfig {
    /// Read config from the standard env vars (see `ops/.env.example`).
    #[must_use]
    pub fn from_env() -> Self {
        let get = |k: &str| std::env::var(k).ok().filter(|v| !v.trim().is_empty());
        Self {
            at_username: get("AFRICASTALKING_USERNAME"),
            at_api_key: get("AFRICASTALKING_API_KEY"),
            at_sender_id: get("AFRICASTALKING_SENDER_ID"),
            infobip_base_url: get("INFOBIP_BASE_URL"),
            infobip_api_key: get("INFOBIP_API_KEY"),
            infobip_sender: get("INFOBIP_SENDER_ID"),
        }
    }
}

/// Build the provider stack from the environment (§9).
///
/// `SMS_DRY_RUN=false` wires Africa's Talking (primary) → Infobip (fallback)
/// when their credentials are present (mirrors `EMAIL_DRY_RUN`). Otherwise — or
/// with missing creds — yields the [`MockProvider`] used in dev/demo and tests,
/// so the flow always works.
#[must_use]
pub fn provider_from_env() -> std::sync::Arc<dyn SmsProvider> {
    use std::sync::Arc;
    // Default to dry-run (mock) unless explicitly disabled.
    let dry_run = std::env::var("SMS_DRY_RUN").map_or(true, |v| !v.eq_ignore_ascii_case("false"));
    if dry_run {
        return Arc::new(MockProvider);
    }
    let cfg = LiveSmsConfig::from_env();
    let primary = AfricasTalkingProvider::from_config(&cfg);
    let fallback = InfobipProvider::from_config(&cfg);
    match (primary, fallback) {
        (Some(p), Some(f)) => Arc::new(FallbackProvider::new(Box::new(p), Box::new(f))),
        (Some(p), None) => Arc::new(p),
        (None, Some(f)) => Arc::new(f),
        (None, None) => {
            tracing::warn!("SMS_PROVIDER=live but no provider credentials configured; using mock");
            Arc::new(MockProvider)
        }
    }
}

/// Africa's Talking bulk SMS (primary — §9).
pub struct AfricasTalkingProvider {
    http: reqwest::Client,
    username: String,
    api_key: String,
    sender_id: Option<String>,
}

impl AfricasTalkingProvider {
    /// Construct from config, or `None` if credentials are missing.
    #[must_use]
    pub fn from_config(cfg: &LiveSmsConfig) -> Option<Self> {
        Some(Self {
            http: reqwest::Client::new(),
            username: cfg.at_username.clone()?,
            api_key: cfg.at_api_key.clone()?,
            sender_id: cfg.at_sender_id.clone(),
        })
    }
}

#[async_trait]
impl SmsProvider for AfricasTalkingProvider {
    async fn send(&self, to: &Phone, message: &str) -> Result<SmsReceipt, SmsError> {
        let mut form = vec![
            ("username", self.username.as_str()),
            ("to", to.as_str()),
            ("message", message),
        ];
        if let Some(from) = &self.sender_id {
            form.push(("from", from.as_str()));
        }
        let resp = self
            .http
            .post("https://api.africastalking.com/version1/messaging")
            .header("apiKey", &self.api_key)
            .header("Accept", "application/json")
            .form(&form)
            .send()
            .await
            .map_err(|e| SmsError::Send(format!("africastalking request: {e}")))?;

        if !resp.status().is_success() {
            return Err(SmsError::Send(format!(
                "africastalking status {}",
                resp.status()
            )));
        }
        let body: serde_json::Value = resp
            .json()
            .await
            .map_err(|e| SmsError::Send(format!("africastalking decode: {e}")))?;
        let message_id = body
            .pointer("/SMSMessageData/Recipients/0/messageId")
            .and_then(serde_json::Value::as_str)
            .map(ToOwned::to_owned);
        Ok(SmsReceipt {
            provider: "africastalking",
            message_id,
        })
    }
}

/// Infobip SMS (fallback — §9).
pub struct InfobipProvider {
    http: reqwest::Client,
    base_url: String,
    api_key: String,
    sender: Option<String>,
}

impl InfobipProvider {
    /// Construct from config, or `None` if credentials are missing.
    #[must_use]
    pub fn from_config(cfg: &LiveSmsConfig) -> Option<Self> {
        Some(Self {
            http: reqwest::Client::new(),
            base_url: cfg
                .infobip_base_url
                .clone()?
                .trim_end_matches('/')
                .to_owned(),
            api_key: cfg.infobip_api_key.clone()?,
            sender: cfg.infobip_sender.clone(),
        })
    }
}

#[async_trait]
impl SmsProvider for InfobipProvider {
    async fn send(&self, to: &Phone, message: &str) -> Result<SmsReceipt, SmsError> {
        let mut msg = serde_json::json!({
            "destinations": [{ "to": to.as_str() }],
            "text": message,
        });
        if let Some(from) = &self.sender {
            msg["from"] = serde_json::Value::String(from.clone());
        }
        let body = serde_json::json!({ "messages": [msg] });
        let resp = self
            .http
            .post(format!("{}/sms/2/text/advanced", self.base_url))
            .header("Authorization", format!("App {}", self.api_key))
            .header("Accept", "application/json")
            .json(&body)
            .send()
            .await
            .map_err(|e| SmsError::Send(format!("infobip request: {e}")))?;

        if !resp.status().is_success() {
            return Err(SmsError::Send(format!("infobip status {}", resp.status())));
        }
        let out: serde_json::Value = resp
            .json()
            .await
            .map_err(|e| SmsError::Send(format!("infobip decode: {e}")))?;
        let message_id = out
            .pointer("/messages/0/messageId")
            .and_then(serde_json::Value::as_str)
            .map(ToOwned::to_owned);
        Ok(SmsReceipt {
            provider: "infobip",
            message_id,
        })
    }
}

/// Tries `primary`, and on failure logs and tries `fallback` (§9). The returned
/// receipt records which provider actually delivered.
pub struct FallbackProvider {
    primary: Box<dyn SmsProvider>,
    fallback: Box<dyn SmsProvider>,
}

impl FallbackProvider {
    #[must_use]
    pub fn new(primary: Box<dyn SmsProvider>, fallback: Box<dyn SmsProvider>) -> Self {
        Self { primary, fallback }
    }
}

#[async_trait]
impl SmsProvider for FallbackProvider {
    async fn send(&self, to: &Phone, message: &str) -> Result<SmsReceipt, SmsError> {
        match self.primary.send(to, message).await {
            Ok(receipt) => Ok(receipt),
            Err(primary_err) => {
                // Log the failure (no message body — may contain an OTP), then
                // try the fallback provider.
                tracing::warn!(error = %primary_err, "primary sms provider failed, trying fallback");
                self.fallback.send(to, message).await
            }
        }
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

    struct AlwaysFail;
    #[async_trait]
    impl SmsProvider for AlwaysFail {
        async fn send(&self, _to: &Phone, _m: &str) -> Result<SmsReceipt, SmsError> {
            Err(SmsError::Send("boom".into()))
        }
    }

    #[tokio::test]
    async fn fallback_uses_secondary_when_primary_fails() {
        let phone = Phone::parse("+254712345678").unwrap();
        let provider = FallbackProvider::new(Box::new(AlwaysFail), Box::new(MockProvider));
        let receipt = provider.send(&phone, "hello").await.unwrap();
        assert_eq!(receipt.provider, "mock");
    }

    #[tokio::test]
    async fn fallback_propagates_when_both_fail() {
        let phone = Phone::parse("+254712345678").unwrap();
        let provider = FallbackProvider::new(Box::new(AlwaysFail), Box::new(AlwaysFail));
        assert!(provider.send(&phone, "hello").await.is_err());
    }
}
