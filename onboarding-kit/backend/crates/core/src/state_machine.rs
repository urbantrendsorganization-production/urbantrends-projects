//! Onboarding application state machine (CLAUDE.md §6).
//!
//! This is the heart of the product. The rules here are enforced structurally:
//! a rejection cannot exist without a reason and a return cannot exist without
//! notes, because that data is carried in the enum variant rather than validated
//! after the fact.
//!
//! Two representations coexist:
//! - [`Status`] — the rich state, carrying the reason/notes mandated by §6. Used
//!   when a specific state must be fully described (e.g. serialized to a client).
//! - [`StatusKind`] — the bare discriminant. Used for the denormalized
//!   `current_status` column and for deciding transition validity, which never
//!   depends on the reason/notes payload.

use crate::Role;

/// The bare status discriminant — no payload. Mirrors the `current_status`
/// column's CHECK constraint and is what the database round-trips.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum StatusKind {
    Draft,
    Submitted,
    UnderReview,
    Approved,
    Rejected,
    ReturnedForCorrection,
}

impl StatusKind {
    /// String form stored in the database (matches the migration CHECK values).
    #[must_use]
    pub fn as_str(self) -> &'static str {
        match self {
            StatusKind::Draft => "draft",
            StatusKind::Submitted => "submitted",
            StatusKind::UnderReview => "under_review",
            StatusKind::Approved => "approved",
            StatusKind::Rejected => "rejected",
            StatusKind::ReturnedForCorrection => "returned_for_correction",
        }
    }

    /// Parse the database string form back into a [`StatusKind`].
    ///
    /// # Errors
    /// Returns [`UnknownStatus`] if `value` is not one of the known statuses,
    /// which indicates database corruption or a schema drift bug.
    pub fn from_db(value: &str) -> Result<Self, UnknownStatus> {
        match value {
            "draft" => Ok(StatusKind::Draft),
            "submitted" => Ok(StatusKind::Submitted),
            "under_review" => Ok(StatusKind::UnderReview),
            "approved" => Ok(StatusKind::Approved),
            "rejected" => Ok(StatusKind::Rejected),
            "returned_for_correction" => Ok(StatusKind::ReturnedForCorrection),
            other => Err(UnknownStatus(other.to_owned())),
        }
    }

    /// Terminal states accept no further transitions (§6).
    #[must_use]
    pub fn is_terminal(self) -> bool {
        matches!(self, StatusKind::Approved | StatusKind::Rejected)
    }
}

/// Returned when a status string from the database is not recognized.
#[derive(Debug, Clone, thiserror::Error)]
#[error("unknown application status: {0}")]
pub struct UnknownStatus(pub String);

/// The rich application status. Rejection and return carry their mandatory text
/// in the variant, so an empty-less state is unrepresentable (§6).
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum Status {
    Draft,
    Submitted,
    UnderReview,
    Approved,
    Rejected { reason: String },
    ReturnedForCorrection { notes: String },
}

impl Status {
    /// The discriminant for this status.
    #[must_use]
    pub fn kind(&self) -> StatusKind {
        match self {
            Status::Draft => StatusKind::Draft,
            Status::Submitted => StatusKind::Submitted,
            Status::UnderReview => StatusKind::UnderReview,
            Status::Approved => StatusKind::Approved,
            Status::Rejected { .. } => StatusKind::Rejected,
            Status::ReturnedForCorrection { .. } => StatusKind::ReturnedForCorrection,
        }
    }

    /// The reason/notes text for states that carry it, persisted on the event
    /// row's `reason` column.
    #[must_use]
    pub fn reason(&self) -> Option<&str> {
        match self {
            Status::Rejected { reason } => Some(reason),
            Status::ReturnedForCorrection { notes } => Some(notes),
            _ => None,
        }
    }
}

/// Who is attempting a transition. `is_owner` means the actor is the agent that
/// owns the application; it is only consulted for agent-driven transitions.
#[derive(Debug, Clone, Copy)]
pub struct Actor {
    pub role: Role,
    pub is_owner: bool,
}

impl Actor {
    #[must_use]
    pub fn new(role: Role, is_owner: bool) -> Self {
        Self { role, is_owner }
    }
}

