//! S3-compatible object storage (CLAUDE.md §11).
//!
//! MinIO in dev, Hetzner Object Storage in prod, via `aws-sdk-s3` with a custom
//! endpoint and path-style addressing. KYC documents are never public: uploads
//! use short-lived presigned PUTs (≤10 min), reads use short-lived presigned
//! GETs (≤5 min). Size is enforced at confirm time (a SigV4 query-presigned PUT
//! cannot bound the body length); content-type is pinned into the presign.

use std::time::Duration;

use aws_sdk_s3::config::{BehaviorVersion, Credentials, Region};
use aws_sdk_s3::presigning::PresigningConfig;
use aws_sdk_s3::primitives::ByteStream;
use uuid::Uuid;

/// Connection settings for the object store.
#[derive(Debug, Clone)]
pub struct StorageConfig {
    pub endpoint: String,
    pub region: String,
    pub bucket: String,
    pub access_key_id: String,
    pub secret_access_key: String,
    pub force_path_style: bool,
}

/// Metadata returned by [`ObjectStore::head`].
#[derive(Debug, Clone)]
pub struct ObjectMeta {
    pub size_bytes: i64,
    pub content_type: Option<String>,
}

/// Errors from the object store.
#[derive(Debug, thiserror::Error)]
pub enum StorageError {
    #[error("presigning failed: {0}")]
    Presign(String),
    #[error("object storage error: {0}")]
    S3(String),
}

/// A handle to a single bucket in an S3-compatible store.
#[derive(Clone)]
pub struct ObjectStore {
    client: aws_sdk_s3::Client,
    bucket: String,
}

impl ObjectStore {
    /// Build a client from configuration. Does not perform any network I/O.
    #[must_use]
    pub fn new(config: &StorageConfig) -> Self {
        let creds = Credentials::new(
            &config.access_key_id,
            &config.secret_access_key,
            None,
            None,
            "onboardkit-static",
        );
        let conf = aws_sdk_s3::config::Builder::new()
            .behavior_version(BehaviorVersion::latest())
            .region(Region::new(config.region.clone()))
            .endpoint_url(&config.endpoint)
            .credentials_provider(creds)
            .force_path_style(config.force_path_style)
            // Manual `Builder::new()` (vs `aws_config::load`) does not install a
            // sleep impl; retry/timeout config requires one or construction panics.
            .sleep_impl(aws_sdk_s3::config::SharedAsyncSleep::new(
                aws_smithy_async::rt::sleep::TokioSleep::new(),
            ))
            .build();
        Self {
            client: aws_sdk_s3::Client::from_conf(conf),
            bucket: config.bucket.clone(),
        }
    }

    /// Create the bucket if it does not already exist (dev convenience for
    /// MinIO). Idempotent.
    ///
    /// # Errors
    /// [`StorageError::S3`] on an unexpected failure.
    pub async fn ensure_bucket(&self) -> Result<(), StorageError> {
        if self
            .client
            .head_bucket()
            .bucket(&self.bucket)
            .send()
            .await
            .is_ok()
        {
            return Ok(());
        }
        match self
            .client
            .create_bucket()
            .bucket(&self.bucket)
            .send()
            .await
        {
            Ok(_) => Ok(()),
            // Racing/existing bucket is fine.
            Err(err) => {
                let msg = err.into_service_error().to_string();
                if msg.contains("BucketAlreadyOwnedByYou") || msg.contains("BucketAlreadyExists") {
                    Ok(())
                } else {
                    Err(StorageError::S3(msg))
                }
            }
        }
    }

    /// A presigned PUT URL the client uses to upload `content_type` to `key`.
    ///
    /// # Errors
    /// [`StorageError::Presign`] if the request cannot be signed.
    pub async fn presign_put(
        &self,
        key: &str,
        content_type: &str,
        expires_in: Duration,
    ) -> Result<String, StorageError> {
        let cfg = PresigningConfig::expires_in(expires_in)
            .map_err(|e| StorageError::Presign(e.to_string()))?;
        let presigned = self
            .client
            .put_object()
            .bucket(&self.bucket)
            .key(key)
            .content_type(content_type)
            .presigned(cfg)
            .await
            .map_err(|e| StorageError::Presign(e.to_string()))?;
        Ok(presigned.uri().to_string())
    }

