//! `AppError` — the single error type returned by all handlers.
//!
//! Renders the consistent JSON body from CLAUDE.md §7:
//! `{ "error": { "code": "...", "message": "..." } }`. Internal errors are
//! logged with full detail but NEVER leaked to the client.

use axum::Json;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use serde::Serialize;

/// Application-wide error type. Every fallible handler returns
/// `Result<T, AppError>`.
#[derive(Debug, thiserror::Error)]
pub enum AppError {
    #[error("authentication required")]
    Unauthorized,

    #[error("insufficient permissions")]
    Forbidden,

    #[error("resource not found")]
    NotFound,

    #[error("bad request: {0}")]
    BadRequest(String),

    #[error("validation failed: {0}")]
    Validation(String),

    #[error("conflict: {0}")]
    Conflict(String),

    #[error("too many requests")]
    TooManyRequests,

    /// Any unexpected failure. The inner error is logged, never returned.
    #[error("internal error")]
    Internal(#[source] anyhow::Error),
}

impl AppError {
    fn status_and_code(&self) -> (StatusCode, &'static str) {
        match self {
            AppError::Unauthorized => (StatusCode::UNAUTHORIZED, "unauthorized"),
            AppError::Forbidden => (StatusCode::FORBIDDEN, "forbidden"),
            AppError::NotFound => (StatusCode::NOT_FOUND, "not_found"),
            AppError::BadRequest(_) => (StatusCode::BAD_REQUEST, "bad_request"),
            AppError::Validation(_) => (StatusCode::UNPROCESSABLE_ENTITY, "validation_error"),
            AppError::Conflict(_) => (StatusCode::CONFLICT, "conflict"),
            AppError::TooManyRequests => (StatusCode::TOO_MANY_REQUESTS, "too_many_requests"),
            AppError::Internal(_) => (StatusCode::INTERNAL_SERVER_ERROR, "internal_error"),
        }
    }

    /// The client-facing message. Internal errors are deliberately generic.
    fn public_message(&self) -> String {
        match self {
            AppError::Unauthorized => "Authentication required.".to_string(),
            AppError::Forbidden => "You do not have permission to perform this action.".to_string(),
            AppError::NotFound => "The requested resource was not found.".to_string(),
            AppError::TooManyRequests => "Too many requests. Please try again later.".to_string(),
            AppError::BadRequest(msg) | AppError::Validation(msg) | AppError::Conflict(msg) => {
                msg.clone()
            }
            AppError::Internal(_) => "An internal error occurred.".to_string(),
        }
    }
}

#[derive(Serialize)]
struct ErrorBody {
    error: ErrorDetail,
}

#[derive(Serialize)]
struct ErrorDetail {
    code: &'static str,
    message: String,
}

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        let (status, code) = self.status_and_code();

        // Log server-side faults with full context; keep the client body generic.
        if let AppError::Internal(error) = &self {
            tracing::error!(error = ?error, "internal error");
        }

        let body = ErrorBody {
            error: ErrorDetail {
                code,
                message: self.public_message(),
            },
        };
        (status, Json(body)).into_response()
    }
}

impl From<sqlx::Error> for AppError {
    fn from(error: sqlx::Error) -> Self {
        AppError::Internal(error.into())
    }
}

impl From<anyhow::Error> for AppError {
    fn from(error: anyhow::Error) -> Self {
        AppError::Internal(error)
    }
}

/// Convenience alias for handler return types.
pub type AppResult<T> = Result<T, AppError>;
