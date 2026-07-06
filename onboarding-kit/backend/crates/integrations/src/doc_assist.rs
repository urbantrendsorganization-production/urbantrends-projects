//! LLM-assisted KYC field extraction (opt-in — CLAUDE.md §1 scope note).
//!
//! **Assistive only.** This reads a KYC document image and returns *suggested*
//! field values to pre-fill the onboarding form. A human reviewer still makes
//! every approve/reject decision — nothing here decides an application. §1 puts
//! *automated* ID verification out of MVP scope; this stays on the right side of
//! that line by producing suggestions a person edits and confirms.
//!
//! Off by default. [`extractor_from_env`] returns [`DisabledExtractor`] unless
//! `LLM_DOC_ASSIST=true`; the real path calls the Anthropic Messages API
//! (`claude-opus-4-8` by default) over raw HTTP with a **structured-output**
//! schema, so the response is guaranteed-parseable JSON.
//!
//! **Data-protection note (Kenya DPA 2019):** enabling this sends the document
//! image and any text on it (national ID number, KRA PIN, name, DOB) to an
//! external processor. That requires a lawful basis and belongs in the client
//! consent terms. This module never logs the image, the API key, the request or
//! response bodies, or any extracted field — only the doc kind and pass/fail.

use base64::Engine;
use serde::Deserialize;

/// Which KYC document this is — drives the extraction prompt. Mirrors the
/// `kyc_documents.doc_type` values (§5).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DocKind {
    IdFront,
    IdBack,
    Selfie,
    AddressProof,
}

impl DocKind {
    /// Human guidance appended to the prompt for this document type.
    fn guidance(self) -> &'static str {
        match self {
            Self::IdFront => {
                "This is the FRONT of a Kenyan national ID card. Read the full \
                 name, the ID (serial) number, and the date of birth."
            }
            Self::IdBack => {
                "This is the BACK of a Kenyan national ID card. It usually has a \
                 district/place of issue and a serial; personal fields are rare."
            }
            Self::Selfie => {
                "This is a selfie photo. It carries no text fields — return null \
                 for every field."
            }
            Self::AddressProof => {
                "This is a proof-of-address document (e.g. a utility bill). Read \
                 the account holder's name and the postal/physical address; a \
                 KRA PIN may appear on some bills."
            }
        }
    }
}

/// Suggested field values extracted from a document. **All optional** — the
/// model returns `null` for anything absent or illegible; nothing here is
/// authoritative. These are PII: never log them.
#[derive(Debug, Clone, Default, PartialEq, Eq, Deserialize)]
pub struct ExtractedFields {
    pub full_name: Option<String>,
    pub national_id_number: Option<String>,
    /// As printed on the document (ISO `YYYY-MM-DD` when the model can normalise
    /// it). Kept as a string suggestion — parsing/validation is the caller's job.
    pub date_of_birth: Option<String>,
    pub kra_pin: Option<String>,
    pub address: Option<String>,
}

/// Errors from the assist path.
#[derive(Debug, thiserror::Error)]
pub enum DocAssistError {
    /// The feature is off (`LLM_DOC_ASSIST` not `true`). Callers treat this as
    /// "no suggestion available" and carry on — it is not a failure.
    #[error("document assist is disabled")]
    Disabled,
    #[error("unsupported document media type: {0}")]
    UnsupportedMedia(String),
    #[error("anthropic request failed: {0}")]
    Request(String),
    #[error("anthropic response could not be parsed")]
    BadResponse,
}

/// Extracts suggested fields from a KYC document image.
#[async_trait::async_trait]
pub trait DocExtractor: Send + Sync {
    /// `media_type` is the sniffed MIME (e.g. `image/jpeg`, `application/pdf`).
    async fn extract(
        &self,
        kind: DocKind,
        bytes: &[u8],
        media_type: &str,
    ) -> Result<ExtractedFields, DocAssistError>;
}

/// The default: does nothing, so the feature is inert unless explicitly enabled.
pub struct DisabledExtractor;

#[async_trait::async_trait]
impl DocExtractor for DisabledExtractor {
    async fn extract(
        &self,
        _kind: DocKind,
        _bytes: &[u8],
        _media_type: &str,
    ) -> Result<ExtractedFields, DocAssistError> {
        Err(DocAssistError::Disabled)
    }
}

/// Returns fixed fields without any network call — for tests and demo mode.
pub struct MockExtractor;

#[async_trait::async_trait]
impl DocExtractor for MockExtractor {
    async fn extract(
        &self,
        kind: DocKind,
        _bytes: &[u8],
        _media_type: &str,
    ) -> Result<ExtractedFields, DocAssistError> {
        tracing::info!(kind = ?kind, "MOCK doc-assist (no API call)");
        Ok(match kind {
            DocKind::IdFront => ExtractedFields {
                full_name: Some("Jane Wanjiku Kamau".into()),
                national_id_number: Some("12345678".into()),
                date_of_birth: Some("1990-04-12".into()),
                ..Default::default()
            },
            _ => ExtractedFields::default(),
        })
    }
}

