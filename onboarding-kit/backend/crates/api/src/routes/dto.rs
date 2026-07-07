//! Shared response DTOs for the onboarding endpoints, and mappers from db rows.

use chrono::{DateTime, NaiveDate, Utc};
use onboardkit_core::StatusKind;
use onboardkit_db::{Application, ApplicationEvent, Client, KycDocument};
use serde::Serialize;
use utoipa::ToSchema;
use uuid::Uuid;

/// Generic paginated envelope (§7).
#[derive(Serialize, ToSchema)]
pub struct Paginated<T> {
    pub data: Vec<T>,
    pub meta: Meta,
}

#[derive(Serialize, ToSchema)]
pub struct Meta {
    pub page: i64,
    pub per_page: i64,
    pub total: i64,
}

/// Concrete instantiation of [`Paginated`] for the applications queue, so the
/// OpenAPI schema is nameable without generic-schema plumbing. Same wire shape
/// as `Paginated<ApplicationResponse>`.
#[derive(Serialize, ToSchema)]
pub struct PaginatedApplications {
    pub data: Vec<ApplicationResponse>,
    pub meta: Meta,
}

#[derive(Serialize, ToSchema)]
pub struct ClientResponse {
    pub id: Uuid,
    pub full_name: String,
    pub phone: Option<String>,
    pub national_id_number: Option<String>,
    pub kra_pin: Option<String>,
    pub date_of_birth: Option<NaiveDate>,
    pub address: Option<String>,
    #[schema(value_type = Option<Object>)]
    pub next_of_kin: Option<serde_json::Value>,
    pub client_number: Option<String>,
}

#[must_use]
pub fn client_dto(c: Client) -> ClientResponse {
    ClientResponse {
        id: c.id,
        full_name: c.full_name,
        phone: c.phone,
        national_id_number: c.national_id_number,
        kra_pin: c.kra_pin,
        date_of_birth: c.date_of_birth,
        address: c.address,
        next_of_kin: c.next_of_kin,
        client_number: c.client_number,
    }
}

#[derive(Serialize, ToSchema)]
pub struct ApplicationResponse {
    pub id: Uuid,
    pub client_id: Uuid,
    pub agent_id: Uuid,
    pub branch_id: Uuid,
    pub product_code: String,
    #[schema(value_type = String)]
    pub status: StatusKind,
    pub otp_verified: bool,
    pub consent_given: bool,
    pub consent_terms_version: Option<String>,
    pub submitted_at: Option<DateTime<Utc>>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[must_use]
pub fn application_dto(a: Application) -> ApplicationResponse {
    ApplicationResponse {
        id: a.id,
        client_id: a.client_id,
        agent_id: a.agent_id,
        branch_id: a.branch_id,
        product_code: a.product_code,
        status: a.current_status,
        otp_verified: a.otp_verified_at.is_some(),
        consent_given: a.consent_at.is_some(),
        consent_terms_version: a.consent_terms_version,
        submitted_at: a.submitted_at,
        created_at: a.created_at,
        updated_at: a.updated_at,
    }
}

#[derive(Serialize, ToSchema)]
pub struct DocumentResponse {
    pub id: Uuid,
    pub doc_type: String,
    pub content_type: String,
    pub size_bytes: i64,
    pub processed: bool,
    /// Short-lived presigned GET URL (≤5 min).
    pub url: String,
    pub thumbnail_url: Option<String>,
    pub uploaded_at: DateTime<Utc>,
}

#[must_use]
pub fn document_dto(
    d: KycDocument,
    url: String,
    thumbnail_url: Option<String>,
) -> DocumentResponse {
    DocumentResponse {
        id: d.id,
        doc_type: d.doc_type,
        content_type: d.content_type,
        size_bytes: d.size_bytes,
        processed: d.processed,
        url,
        thumbnail_url,
        uploaded_at: d.uploaded_at,
    }
}

#[derive(Serialize, ToSchema)]
pub struct EventResponse {
    pub from_status: Option<String>,
    pub to_status: String,
    pub reason: Option<String>,
    pub created_at: DateTime<Utc>,
}

#[must_use]
pub fn event_dto(e: ApplicationEvent) -> EventResponse {
    EventResponse {
        from_status: e.from_status,
        to_status: e.to_status,
        reason: e.reason,
        created_at: e.created_at,
    }
}

/// Full application detail returned by `GET /applications/:id`.
#[derive(Serialize, ToSchema)]
pub struct ApplicationDetailResponse {
    pub application: ApplicationResponse,
    pub client: ClientResponse,
    pub documents: Vec<DocumentResponse>,
    pub events: Vec<EventResponse>,
}
