//! `onboardkit-core` — pure domain layer for OnboardKit.
//!
//! This crate holds domain types, the application state machine, and validation
//! logic. It depends on nothing internal and MUST NEVER import `axum` or `sqlx`
//! (see CLAUDE.md §2 and §3). The domain model and state machine land in Phase 1.

#![warn(clippy::pedantic)]
#![allow(clippy::module_name_repetitions, clippy::doc_markdown)]

pub mod jobs;
pub mod state_machine;

pub use state_machine::{
    Actor, Status, StatusKind, Transition, TransitionAction, TransitionError, UnknownStatus,
    apply_transition,
};

/// User roles as defined in CLAUDE.md §5. Kept here in Phase 0 so both the API
/// and JWT layers can reference a single source of truth; RBAC behaviour lands
/// in Phase 1.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Role {
    Agent,
    Reviewer,
    Admin,
}

impl Role {
    /// The wire/string representation used in JWT claims and the database.
    #[must_use]
    pub fn as_str(self) -> &'static str {
        match self {
            Role::Agent => "agent",
            Role::Reviewer => "reviewer",
            Role::Admin => "admin",
        }
    }

    /// Parse the database/wire string form back into a [`Role`].
    ///
    /// # Errors
    /// Returns [`UnknownRole`] if `value` is not a known role, which indicates
    /// database corruption or schema drift.
    pub fn from_db(value: &str) -> Result<Self, UnknownRole> {
        match value {
            "agent" => Ok(Role::Agent),
            "reviewer" => Ok(Role::Reviewer),
            "admin" => Ok(Role::Admin),
            other => Err(UnknownRole(other.to_owned())),
        }
    }
}

/// Returned when a role string from the database is not recognized.
#[derive(Debug, Clone, thiserror::Error)]
#[error("unknown role: {0}")]
pub struct UnknownRole(pub String);

#[cfg(test)]
mod tests {
    use super::Role;

    #[test]
    fn role_roundtrips_through_json() {
        for (role, text) in [
            (Role::Agent, "\"agent\""),
            (Role::Reviewer, "\"reviewer\""),
            (Role::Admin, "\"admin\""),
        ] {
            let encoded = serde_json::to_string(&role).expect("serialize role");
            assert_eq!(encoded, text);
            let decoded: Role = serde_json::from_str(&encoded).expect("deserialize role");
            assert_eq!(decoded, role);
        }
    }

    #[test]
    fn role_as_str_matches_serde() {
        assert_eq!(Role::Agent.as_str(), "agent");
        assert_eq!(Role::Reviewer.as_str(), "reviewer");
        assert_eq!(Role::Admin.as_str(), "admin");
    }
}
