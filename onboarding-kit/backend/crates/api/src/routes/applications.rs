//! Application lifecycle endpoints (§7): create draft, progressive save, submit,
//! and the role-scoped queue + detail views.

use std::time::Duration;

use axum::extract::{Path, Query, State};
use axum::http::StatusCode;
use axum::routing::{get, patch, post};
use axum::{Json, Router};
use chrono::{NaiveDate, Utc};
use onboardkit_core::{Actor, Role, StatusKind, TransitionAction, apply_transition};
use onboardkit_db::applications::{ApplicationFilter, NewApplication};
use onboardkit_db::clients::ClientPatch;
use onboardkit_db::{applications, clients, documents, events};
use onboardkit_integrations::Phone;
use serde::Deserialize;
use utoipa::ToSchema;
use uuid::Uuid;

use crate::auth::{AuthUser, RequireAgent};
use crate::error::{AppError, AppResult};
use crate::routes::dto::{
    ApplicationDetailResponse, ApplicationResponse, Meta, Paginated, PaginatedApplications,
    application_dto, client_dto, document_dto, event_dto,
};
use crate::routes::guard::{
    REQUIRED_DOC_TYPES, load_application, load_owned, load_owned_editable, map_transition_err,
};
use crate::state::AppState;

/// Presigned GET URLs for reading documents expire quickly (§11).
const GET_URL_TTL: Duration = Duration::from_secs(300);

// ---- Create ---------------------------------------------------------------

#[derive(Deserialize, ToSchema)]
pub(crate) struct CreateApplicationRequest {
    client_id: Uuid,
    product_code: String,
}

/// `POST /applications` (agent) — open a draft for one of the agent's clients.
#[utoipa::path(
    post,
    path = "/api/v1/applications",
    tag = "applications",
    security(("bearer_auth" = [])),
    request_body = CreateApplicationRequest,
    responses(
        (status = 201, description = "Draft application created", body = ApplicationResponse),
        (status = 404, description = "Client not found in tenant"),
        (status = 422, description = "Missing branch or product"),
    ),
)]
#[tracing::instrument(skip_all)]
pub(crate) async fn create(
    State(state): State<AppState>,
    RequireAgent(user): RequireAgent,
    Json(req): Json<CreateApplicationRequest>,
) -> AppResult<(StatusCode, Json<ApplicationResponse>)> {
    let Some(branch_id) = user.branch_id() else {
        return Err(AppError::Validation(
            "Your account is not assigned to a branch.".to_owned(),
        ));
    };
    let product_code = req.product_code.trim();
    if product_code.is_empty() {
        return Err(AppError::Validation("A product is required.".to_owned()));
    }

    // The client must exist within the tenant.
    if clients::get(&state.pool, user.tenant_id(), req.client_id)
        .await?
        .is_none()
    {
        return Err(AppError::NotFound);
    }

    let app = applications::create_draft(
        &state.pool,
        user.tenant_id(),
        &NewApplication {
            client_id: req.client_id,
            agent_id: user.user_id(),
            branch_id,
            product_code: product_code.to_owned(),
        },
    )
    .await?;
    tracing::info!(application_id = %app.id, "draft application created");
    Ok((StatusCode::CREATED, Json(application_dto(app))))
}

// ---- Progressive save -----------------------------------------------------

#[derive(Deserialize, ToSchema)]
pub(crate) struct PatchApplicationRequest {
    full_name: Option<String>,
    phone: Option<String>,
    national_id_number: Option<String>,
    kra_pin: Option<String>,
    date_of_birth: Option<NaiveDate>,
    address: Option<String>,
    #[schema(value_type = Option<Object>)]
    next_of_kin: Option<serde_json::Value>,
}