/// A requested transition. Reject/Return carry their mandatory text so the
/// caller cannot request them without supplying it (§6).
#[derive(Debug, Clone)]
pub enum TransitionAction {
    Submit,
    StartReview,
    Approve,
    Reject { reason: String },
    Return { notes: String },
}

impl TransitionAction {
    /// Stable name used in error messages and logs.
    #[must_use]
    pub fn name(&self) -> &'static str {
        match self {
            TransitionAction::Submit => "submit",
            TransitionAction::StartReview => "start_review",
            TransitionAction::Approve => "approve",
            TransitionAction::Reject { .. } => "reject",
            TransitionAction::Return { .. } => "return",
        }
    }
}

/// The result of a successful transition: enough to write exactly one
/// `application_events` row and update the denormalized column (§6). The
/// database/api layer enriches this with ids, actor and timestamp.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Transition {
    pub from: StatusKind,
    pub to: Status,
}

impl Transition {
    #[must_use]
    pub fn to_kind(&self) -> StatusKind {
        self.to.kind()
    }

    #[must_use]
    pub fn reason(&self) -> Option<&str> {
        self.to.reason()
    }
}

/// Why a transition was refused.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum TransitionError {
    /// The action is never valid from this state.
    #[error("cannot {action} from {from:?}")]
    InvalidTransition {
        from: StatusKind,
        action: &'static str,
    },

    /// The actor's role (or ownership) does not permit this action.
    #[error("{role:?} may not {action}")]
    Unauthorized { role: Role, action: &'static str },

    /// Rejection was requested with a blank reason.
    #[error("a rejection reason is required")]
    EmptyReason,

    /// Return was requested with blank notes.
    #[error("return notes are required")]
    EmptyNotes,
}

/// Apply `action` to an application currently in `from`, on behalf of `actor`.
///
/// Checks proceed in a fixed order so errors are predictable: authorization
/// first (can this role ever perform this action?), then state validity (is the
/// action legal from `from`?), then content (non-empty reason/notes).
///
/// # Errors
/// Returns [`TransitionError`] for an unauthorized actor, an illegal
/// from/action pair, or a missing rejection reason / return notes.
// The action is logically consumed by the transition it requests, so taking it
// by value is the intended ergonomic API for callers that construct-and-apply.
#[allow(clippy::needless_pass_by_value)]
pub fn apply_transition(
    from: StatusKind,
    action: TransitionAction,
    actor: Actor,
) -> Result<Transition, TransitionError> {
    let action_name = action.name();

    // 1. Authorization — independent of the current state.
    if !is_authorized(&action, actor) {
        return Err(TransitionError::Unauthorized {
            role: actor.role,
            action: action_name,
        });
    }

    // 2. State validity + resulting status.
    let to = match (&action, from) {
        (TransitionAction::Submit, StatusKind::Draft | StatusKind::ReturnedForCorrection) => {
            Status::Submitted
        }
        (TransitionAction::StartReview, StatusKind::Submitted) => Status::UnderReview,
        (TransitionAction::Approve, StatusKind::UnderReview) => Status::Approved,
        (TransitionAction::Reject { reason }, StatusKind::UnderReview) => {
            let reason = reason.trim();
            if reason.is_empty() {
                return Err(TransitionError::EmptyReason);
            }
            Status::Rejected {
                reason: reason.to_owned(),
            }
        }
        (TransitionAction::Return { notes }, StatusKind::UnderReview) => {
            let notes = notes.trim();
            if notes.is_empty() {
                return Err(TransitionError::EmptyNotes);
            }
            Status::ReturnedForCorrection {
                notes: notes.to_owned(),
            }
        }
        _ => {
            return Err(TransitionError::InvalidTransition {
                from,
                action: action_name,
            });
        }
    };

    Ok(Transition { from, to })
}