/// Real extractor backed by the Anthropic Messages API (raw HTTP — there is no
/// official Rust SDK). Uses structured outputs so the reply is valid JSON.
pub struct AnthropicExtractor {
    http: reqwest::Client,
    api_key: String,
    model: String,
}

impl AnthropicExtractor {
    const ENDPOINT: &'static str = "https://api.anthropic.com/v1/messages";
    const API_VERSION: &'static str = "2023-06-01";
    const DEFAULT_MODEL: &'static str = "claude-opus-4-8";

    /// Build from env, or `None` if `ANTHROPIC_API_KEY` is unset/blank.
    #[must_use]
    pub fn from_env() -> Option<Self> {
        let get = |k: &str| std::env::var(k).ok().filter(|v| !v.trim().is_empty());
        Some(Self {
            http: reqwest::Client::new(),
            api_key: get("ANTHROPIC_API_KEY")?,
            model: get("LLM_DOC_ASSIST_MODEL").unwrap_or_else(|| Self::DEFAULT_MODEL.to_owned()),
        })
    }

    /// JSON Schema constraining the reply (all fields nullable; strict object).
    fn schema() -> serde_json::Value {
        let nullable = serde_json::json!({ "type": ["string", "null"] });
        serde_json::json!({
            "type": "object",
            "properties": {
                "full_name": nullable,
                "national_id_number": nullable,
                "date_of_birth": nullable,
                "kra_pin": nullable,
                "address": nullable,
            },
            "required": [
                "full_name", "national_id_number",
                "date_of_birth", "kra_pin", "address",
            ],
            "additionalProperties": false,
        })
    }

    /// The document content block: `image` for photos, `document` for PDFs
    /// (address proofs). Other media types are rejected.
    fn source_block(bytes: &[u8], media_type: &str) -> Result<serde_json::Value, DocAssistError> {
        let data = base64::engine::general_purpose::STANDARD.encode(bytes);
        let source = serde_json::json!({
            "type": "base64", "media_type": media_type, "data": data,
        });
        if media_type.starts_with("image/") {
            Ok(serde_json::json!({ "type": "image", "source": source }))
        } else if media_type == "application/pdf" {
            Ok(serde_json::json!({ "type": "document", "source": source }))
        } else {
            Err(DocAssistError::UnsupportedMedia(media_type.to_owned()))
        }
    }

    /// Pull the first `text` content block out of a Messages API response and
    /// parse it as [`ExtractedFields`]. Structured outputs guarantee the first
    /// text block is schema-valid JSON.
    fn parse_response(body: &serde_json::Value) -> Result<ExtractedFields, DocAssistError> {
        let text = body
            .get("content")
            .and_then(serde_json::Value::as_array)
            .into_iter()
            .flatten()
            .find(|b| b.get("type").and_then(serde_json::Value::as_str) == Some("text"))
            .and_then(|b| b.get("text"))
            .and_then(serde_json::Value::as_str)
            .ok_or(DocAssistError::BadResponse)?;
        serde_json::from_str(text).map_err(|_| DocAssistError::BadResponse)
    }
}

#[async_trait::async_trait]
impl DocExtractor for AnthropicExtractor {
    #[tracing::instrument(skip(self, bytes, media_type), fields(kind = ?kind))]
    async fn extract(
        &self,
        kind: DocKind,
        bytes: &[u8],
        media_type: &str,
    ) -> Result<ExtractedFields, DocAssistError> {
        let source = Self::source_block(bytes, media_type)?;
        let instruction = format!(
            "{}\n\nExtract the client's KYC fields from this document into the \
             required JSON shape. Use null for any field that is absent, \
             illegible, or does not apply to this document. Do NOT guess or \
             invent values — a human reviewer will verify every field, so a null \
             is safer than a wrong guess.",
            kind.guidance()
        );

        // Structured output only (no `thinking`/`effort`): the JSON schema
        // constrains the reply, and omitting effort keeps the request valid
        // across opus/sonnet/haiku (effort 400s on haiku).
        let request = serde_json::json!({
            "model": self.model,
            "max_tokens": 1024,
            "output_config": { "format": { "type": "json_schema", "schema": Self::schema() } },
            "messages": [{
                "role": "user",
                "content": [ source, { "type": "text", "text": instruction } ],
            }],
        });

        let resp = self
            .http
            .post(Self::ENDPOINT)
            .header("x-api-key", &self.api_key)
            .header("anthropic-version", Self::API_VERSION)
            .header("content-type", "application/json")
            .json(&request)
            .send()
            .await
            .map_err(|e| DocAssistError::Request(format!("transport: {e}")))?;

        if !resp.status().is_success() {
            // Log the status only — never the body (it can echo document text).
            let status = resp.status();
            tracing::warn!(%status, "doc-assist api returned non-success");
            return Err(DocAssistError::Request(format!("status {status}")));
        }

        let body: serde_json::Value = resp
            .json()
            .await
            .map_err(|e| DocAssistError::Request(format!("decode: {e}")))?;
        let fields = Self::parse_response(&body)?;
        // Count populated fields for observability — never the values (PII).
        let populated = [
            &fields.full_name,
            &fields.national_id_number,
            &fields.date_of_birth,
            &fields.kra_pin,
            &fields.address,
        ]
        .iter()
        .filter(|v| v.is_some())
        .count();
        tracing::info!(populated, "doc-assist extraction complete");
        Ok(fields)
    }
}