/// `PATCH /applications/:id` (agent owner, Draft/Returned only) — save one
/// section of the client's details. A dropped connection never loses prior work
/// because each section is persisted independently (§12).
#[utoipa::path(
    patch,
    path = "/api/v1/applications/{id}",
    tag = "applications",
    security(("bearer_auth" = [])),
    params(("id" = Uuid, Path, description = "Application id")),
    request_body = PatchApplicationRequest,
    responses(
        (status = 200, description = "Section saved; full detail returned", body = ApplicationDetailResponse),
        (status = 409, description = "Application no longer editable"),
        (status = 422, description = "Invalid phone or field"),
    ),
)]
#[tracing::instrument(skip_all)]
pub(crate) async fn patch_application(
    State(state): State<AppState>,
    RequireAgent(user): RequireAgent,
    Path(id): Path<Uuid>,
    Json(req): Json<PatchApplicationRequest>,
) -> AppResult<Json<ApplicationDetailResponse>> {
    let app = load_owned_editable(&state, &user, id).await?;

    // Normalize phone to E.164 (default region KE) before it is stored.
    let phone = match req
        .phone
        .as_deref()
        .map(str::trim)
        .filter(|p| !p.is_empty())
    {
        Some(raw) => Some(
            Phone::parse(raw)
                .map_err(|_| AppError::Validation("Invalid phone number.".to_owned()))?
                .as_str()
                .to_owned(),
        ),
        None => None,
    };

    let patch = ClientPatch {
        full_name: req.full_name.map(|s| s.trim().to_owned()),
        phone,
        national_id_number: req.national_id_number,
        kra_pin: req.kra_pin,
        date_of_birth: req.date_of_birth,
        address: req.address,
        next_of_kin: req.next_of_kin,
    };

    clients::patch(&state.pool, user.tenant_id(), app.client_id, &patch)
        .await
        .map_err(|e| match &e {
            sqlx::Error::Database(db) if db.is_unique_violation() => {
                AppError::Conflict("That phone number is already registered.".to_owned())
            }
            _ => AppError::from(e),
        })?;

    detail_response(&state, &app.id, &user).await
}

// ---- Submit ---------------------------------------------------------------

/// `POST /applications/:id/submit` (agent owner) — validate completeness and
/// transition Draft/Returned -> Submitted (§6).
#[utoipa::path(
    post,
    path = "/api/v1/applications/{id}/submit",
    tag = "applications",
    security(("bearer_auth" = [])),
    params(("id" = Uuid, Path, description = "Application id")),
    responses(
        (status = 200, description = "Application submitted", body = ApplicationResponse),
        (status = 409, description = "Not in a submittable state"),
        (status = 422, description = "Completeness check failed"),
    ),
)]
#[tracing::instrument(skip_all)]
pub(crate) async fn submit(
    State(state): State<AppState>,
    RequireAgent(user): RequireAgent,
    Path(id): Path<Uuid>,
) -> AppResult<Json<ApplicationResponse>> {
    let app = load_owned(&state, &user, id).await?;

    // Completeness mirrors the state machine's Draft->Submitted contract (§6).
    let processed = documents::count_processed_types(&state.pool, user.tenant_id(), app.id).await?;
    let required = i64::try_from(REQUIRED_DOC_TYPES.len()).unwrap_or(i64::MAX);
    if processed < required {
        return Err(AppError::Validation(
            "All four documents must be uploaded and processed before submitting.".to_owned(),
        ));
    }
    if app.otp_verified_at.is_none() {
        return Err(AppError::Validation(
            "The client's phone must be verified before submitting.".to_owned(),
        ));
    }
    if app.consent_at.is_none() {
        return Err(AppError::Validation(
            "Consent must be recorded before submitting.".to_owned(),
        ));
    }

    let actor = Actor::new(Role::Agent, true);
    apply_transition(app.current_status, TransitionAction::Submit, actor)
        .map_err(|e| map_transition_err(&e))?;

    events::record_submit(
        &state.pool,
        user.tenant_id(),
        app.id,
        user.user_id(),
        app.current_status,
        Utc::now(),
    )
    .await?;

    let updated = load_application(&state, user.tenant_id(), app.id).await?;
    tracing::info!(application_id = %app.id, "application submitted");
    Ok(Json(application_dto(updated)))
}

// ---- Queue + detail -------------------------------------------------------

#[derive(Deserialize)]
pub(crate) struct ListQuery {
    page: Option<i64>,
    per_page: Option<i64>,
    status: Option<StatusKind>,
    branch_id: Option<Uuid>,
    agent_id: Option<Uuid>,
}