/// Whether `actor` may ever perform `action`, regardless of current state.
fn is_authorized(action: &TransitionAction, actor: Actor) -> bool {
    match action {
        // Only the owning agent may submit (§6).
        TransitionAction::Submit => actor.role == Role::Agent && actor.is_owner,
        // All review transitions are reviewer-only (§6, §7).
        TransitionAction::StartReview
        | TransitionAction::Approve
        | TransitionAction::Reject { .. }
        | TransitionAction::Return { .. } => actor.role == Role::Reviewer,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn agent_owner() -> Actor {
        Actor::new(Role::Agent, true)
    }
    fn agent_other() -> Actor {
        Actor::new(Role::Agent, false)
    }
    fn reviewer() -> Actor {
        Actor::new(Role::Reviewer, false)
    }
    fn admin() -> Actor {
        Actor::new(Role::Admin, false)
    }

    // ---- Kind <-> string round-trip -------------------------------------

    #[test]
    fn status_kind_db_roundtrip_is_total() {
        for kind in [
            StatusKind::Draft,
            StatusKind::Submitted,
            StatusKind::UnderReview,
            StatusKind::Approved,
            StatusKind::Rejected,
            StatusKind::ReturnedForCorrection,
        ] {
            assert_eq!(StatusKind::from_db(kind.as_str()).unwrap(), kind);
        }
    }

    #[test]
    fn unknown_status_string_is_rejected() {
        assert!(StatusKind::from_db("nonsense").is_err());
    }

    #[test]
    fn only_approved_and_rejected_are_terminal() {
        assert!(StatusKind::Approved.is_terminal());
        assert!(StatusKind::Rejected.is_terminal());
        for kind in [
            StatusKind::Draft,
            StatusKind::Submitted,
            StatusKind::UnderReview,
            StatusKind::ReturnedForCorrection,
        ] {
            assert!(!kind.is_terminal());
        }
    }

    // ---- Every valid transition -----------------------------------------

    #[test]
    fn draft_to_submitted_by_owner() {
        let t = apply_transition(StatusKind::Draft, TransitionAction::Submit, agent_owner())
            .expect("valid");
        assert_eq!(t.to_kind(), StatusKind::Submitted);
        assert_eq!(t.from, StatusKind::Draft);
    }

    #[test]
    fn returned_to_submitted_by_owner() {
        let t = apply_transition(
            StatusKind::ReturnedForCorrection,
            TransitionAction::Submit,
            agent_owner(),
        )
        .expect("valid");
        assert_eq!(t.to_kind(), StatusKind::Submitted);
    }

    #[test]
    fn submitted_to_under_review_by_reviewer() {
        let t = apply_transition(
            StatusKind::Submitted,
            TransitionAction::StartReview,
            reviewer(),
        )
        .expect("valid");
        assert_eq!(t.to_kind(), StatusKind::UnderReview);
    }

    #[test]
    fn under_review_to_approved_by_reviewer() {
        let t = apply_transition(
            StatusKind::UnderReview,
            TransitionAction::Approve,
            reviewer(),
        )
        .expect("valid");
        assert_eq!(t.to, Status::Approved);
    }

    #[test]
    fn under_review_to_rejected_carries_reason() {
        let t = apply_transition(
            StatusKind::UnderReview,
            TransitionAction::Reject {
                reason: "ID photo unreadable".to_owned(),
            },
            reviewer(),
        )
        .expect("valid");
        assert_eq!(t.to_kind(), StatusKind::Rejected);
        assert_eq!(t.reason(), Some("ID photo unreadable"));
    }

    #[test]
    fn under_review_to_returned_carries_notes() {
        let t = apply_transition(
            StatusKind::UnderReview,
            TransitionAction::Return {
                notes: "Please retake the selfie".to_owned(),
            },
            reviewer(),
        )
        .expect("valid");
        assert_eq!(t.to_kind(), StatusKind::ReturnedForCorrection);
        assert_eq!(t.reason(), Some("Please retake the selfie"));
    }

    // ---- Mandatory text ---------------------------------------------------

    #[test]
    fn reject_with_blank_reason_is_rejected() {
        let err = apply_transition(
            StatusKind::UnderReview,
            TransitionAction::Reject {
                reason: "   ".to_owned(),
            },
            reviewer(),
        )
        .unwrap_err();
        assert_eq!(err, TransitionError::EmptyReason);
    }

    #[test]
    fn return_with_blank_notes_is_rejected() {
        let err = apply_transition(
            StatusKind::UnderReview,
            TransitionAction::Return {
                notes: String::new(),
            },
            reviewer(),
        )
        .unwrap_err();
        assert_eq!(err, TransitionError::EmptyNotes);
    }

    #[test]
    fn reason_and_notes_are_trimmed() {
        let t = apply_transition(
            StatusKind::UnderReview,
            TransitionAction::Reject {
                reason: "  duplicate client  ".to_owned(),
            },
            reviewer(),
        )
        .expect("valid");
        assert_eq!(t.reason(), Some("duplicate client"));
    }

    // ---- Actor authorization ---------------------------------------------

    #[test]
    fn non_owner_agent_cannot_submit() {
        let err = apply_transition(StatusKind::Draft, TransitionAction::Submit, agent_other())
            .unwrap_err();
        assert!(matches!(err, TransitionError::Unauthorized { .. }));
    }

    #[test]
    fn reviewer_cannot_submit() {
        let err =
            apply_transition(StatusKind::Draft, TransitionAction::Submit, reviewer()).unwrap_err();
        assert!(matches!(err, TransitionError::Unauthorized { .. }));
    }

    #[test]
    fn agent_cannot_perform_review_actions() {
        for action in [
            TransitionAction::StartReview,
            TransitionAction::Approve,
            TransitionAction::Reject {
                reason: "x".to_owned(),
            },
            TransitionAction::Return {
                notes: "x".to_owned(),
            },
        ] {
            let err = apply_transition(StatusKind::UnderReview, action, agent_owner()).unwrap_err();
            assert!(matches!(err, TransitionError::Unauthorized { .. }));
        }
    }

    #[test]
    fn admin_cannot_perform_transitions() {
        assert!(matches!(
            apply_transition(
                StatusKind::Submitted,
                TransitionAction::StartReview,
                admin()
            ),
            Err(TransitionError::Unauthorized { .. })
        ));
        assert!(matches!(
            apply_transition(StatusKind::Draft, TransitionAction::Submit, admin()),
            Err(TransitionError::Unauthorized { .. })
        ));
    }

    // ---- Every invalid from/action pair ----------------------------------

    /// The full transition table: (from, action-name) -> valid? Authorization
    /// aside, exactly these six pairs are legal; everything else is invalid.
    fn is_valid_pair(from: StatusKind, action: &str) -> bool {
        matches!(
            (from, action),
            (
                StatusKind::Draft | StatusKind::ReturnedForCorrection,
                "submit"
            ) | (StatusKind::Submitted, "start_review")
                | (StatusKind::UnderReview, "approve" | "reject" | "return")
        )
    }

    fn every_action() -> Vec<TransitionAction> {
        vec![
            TransitionAction::Submit,
            TransitionAction::StartReview,
            TransitionAction::Approve,
            TransitionAction::Reject {
                reason: "reason".to_owned(),
            },
            TransitionAction::Return {
                notes: "notes".to_owned(),
            },
        ]
    }

    fn every_kind() -> Vec<StatusKind> {
        vec![
            StatusKind::Draft,
            StatusKind::Submitted,
            StatusKind::UnderReview,
            StatusKind::Approved,
            StatusKind::Rejected,
            StatusKind::ReturnedForCorrection,
        ]
    }

    /// Exhaustive sweep: for each (from, action) pair, using an actor authorized
    /// for that action, the result is Ok iff the pair is in the table. This
    /// covers every invalid pair (30 - 6 = 24 of them) plus every valid one.
    #[test]
    fn exhaustive_from_action_table() {
        for from in every_kind() {
            for action in every_action() {
                // Choose an actor authorized for this action so we isolate the
                // state-validity dimension from authorization.
                let actor = match action {
                    TransitionAction::Submit => agent_owner(),
                    _ => reviewer(),
                };
                let name = action.name();
                let result = apply_transition(from, action, actor);
                if is_valid_pair(from, name) {
                    assert!(result.is_ok(), "expected {name} from {from:?} to be valid");
                } else {
                    assert!(
                        matches!(result, Err(TransitionError::InvalidTransition { .. })),
                        "expected {name} from {from:?} to be an invalid transition, got {result:?}"
                    );
                }
            }
        }
    }

    #[test]
    fn terminal_states_accept_nothing() {
        for from in [StatusKind::Approved, StatusKind::Rejected] {
            for action in every_action() {
                let actor = match action {
                    TransitionAction::Submit => agent_owner(),
                    _ => reviewer(),
                };
                assert!(
                    apply_transition(from, action, actor).is_err(),
                    "terminal {from:?} must reject all actions"
                );
            }
        }
    }
}