/// Build the extractor from the environment.
///
/// `LLM_DOC_ASSIST=true` wires the [`AnthropicExtractor`] when
/// `ANTHROPIC_API_KEY` is set; anything else (the default) yields
/// [`DisabledExtractor`], so the feature is inert until deliberately turned on.
#[must_use]
pub fn extractor_from_env() -> std::sync::Arc<dyn DocExtractor> {
    use std::sync::Arc;
    let enabled = std::env::var("LLM_DOC_ASSIST").is_ok_and(|v| v.eq_ignore_ascii_case("true"));
    if !enabled {
        return Arc::new(DisabledExtractor);
    }
    if let Some(extractor) = AnthropicExtractor::from_env() {
        tracing::info!(model = %extractor.model, "doc-assist enabled");
        Arc::new(extractor)
    } else {
        tracing::warn!("LLM_DOC_ASSIST=true but ANTHROPIC_API_KEY unset; disabling doc-assist");
        Arc::new(DisabledExtractor)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn disabled_returns_disabled() {
        let err = DisabledExtractor
            .extract(DocKind::IdFront, b"", "image/jpeg")
            .await
            .unwrap_err();
        assert!(matches!(err, DocAssistError::Disabled));
    }

    #[tokio::test]
    async fn mock_returns_id_front_fields() {
        let fields = MockExtractor
            .extract(DocKind::IdFront, b"x", "image/jpeg")
            .await
            .unwrap();
        assert_eq!(fields.national_id_number.as_deref(), Some("12345678"));
        // Selfie carries no fields.
        let selfie = MockExtractor
            .extract(DocKind::Selfie, b"x", "image/jpeg")
            .await
            .unwrap();
        assert_eq!(selfie, ExtractedFields::default());
    }

    #[test]
    fn image_and_pdf_blocks_build_pdf_rejects_other() {
        let img = AnthropicExtractor::source_block(b"abc", "image/png").unwrap();
        assert_eq!(img["type"], "image");
        let pdf = AnthropicExtractor::source_block(b"abc", "application/pdf").unwrap();
        assert_eq!(pdf["type"], "document");
        // base64 of "abc"
        assert_eq!(pdf["source"]["data"], "YWJj");
        assert!(matches!(
            AnthropicExtractor::source_block(b"abc", "text/plain"),
            Err(DocAssistError::UnsupportedMedia(_))
        ));
    }

    #[test]
    fn parses_structured_text_block() {
        let body = serde_json::json!({
            "content": [
                { "type": "text", "text": "{\"full_name\":\"Amina Yusuf\",\
                    \"national_id_number\":\"87654321\",\"date_of_birth\":null,\
                    \"kra_pin\":null,\"address\":null}" }
            ]
        });
        let fields = AnthropicExtractor::parse_response(&body).unwrap();
        assert_eq!(fields.full_name.as_deref(), Some("Amina Yusuf"));
        assert_eq!(fields.national_id_number.as_deref(), Some("87654321"));
        assert!(fields.date_of_birth.is_none());
    }

    #[test]
    fn parse_response_skips_thinking_finds_text() {
        let body = serde_json::json!({
            "content": [
                { "type": "thinking", "thinking": "..." },
                { "type": "text", "text": "{\"full_name\":null,\
                    \"national_id_number\":null,\"date_of_birth\":null,\
                    \"kra_pin\":null,\"address\":null}" }
            ]
        });
        let fields = AnthropicExtractor::parse_response(&body).unwrap();
        assert_eq!(fields, ExtractedFields::default());
    }

    #[test]
    fn parse_response_errors_without_text_block() {
        let body = serde_json::json!({ "content": [] });
        assert!(matches!(
            AnthropicExtractor::parse_response(&body),
            Err(DocAssistError::BadResponse)
        ));
    }
}
