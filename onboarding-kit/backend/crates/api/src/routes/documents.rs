//! KYC document upload flow (§7, §11): presign a PUT, then confirm the upload
//! after server-side validation (existence, size, magic-byte MIME sniff) and
//! enqueue the `process_image` job.

use std::time::Duration;

use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::routing::post;
use axum::{Json, Router};
use onboardkit_core::jobs::{ProcessImagePayload, job_type};
use onboardkit_db::documents::NewDocument;
use onboardkit_db::{documents, jobs};
use onboardkit_integrations::{mime, storage};
use serde::{Deserialize, Serialize};
use utoipa::ToSchema;
use uuid::Uuid;

use crate::auth::RequireAgent;
use crate::error::{AppError, AppResult};
use crate::routes::guard::{REQUIRED_DOC_TYPES, load_owned_editable};
use crate::state::AppState;

/// Presigned PUT URLs expire quickly (§11).
const PUT_URL_TTL: Duration = Duration::from_secs(600);
/// Hard cap on a single upload (§11).
const MAX_UPLOAD_BYTES: i64 = 10 * 1024 * 1024;
/// Enough leading bytes for a reliable magic-byte sniff.
const SNIFF_BYTES: u64 = 512;

fn validate_doc_type(doc_type: &str) -> AppResult<()> {
    if REQUIRED_DOC_TYPES.contains(&doc_type) {
        Ok(())
    } else {
        Err(AppError::Validation("Unknown document type.".to_owned()))
    }
}

// ---- Presign --------------------------------------------------------------

#[derive(Deserialize, ToSchema)]
pub(crate) struct PresignRequest {
    doc_type: String,
    content_type: String,
}

#[derive(Serialize, ToSchema)]
pub(crate) struct PresignResponse {
    url: String,
    storage_key: String,
    expires_in: u64,
}

/// `POST /applications/:id/documents/presign` — a short-lived PUT URL the client
/// uploads to directly. The content type is pinned into the signature; real
/// validation happens on confirm.
#[utoipa::path(
    post,
    path = "/api/v1/applications/{id}/documents/presign",
    tag = "documents",
    security(("bearer_auth" = [])),
    params(("id" = Uuid, Path, description = "Application id")),
    request_body = PresignRequest,
    responses(
        (status = 200, description = "Presigned PUT URL + storage key", body = PresignResponse),
        (status = 422, description = "Unknown doc type or disallowed content type"),
    ),
)]
#[tracing::instrument(skip_all)]
pub(crate) async fn presign(
    State(state): State<AppState>,
    RequireAgent(user): RequireAgent,
    Path(id): Path<Uuid>,
    Json(req): Json<PresignRequest>,
) -> AppResult<Json<PresignResponse>> {
    let app = load_owned_editable(&state, &user, id).await?;
    validate_doc_type(&req.doc_type)?;
    if !mime::is_allowed_for(&req.doc_type, &req.content_type) {
        return Err(AppError::Validation(
            "That file type is not allowed for this document.".to_owned(),
        ));
    }

    let ext = mime::extension_for(&req.content_type);
    let key = storage::document_key(user.tenant_id(), app.id, &req.doc_type, ext);
    let url = state
        .storage
        .presign_put(&key, &req.content_type, PUT_URL_TTL)
        .await
        .map_err(|e| AppError::Internal(anyhow::anyhow!(e)))?;

    Ok(Json(PresignResponse {
        url,
        storage_key: key,
        expires_in: PUT_URL_TTL.as_secs(),
    }))
}

// ---- Confirm --------------------------------------------------------------

#[derive(Deserialize, ToSchema)]
pub(crate) struct ConfirmRequest {
    doc_type: String,
    storage_key: String,
    original_filename: String,
}

#[derive(Serialize, ToSchema)]
pub(crate) struct ConfirmResponse {
    id: Uuid,
    doc_type: String,
    processed: bool,
}

/// `POST /applications/:id/documents/confirm` — verify the uploaded object
/// (exists, size, sniffed MIME), record it, and enqueue image processing.
#[utoipa::path(
    post,
    path = "/api/v1/applications/{id}/documents/confirm",
    tag = "documents",
    security(("bearer_auth" = [])),
    params(("id" = Uuid, Path, description = "Application id")),
    request_body = ConfirmRequest,
    responses(
        (status = 201, description = "Document recorded; processing enqueued", body = ConfirmResponse),
        (status = 422, description = "Object missing, wrong size, or disallowed type"),
    ),
)]
#[tracing::instrument(skip_all)]
pub(crate) async fn confirm(
    State(state): State<AppState>,
    RequireAgent(user): RequireAgent,
    Path(id): Path<Uuid>,
    Json(req): Json<ConfirmRequest>,
) -> AppResult<(StatusCode, Json<ConfirmResponse>)> {
    let app = load_owned_editable(&state, &user, id).await?;
    validate_doc_type(&req.doc_type)?;

    // The key must belong to this tenant/application — never trust the client.
    let expected_prefix = format!("tenants/{}/applications/{}/", user.tenant_id(), app.id);
    if !req.storage_key.starts_with(&expected_prefix) {
        return Err(AppError::Validation("Invalid storage key.".to_owned()));
    }

    let meta = state
        .storage
        .head(&req.storage_key)
        .await
        .map_err(|e| AppError::Internal(anyhow::anyhow!(e)))?
        .ok_or_else(|| AppError::Validation("Upload not found. Please retry.".to_owned()))?;
    if meta.size_bytes <= 0 || meta.size_bytes > MAX_UPLOAD_BYTES {
        return Err(AppError::Validation(
            "File is empty or too large.".to_owned(),
        ));
    }

    let head_bytes = state
        .storage
        .get_prefix(&req.storage_key, SNIFF_BYTES)
        .await
        .map_err(|e| AppError::Internal(anyhow::anyhow!(e)))?;
    let sniffed = mime::sniff(&head_bytes)
        .ok_or_else(|| AppError::Validation("Unrecognized file type.".to_owned()))?;
    if !mime::is_allowed_for(&req.doc_type, sniffed) {
        return Err(AppError::Validation(
            "That file type is not allowed for this document.".to_owned(),
        ));
    }

    // Record the document and enqueue processing atomically.
    let mut tx = state.pool.begin().await?;
    let doc = documents::upsert(
        &mut *tx,
        user.tenant_id(),
        app.id,
        &NewDocument {
            doc_type: req.doc_type.clone(),
            storage_key: req.storage_key,
            original_filename: req.original_filename,
            content_type: sniffed.to_owned(),
            size_bytes: meta.size_bytes,
        },
    )
    .await?;
    let payload = serde_json::to_value(ProcessImagePayload {
        document_id: doc.id,
    })
    .map_err(|e| AppError::Internal(e.into()))?;
    jobs::enqueue(&mut *tx, job_type::PROCESS_IMAGE, payload).await?;
    tx.commit().await?;

    tracing::info!(document_id = %doc.id, doc_type = %doc.doc_type, "document confirmed");
    Ok((
        StatusCode::CREATED,
        Json(ConfirmResponse {
            id: doc.id,
            doc_type: doc.doc_type,
            processed: doc.processed,
        }),
    ))
}

/// Routes owned by this module.
pub fn router() -> Router<AppState> {
    Router::new()
        .route("/applications/{id}/documents/presign", post(presign))
        .route("/applications/{id}/documents/confirm", post(confirm))
}
