//! OpenAPI 3.1 document for the whole API (CLAUDE.md §7).
//!
//! Built from the `#[utoipa::path]` annotations on each handler and the
//! `ToSchema` derives on the DTOs. Served as JSON at `/api/v1/openapi.json` so
//! the frontends can generate their clients (`openapi-typescript` for office,
//! `openapi-generator` dart-dio for agent) instead of hand-writing API types.

use utoipa::openapi::security::{HttpAuthScheme, HttpBuilder, SecurityScheme};
use utoipa::{Modify, OpenApi};

use crate::routes::{
    admin, applications, auth, clients, consent, documents, dto, exports, health, otp, reports,
    review, session,
};

/// Adds the `bearer_auth` security scheme (JWT access token) that protected
/// paths reference via `security(("bearer_auth" = []))`.
struct SecurityAddon;

impl Modify for SecurityAddon {
    fn modify(&self, openapi: &mut utoipa::openapi::OpenApi) {
        if let Some(components) = openapi.components.as_mut() {
            components.add_security_scheme(
                "bearer_auth",
                SecurityScheme::Http(
                    HttpBuilder::new()
                        .scheme(HttpAuthScheme::Bearer)
                        .bearer_format("JWT")
                        .build(),
                ),
            );
        }
    }
}

/// The aggregated OpenAPI document.
#[derive(OpenApi)]
#[openapi(
    info(
        title = "OnboardKit API",
        version = "0.1.0",
        description = "Client onboarding & KYC portal for Kenyan insurers and MFIs."
    ),
    modifiers(&SecurityAddon),
    tags(
        (name = "health", description = "Liveness / readiness"),
        (name = "auth", description = "Login, refresh, logout"),
        (name = "session", description = "Authenticated caller identity"),
        (name = "clients", description = "Client shells"),
        (name = "applications", description = "Onboarding lifecycle + queue"),
        (name = "documents", description = "KYC document upload flow"),
        (name = "otp", description = "Client phone verification"),
        (name = "review", description = "Reviewer transitions"),
        (name = "reports", description = "Admin analytics"),
        (name = "exports", description = "Approved-client exports"),
        (name = "admin", description = "Branch / user / product CRUD"),
    ),
    paths(
        health::health,
        session::me,
        auth::login,
        auth::refresh,
        auth::logout,
        clients::create,
        applications::create,
        applications::list,
        applications::get_detail,
        applications::patch_application,
        applications::submit,
        documents::presign,
        documents::confirm,
        otp::send,
        otp::verify,
        consent::consent,
        review::review,
        reports::summary,
        exports::approved_clients,
        admin::overview,
        admin::list_branches,
        admin::create_branch,
        admin::update_branch,
        admin::list_products,
        admin::create_product,
        admin::update_product,
        admin::list_users,
        admin::create_user,
        admin::update_user,
    ),
    components(schemas(
        dto::ClientResponse,
        dto::ApplicationResponse,
        dto::DocumentResponse,
        dto::EventResponse,
        dto::ApplicationDetailResponse,
        dto::Meta,
        dto::PaginatedApplications,
        health::HealthResponse,
        session::MeResponse,
        auth::LoginRequest,
        auth::RefreshRequest,
        auth::LogoutRequest,
        auth::TokenResponse,
        clients::CreateClientRequest,
        applications::CreateApplicationRequest,
        applications::PatchApplicationRequest,
        documents::PresignRequest,
        documents::PresignResponse,
        documents::ConfirmRequest,
        documents::ConfirmResponse,
        otp::SendResponse,
        otp::VerifyRequest,
        consent::ConsentRequest,
        review::ReviewAction,
        review::ReviewRequest,
        reports::AgentStat,
        reports::BranchStat,
        reports::RejectionReason,
        reports::Summary,
        admin::AdminOverview,
        admin::BranchDto,
        admin::CreateBranch,
        admin::UpdateBranch,
        admin::ProductDto,
        admin::CreateProduct,
        admin::UpdateProduct,
        admin::UserDto,
        admin::CreateUser,
        admin::UpdateUser,
    )),
)]
pub struct ApiDoc;

/// `GET /api/v1/openapi.json` — serve the generated spec.
pub async fn openapi_json() -> axum::Json<utoipa::openapi::OpenApi> {
    axum::Json(ApiDoc::openapi())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn spec_builds_and_covers_the_api() {
        let doc = ApiDoc::openapi();
        // A representative path from each area is present.
        for path in [
            "/api/v1/health",
            "/api/v1/auth/login",
            "/api/v1/applications",
            "/api/v1/applications/{id}/review",
            "/api/v1/reports/summary",
            "/api/v1/branches",
        ] {
            assert!(doc.paths.paths.contains_key(path), "missing path {path}");
        }
        // The bearer security scheme is registered.
        let components = doc.components.expect("components present");
        assert!(components.security_schemes.contains_key("bearer_auth"));
        // Core DTO schemas are registered for client generation.
        for schema in [
            "ApplicationResponse",
            "TokenResponse",
            "PaginatedApplications",
        ] {
            assert!(
                components.schemas.contains_key(schema),
                "missing schema {schema}"
            );
        }
    }
}
