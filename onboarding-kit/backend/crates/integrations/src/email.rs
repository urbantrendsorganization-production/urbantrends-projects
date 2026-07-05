//! Transactional email via Resend (CLAUDE.md §9-style provider trait).
//!
//! Handlers never send inline — the api enqueues a `send_email` job and the
//! worker builds a provider and delivers it. `EMAIL_DRY_RUN` (or a missing API
//! key) routes to [`MockEmailProvider`], which logs instead of sending.

use async_trait::async_trait;
use serde::Serialize;

/// An email to send. `to` is a single recipient (all onboarding emails are 1:1).
#[derive(Debug, Clone)]
pub struct EmailMessage {
    pub to: String,
    pub subject: String,
    pub html: String,
    pub text: String,
}

/// Errors sending email.
#[derive(Debug, thiserror::Error)]
pub enum EmailError {
    #[error("email send failed: {0}")]
    Send(String),
}

/// An email delivery backend.
#[async_trait]
pub trait EmailProvider: Send + Sync {
    async fn send(&self, msg: &EmailMessage) -> Result<(), EmailError>;
    /// Human-readable provider name, recorded on the job row.
    fn name(&self) -> &'static str;
}

/// Config for constructing a provider.
#[derive(Debug, Clone)]
pub struct EmailConfig {
    pub api_key: String,
    pub from: String,
    pub dry_run: bool,
}

/// Build the appropriate provider: [`MockEmailProvider`] when dry-run or no key,
/// otherwise [`ResendProvider`].
#[must_use]
pub fn build_provider(config: &EmailConfig) -> Box<dyn EmailProvider> {
    if config.dry_run || config.api_key.is_empty() {
        Box::new(MockEmailProvider)
    } else {
        Box::new(ResendProvider::new(&config.api_key, &config.from))
    }
}

/// Resend REST provider (<https://resend.com/docs>).
pub struct ResendProvider {
    api_key: String,
    from: String,
    http: reqwest::Client,
}

impl ResendProvider {
    #[must_use]
    pub fn new(api_key: &str, from: &str) -> Self {
        Self {
            api_key: api_key.to_owned(),
            from: from.to_owned(),
            http: reqwest::Client::new(),
        }
    }
}

#[derive(Serialize)]
struct ResendRequest<'a> {
    from: &'a str,
    to: [&'a str; 1],
    subject: &'a str,
    html: &'a str,
    text: &'a str,
}

#[async_trait]
impl EmailProvider for ResendProvider {
    async fn send(&self, msg: &EmailMessage) -> Result<(), EmailError> {
        let body = ResendRequest {
            from: &self.from,
            to: [&msg.to],
            subject: &msg.subject,
            html: &msg.html,
            text: &msg.text,
        };
        let response = self
            .http
            .post("https://api.resend.com/emails")
            .bearer_auth(&self.api_key)
            .json(&body)
            .send()
            .await
            .map_err(|e| EmailError::Send(e.to_string()))?;

        if response.status().is_success() {
            tracing::info!(to = %msg.to, "email sent via resend");
            Ok(())
        } else {
            let status = response.status();
            let detail = response.text().await.unwrap_or_default();
            Err(EmailError::Send(format!(
                "resend returned {status}: {detail}"
            )))
        }
    }

    fn name(&self) -> &'static str {
        "resend"
    }
}

/// Logs instead of sending. Used in dev / dry-run and tests.
pub struct MockEmailProvider;

#[async_trait]
impl EmailProvider for MockEmailProvider {
    async fn send(&self, msg: &EmailMessage) -> Result<(), EmailError> {
        tracing::info!(to = %msg.to, subject = %msg.subject, "MOCK email (not delivered)");
        Ok(())
    }

    fn name(&self) -> &'static str {
        "mock"
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn mock_provider_accepts_and_reports_name() {
        let provider = build_provider(&EmailConfig {
            api_key: String::new(),
            from: "OnboardKit <no-reply@example.com>".to_owned(),
            dry_run: true,
        });
        assert_eq!(provider.name(), "mock");
        provider
            .send(&EmailMessage {
                to: "agent@example.com".to_owned(),
                subject: "Application submitted".to_owned(),
                html: "<p>hi</p>".to_owned(),
                text: "hi".to_owned(),
            })
            .await
            .expect("mock send");
    }

    #[test]
    fn real_key_selects_resend() {
        let provider = build_provider(&EmailConfig {
            api_key: "re_live_xxx".to_owned(),
            from: "OnboardKit <no-reply@example.com>".to_owned(),
            dry_run: false,
        });
        assert_eq!(provider.name(), "resend");
    }
}
