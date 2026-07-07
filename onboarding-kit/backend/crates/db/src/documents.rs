//! KYC document repository. Tenant-scoped (§4).

use sqlx::PgExecutor;
use uuid::Uuid;

use crate::models::KycDocument;

/// A confirmed upload to record.
#[derive(Debug, Clone)]
pub struct NewDocument {
    pub doc_type: String,
    pub storage_key: String,
    pub original_filename: String,
    pub content_type: String,
    pub size_bytes: i64,
}

/// Insert or replace the current document for an (application, doc_type).
/// Re-upload resets `processed`/`thumbnail_key` so the image job re-runs (§5).
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn upsert(
    exec: impl PgExecutor<'_>,
    tenant_id: Uuid,
    application_id: Uuid,
    doc: &NewDocument,
) -> Result<KycDocument, sqlx::Error> {
    sqlx::query_as!(
        KycDocument,
        r#"INSERT INTO kyc_documents
             (tenant_id, application_id, doc_type, storage_key, original_filename,
              content_type, size_bytes, processed, thumbnail_key)
           VALUES ($1, $2, $3, $4, $5, $6, $7, FALSE, NULL)
           ON CONFLICT (application_id, doc_type) DO UPDATE SET
             storage_key       = EXCLUDED.storage_key,
             original_filename = EXCLUDED.original_filename,
             content_type      = EXCLUDED.content_type,
             size_bytes        = EXCLUDED.size_bytes,
             processed         = FALSE,
             thumbnail_key     = NULL,
             uploaded_at       = now()
           RETURNING id, tenant_id, application_id, doc_type, storage_key,
                     original_filename, content_type, size_bytes, processed,
                     thumbnail_key, uploaded_at"#,
        tenant_id,
        application_id,
        doc.doc_type,
        doc.storage_key,
        doc.original_filename,
        doc.content_type,
        doc.size_bytes,
    )
    .fetch_one(exec)
    .await
}

/// Load a document by id (job path — id is unguessable).
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn get_by_id(
    exec: impl PgExecutor<'_>,
    id: Uuid,
) -> Result<Option<KycDocument>, sqlx::Error> {
    sqlx::query_as!(
        KycDocument,
        r#"SELECT id, tenant_id, application_id, doc_type, storage_key,
                  original_filename, content_type, size_bytes, processed,
                  thumbnail_key, uploaded_at
           FROM kyc_documents WHERE id = $1"#,
        id,
    )
    .fetch_optional(exec)
    .await
}

/// List all documents for an application.
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn list(
    exec: impl PgExecutor<'_>,
    tenant_id: Uuid,
    application_id: Uuid,
) -> Result<Vec<KycDocument>, sqlx::Error> {
    sqlx::query_as!(
        KycDocument,
        r#"SELECT id, tenant_id, application_id, doc_type, storage_key,
                  original_filename, content_type, size_bytes, processed,
                  thumbnail_key, uploaded_at
           FROM kyc_documents
           WHERE tenant_id = $1 AND application_id = $2
           ORDER BY doc_type"#,
        tenant_id,
        application_id,
    )
    .fetch_all(exec)
    .await
}

/// Count distinct processed document types for an application (completeness).
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn count_processed_types(
    exec: impl PgExecutor<'_>,
    tenant_id: Uuid,
    application_id: Uuid,
) -> Result<i64, sqlx::Error> {
    let row = sqlx::query!(
        r#"SELECT COUNT(DISTINCT doc_type) AS "count!"
           FROM kyc_documents
           WHERE tenant_id = $1 AND application_id = $2 AND processed = TRUE"#,
        tenant_id,
        application_id,
    )
    .fetch_one(exec)
    .await?;
    Ok(row.count)
}

/// Mark a document processed and attach its thumbnail key (job path). Idempotent.
///
/// # Errors
/// Returns [`sqlx::Error`] on failure.
pub async fn mark_processed(
    exec: impl PgExecutor<'_>,
    id: Uuid,
    thumbnail_key: Option<&str>,
) -> Result<(), sqlx::Error> {
    sqlx::query!(
        r#"UPDATE kyc_documents SET processed = TRUE, thumbnail_key = $2 WHERE id = $1"#,
        id,
        thumbnail_key,
    )
    .execute(exec)
    .await?;
    Ok(())
}
