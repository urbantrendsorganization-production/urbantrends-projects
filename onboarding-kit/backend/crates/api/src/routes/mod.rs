//! HTTP route modules. Application and reviewer routes are added in later
//! phases; Phase 1 adds auth, the `/me` session endpoint, and an admin stub.

pub mod admin;
pub mod auth;
pub mod health;
pub mod session;
