//! `onboardkit-integrations` — outbound side-effect adapters.
//!
//! Home of the OTP service (§8), SMS providers (§9) and S3 object storage (§11).
//! These land in later phases; Phase 0 only establishes the crate and its place
//! in the dependency graph (`integrations -> core`).

#![warn(clippy::pedantic)]
#![allow(clippy::module_name_repetitions, clippy::doc_markdown)]