    /// A presigned GET URL for reading `key`.
    ///
    /// # Errors
    /// [`StorageError::Presign`] if the request cannot be signed.
    pub async fn presign_get(
        &self,
        key: &str,
        expires_in: Duration,
    ) -> Result<String, StorageError> {
        let cfg = PresigningConfig::expires_in(expires_in)
            .map_err(|e| StorageError::Presign(e.to_string()))?;
        let presigned = self
            .client
            .get_object()
            .bucket(&self.bucket)
            .key(key)
            .presigned(cfg)
            .await
            .map_err(|e| StorageError::Presign(e.to_string()))?;
        Ok(presigned.uri().to_string())
    }

    /// Fetch object metadata, or `None` if the object does not exist.
    ///
    /// # Errors
    /// [`StorageError::S3`] on an unexpected failure.
    pub async fn head(&self, key: &str) -> Result<Option<ObjectMeta>, StorageError> {
        match self
            .client
            .head_object()
            .bucket(&self.bucket)
            .key(key)
            .send()
            .await
        {
            Ok(out) => Ok(Some(ObjectMeta {
                size_bytes: out.content_length().unwrap_or(0),
                content_type: out.content_type().map(str::to_owned),
            })),
            Err(err) => {
                let service = err.into_service_error();
                if service.is_not_found() {
                    Ok(None)
                } else {
                    Err(StorageError::S3(service.to_string()))
                }
            }
        }
    }

    /// Download the first `n` bytes of `key` (for magic-byte MIME sniffing).
    ///
    /// # Errors
    /// [`StorageError::S3`] on failure.
    pub async fn get_prefix(&self, key: &str, n: u64) -> Result<Vec<u8>, StorageError> {
        let out = self
            .client
            .get_object()
            .bucket(&self.bucket)
            .key(key)
            .range(format!("bytes=0-{}", n.saturating_sub(1)))
            .send()
            .await
            .map_err(|e| StorageError::S3(e.into_service_error().to_string()))?;
        let data = out
            .body
            .collect()
            .await
            .map_err(|e| StorageError::S3(e.to_string()))?;
        Ok(data.into_bytes().to_vec())
    }

    /// Download the full object.
    ///
    /// # Errors
    /// [`StorageError::S3`] on failure.
    pub async fn get(&self, key: &str) -> Result<Vec<u8>, StorageError> {
        let out = self
            .client
            .get_object()
            .bucket(&self.bucket)
            .key(key)
            .send()
            .await
            .map_err(|e| StorageError::S3(e.into_service_error().to_string()))?;
        let data = out
            .body
            .collect()
            .await
            .map_err(|e| StorageError::S3(e.to_string()))?;
        Ok(data.into_bytes().to_vec())
    }

    /// Upload `bytes` to `key`.
    ///
    /// # Errors
    /// [`StorageError::S3`] on failure.
    pub async fn put(
        &self,
        key: &str,
        bytes: Vec<u8>,
        content_type: &str,
    ) -> Result<(), StorageError> {
        self.client
            .put_object()
            .bucket(&self.bucket)
            .key(key)
            .body(ByteStream::from(bytes))
            .content_type(content_type)
            .send()
            .await
            .map_err(|e| StorageError::S3(e.into_service_error().to_string()))?;
        Ok(())
    }
}

/// Build the canonical storage key for a document (§11):
/// `tenants/{tenant}/applications/{app}/{doc_type}/{uuid}.{ext}`.
#[must_use]
pub fn document_key(tenant_id: Uuid, application_id: Uuid, doc_type: &str, ext: &str) -> String {
    let id = Uuid::new_v4();
    format!("tenants/{tenant_id}/applications/{application_id}/{doc_type}/{id}.{ext}")
}

/// The thumbnail key derived from a document's storage key.
#[must_use]
pub fn thumbnail_key(storage_key: &str) -> String {
    format!("{storage_key}.thumb.jpg")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn document_key_follows_the_tenant_layout() {
        let tenant = Uuid::new_v4();
        let app = Uuid::new_v4();
        let key = document_key(tenant, app, "id_front", "jpg");
        assert!(key.starts_with(&format!("tenants/{tenant}/applications/{app}/id_front/")));
        assert!(
            std::path::Path::new(&key)
                .extension()
                .is_some_and(|e| e.eq_ignore_ascii_case("jpg"))
        );
    }

    #[test]
    fn thumbnail_key_is_derived() {
        assert_eq!(thumbnail_key("a/b/c.jpg"), "a/b/c.jpg.thumb.jpg");
    }
}
