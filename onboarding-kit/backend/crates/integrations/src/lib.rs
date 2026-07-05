//! `onboardkit-integrations` — outbound side-effect adapters.
//!
//! Home of the OTP service (§8), SMS providers (§9) and S3 object storage (§11).
//! These land in later phases; Phase 0 only establishes the crate and its place
//! in the dependency graph (`integrations -> core`).

#![warn(clippy::pedantic)]
#![allow(clippy::module_name_repetitions, clippy::doc_markdown)]

pub mod email;
pub mod image_ops;
pub mod mime;
pub mod otp;
pub mod password;
pub mod phone;
pub mod sms;
pub mod storage;
pub mod token;

pub use phone::{Phone, PhoneError};
pub use storage::{ObjectStore, StorageConfig};