/// `GET /applications` — the role-scoped queue (§7). Agents see their own
/// applications; reviewers see non-draft applications in their branch; admins
/// see the whole tenant.
#[utoipa::path(
    get,
    path = "/api/v1/applications",
    tag = "applications",
    security(("bearer_auth" = [])),
    params(
        ("page" = Option<i64>, Query, description = "1-based page (default 1)"),
        ("per_page" = Option<i64>, Query, description = "Page size, max 100 (default 20)"),
        ("status" = Option<String>, Query, description = "Filter by status"),
        ("branch_id" = Option<Uuid>, Query, description = "Admin-only branch filter"),
        ("agent_id" = Option<Uuid>, Query, description = "Admin-only agent filter"),
    ),
    responses((status = 200, description = "Role-scoped, paginated queue", body = PaginatedApplications)),
)]
#[tracing::instrument(skip_all)]
pub(crate) async fn list(
    State(state): State<AppState>,
    user: AuthUser,
    Query(q): Query<ListQuery>,
) -> AppResult<Json<Paginated<ApplicationResponse>>> {
    let page = q.page.unwrap_or(1).max(1);
    let per_page = q.per_page.unwrap_or(20).clamp(1, 100);
    let offset = (page - 1) * per_page;

    let mut filter = ApplicationFilter {
        status: q.status,
        ..ApplicationFilter::default()
    };
    match user.role() {
        Role::Agent => filter.agent_id = Some(user.user_id()),
        Role::Reviewer => {
            filter.branch_id = user.branch_id();
            filter.exclude_draft = true;
        }
        Role::Admin => {
            filter.branch_id = q.branch_id;
            filter.agent_id = q.agent_id;
        }
    }

    let total = applications::count(&state.pool, user.tenant_id(), &filter).await?;
    let rows = applications::list(&state.pool, user.tenant_id(), &filter, per_page, offset).await?;
    let data = rows.into_iter().map(application_dto).collect();

    Ok(Json(Paginated {
        data,
        meta: Meta {
            page,
            per_page,
            total,
        },
    }))
}

/// `GET /applications/:id` — full detail with short-lived presigned document
/// URLs (§7, §11).
#[utoipa::path(
    get,
    path = "/api/v1/applications/{id}",
    tag = "applications",
    security(("bearer_auth" = [])),
    params(("id" = Uuid, Path, description = "Application id")),
    responses(
        (status = 200, description = "Full application detail", body = ApplicationDetailResponse),
        (status = 404, description = "Not visible to the caller, or not found"),
    ),
)]
#[tracing::instrument(skip_all)]
pub(crate) async fn get_detail(
    State(state): State<AppState>,
    user: AuthUser,
    Path(id): Path<Uuid>,
) -> AppResult<Json<ApplicationDetailResponse>> {
    detail_response(&state, &id, &user).await
}

/// Authorize a read of `app` for `user`; 404 rather than 403 so nothing leaks.
fn authorize_view(app: &onboardkit_db::Application, user: &AuthUser) -> AppResult<()> {
    let allowed = match user.role() {
        Role::Admin => true,
        Role::Agent => app.agent_id == user.user_id(),
        Role::Reviewer => {
            user.branch_id() == Some(app.branch_id) && app.current_status != StatusKind::Draft
        }
    };
    if allowed {
        Ok(())
    } else {
        Err(AppError::NotFound)
    }
}

/// Build the full detail payload (shared by GET detail and PATCH responses).
async fn detail_response(
    state: &AppState,
    id: &Uuid,
    user: &AuthUser,
) -> AppResult<Json<ApplicationDetailResponse>> {
    let app = load_application(state, user.tenant_id(), *id).await?;
    authorize_view(&app, user)?;

    let client = clients::get(&state.pool, user.tenant_id(), app.client_id)
        .await?
        .ok_or(AppError::NotFound)?;
    let docs = documents::list(&state.pool, user.tenant_id(), app.id).await?;
    let event_rows = events::list(&state.pool, user.tenant_id(), app.id).await?;

    let mut document_dtos = Vec::with_capacity(docs.len());
    for doc in docs {
        let url = state
            .storage
            .presign_get(&doc.storage_key, GET_URL_TTL)
            .await
            .map_err(|e| AppError::Internal(anyhow::anyhow!(e)))?;
        let thumbnail_url = match &doc.thumbnail_key {
            Some(key) => Some(
                state
                    .storage
                    .presign_get(key, GET_URL_TTL)
                    .await
                    .map_err(|e| AppError::Internal(anyhow::anyhow!(e)))?,
            ),
            None => None,
        };
        document_dtos.push(document_dto(doc, url, thumbnail_url));
    }

    Ok(Json(ApplicationDetailResponse {
        application: application_dto(app),
        client: client_dto(client),
        documents: document_dtos,
        events: event_rows.into_iter().map(event_dto).collect(),
    }))
}

/// Routes owned by this module.
pub fn router() -> Router<AppState> {
    Router::new()
        .route("/applications", post(create).get(list))
        .route("/applications/{id}", get(get_detail))
        .route("/applications/{id}", patch(patch_application))
        .route("/applications/{id}/submit", post(submit))
}
