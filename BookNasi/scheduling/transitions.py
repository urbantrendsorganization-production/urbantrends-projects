"""What a staff member may do to an appointment during the day.

Six statuses, one transition table, and one rule that shapes the whole module:

    **Every transition a staff member can make is reversible, and no reversal is
    guaranteed to succeed.**

Both halves matter and they are in tension, which is why this is written down
rather than left to the views.

*Reversible*, because the screen is used standing, one-handed, with wet hands,
and the marking that matters most is the one most likely to be mis-tapped.
No-show feeds the metric that sells this product to the next shop — CLAUDE.md
§7 — so it has to be one tap, and a one-tap destructive action that needs an
owner to undo is a one-tap action nobody uses. A stylist marking no-show at
11:05 for a client who walks in at 11:07 fixes it themselves, in one tap, in
front of the client.

*Not guaranteed*, because `no_show` and `cancelled` are outside
`ACTIVE_STATUSES` and therefore outside the exclusion constraint. Marking a
no-show genuinely frees the chair — that is the point, so the walk-in waiting by
the door can have it. If somebody takes it in those two minutes, undoing is
refused by the database, and correctly so. That refusal must arrive as
`SlotTaken` with the appointment that took the slot, not as a 500 and not as a
silent no-op, because the staff member is looking at two real people and needs
to know which one has the chair.

## Why "waiting, not started" is not a seventh status

The design draws it as a walk-in state. It ships as `confirmed` with
`started_at` still null — see `Appointment.is_waiting`. A seventh status would
mean editing the tuple the exclusion constraint filters on, and migrating a
constraint that is the product's core guarantee, in order to record something
two existing columns already record. The three-tap flow writes it by simply not
calling `start()`.

## Why finishing shortens the appointment but never lengthens it

"Finish now" at 11:00 on a 10:00–13:30 booking means the chair is free from
11:00, and a walk-in should be able to have it — so the range is trimmed and
`finished_at` records when. Finishing *late* does not push the range out: that
would rewrite the record over time the next client has already booked, and could
collide. `finished_at` still records the truth, `duration_snapshot` still holds
what was booked, and telling the next client is slice 8's job.
"""

from datetime import timedelta
from enum import Enum

from django.db import transaction
from django.utils import timezone

from scheduling.booking import order_bookings_for, slot_taken_on_conflict
from scheduling.models import RANGE_BOUNDS, Appointment
from scheduling.statuses import ACTIVE_STATUSES, AppointmentStatus

S = AppointmentStatus


class Actor(Enum):
    """Who is asking. There are two, and they have different tables.

    Added in slice 6. The payment callback needs two edges no staff member may
    ever have — `pending_payment -> confirmed` and `cancelled -> confirmed` —
    and the reason they are separated rather than merged into
    `STAFF_TRANSITIONS` is CLAUDE.md §5: confirming an unpaid hold is what a
    *paid callback* does. Granting it to a person hands out the deposit-free
    booking the whole rule exists to prevent.

    `STAFF` is the default on `apply_transition`, so every caller written
    before this existed is unchanged and no view can reach the system table by
    forgetting an argument. Reaching it deliberately from a view is refused by
    `payments/tests/test_system_transition_guard.py`, which parses the source —
    a default alone is a convention, and conventions are what this repo has
    been replacing with tests since slice 1.
    """

    STAFF = "staff"
    SYSTEM = "system"


class TransitionRefused(Exception):
    """Not a transition this actor may make from this status.

    A programming error or a stale screen, never a busy calendar. Distinct from
    `SlotTaken`, which means the transition was legal and the chair was gone.
    """

    def __init__(self, appointment, to_status, actor=Actor.STAFF):
        self.appointment = appointment
        self.to_status = to_status
        self.actor = actor
        super().__init__(
            f"An appointment that is {appointment.get_status_display().lower()} "
            f"cannot become {S(to_status).label.lower()}."
        )


#: The table. `from -> {to}`, for a staff member on the day view.
#:
#: `pending_payment` is almost absent on purpose: an unpaid online hold is
#: slice 6's business, and the only thing a staff member can usefully do with
#: one is cancel it when the client rings to say forget it. Confirming one
#: without a payment would hand out the deposit-free booking that CLAUDE.md §5
#: exists to prevent.
STAFF_TRANSITIONS = {
    S.PENDING_PAYMENT: frozenset({S.CANCELLED}),
    S.CONFIRMED: frozenset({S.IN_PROGRESS, S.COMPLETED, S.NO_SHOW, S.CANCELLED}),
    # `confirmed` here is the undo of a mis-tapped Start.
    S.IN_PROGRESS: frozenset({S.COMPLETED, S.CONFIRMED, S.NO_SHOW}),
    S.COMPLETED: frozenset({S.IN_PROGRESS, S.CONFIRMED}),
    S.NO_SHOW: frozenset({S.CONFIRMED}),
    S.CANCELLED: frozenset({S.CONFIRMED}),
}

#: The other table. Two edges, and no more.
#:
#: `pending_payment -> confirmed` is the ordinary paid callback.
#:
#: `cancelled -> confirmed` is the late callback: the hold expired, the slot was
#: released, and the money arrived afterwards. The design's handoff is explicit
#: that this must still confirm ("a late callback after a timeout must still
#: confirm the booking and send the SMS"), and re-entering `ACTIVE_STATUSES`
#: puts the row back under the exclusion constraint — so if somebody took the
#: slot in the meantime, the database refuses and that refusal *is* `slotLost`.
#:
#: Note this is the same edge a staff member already has for undoing a
#: mis-tapped cancel, and that is not an accident: undo-a-cancel and
#: honour-a-late-payment are the same operation with the same collision risk,
#: which is why slice 6 needed no new mechanism for the hardest case in the
#: payment machine.
SYSTEM_TRANSITIONS = {
    S.PENDING_PAYMENT: frozenset({S.CONFIRMED}),
    S.CANCELLED: frozenset({S.CONFIRMED}),
}

TRANSITIONS_BY_ACTOR = {
    Actor.STAFF: STAFF_TRANSITIONS,
    Actor.SYSTEM: SYSTEM_TRANSITIONS,
}


def undo_target(appointment):
    """Where a single Undo button goes, or None when there is nothing to undo.

    Derived rather than stored. The previous status is recoverable from the two
    timestamps for every state that has one, and a `previous_status` column
    would be a second source of truth that a direct `.update()` could desync —
    the same failure `shops/integrity.py` exists to close.
    """
    status = appointment.status
    if status in (S.NO_SHOW, S.CANCELLED):
        return S.CONFIRMED
    if status == S.IN_PROGRESS:
        return S.CONFIRMED
    if status == S.COMPLETED:
        # A finish that was never started was a straight confirmed -> completed.
        return S.IN_PROGRESS if appointment.started_at else S.CONFIRMED
    return None


def _range(appointment, ends_at):
    from django.db.backends.postgresql.psycopg_any import DateTimeTZRange

    return DateTimeTZRange(appointment.starts_at, ends_at, RANGE_BOUNDS)


def apply_transition(appointment, to_status, *, now=None, expired_hold=False, actor=Actor.STAFF):
    """Move one appointment to `to_status`, with its side effects. Returns it.

    **The only function that writes `Appointment.status`.** Slice 5's hold
    release goes through here too rather than setting the column itself —
    `holds.release_hold` is a thin wrapper — and so does slice 6's payment
    settlement, because two places writing one column is how a status ends up
    with the side effects of the other path missing.

    Raises `TransitionRefused` when the move is not in the table, and `SlotTaken`
    when re-entering an active status collides with something booked in the
    meantime.

    `expired_hold` distinguishes a hold that ran out from a client who pressed
    cancel. Only the former is counted by `scheduling/abuse.py`; see the note
    there about not teaching people to walk away from the page instead of using
    the button.

    `actor` chooses the table. It defaults to `STAFF` so that no caller reaches
    the system edges by omission — see `Actor`.
    """
    now = now or timezone.now()
    to_status = S(to_status)

    if appointment.status == to_status:
        # Idempotent. A staff member on a bad connection taps Start, sees
        # nothing happen, and taps it again; the second tap is not an error and
        # must not re-stamp `started_at` to a later time.
        return appointment

    if to_status not in TRANSITIONS_BY_ACTOR[actor].get(appointment.status, frozenset()):
        raise TransitionRefused(appointment, to_status, actor)

    fields = ["status", "updated_at"]
    was_holding = appointment.status == S.PENDING_PAYMENT
    appointment.status = to_status

    if to_status == S.IN_PROGRESS:
        # Preserved if already set: this is also the undo of a mis-tapped
        # Finish, and the client did not arrive twice.
        appointment.started_at = appointment.started_at or now
        appointment.finished_at = None
        appointment.time_range = _range(appointment, appointment.booked_ends_at)
        fields += ["started_at", "finished_at", "time_range"]

    elif to_status == S.COMPLETED:
        appointment.finished_at = now
        # Shortens, never lengthens — see the module docstring. The floor of one
        # minute keeps `appointment_range_not_empty` satisfied when a mis-tapped
        # Start is finished in the same second.
        actual_end = min(
            max(now, appointment.starts_at + timedelta(minutes=1)), appointment.booked_ends_at
        )
        appointment.time_range = _range(appointment, actual_end)
        fields += ["finished_at", "time_range"]

    elif to_status == S.CONFIRMED:
        # The undo of start, finish, no-show or cancel. Everything the day did
        # to this row is cleared, and the booked range comes back from the
        # snapshot.
        appointment.started_at = None
        appointment.finished_at = None
        appointment.time_range = _range(appointment, appointment.booked_ends_at)
        fields += ["started_at", "finished_at", "time_range"]

    # no_show and cancelled keep their timestamps: a client who started and then
    # walked out mid-service is a real thing, and losing `started_at` would lose
    # the only record that the chair was occupied at all.

    queued_release = None
    if was_holding:
        # The hold is resolved either way, so the queued release is no longer
        # wanted and the task id goes with it. Stamped here rather than in the
        # caller so that a hold released by the sweep, by the eta task, or by a
        # client pressing cancel all leave the row in the same shape.
        #
        # The id is kept in a local first: the revoke happens after the commit,
        # by which point the column has already been cleared.
        queued_release = appointment.hold_release_task_id
        appointment.hold_released_at = now if expired_hold else None
        appointment.hold_release_task_id = None
        fields += ["hold_released_at", "hold_release_task_id"]

    elif (
        actor is Actor.SYSTEM
        and to_status == S.CONFIRMED
        and appointment.hold_released_at is not None
    ):
        # The late callback, case 1. This hold *did* expire, so slice 5 stamped
        # it — but the client did not abandon it, they paid for it, and
        # `scheduling/abuse.py` counts `hold_released_at` inside the last hour
        # as an abandonment. Leaving the stamp would put a paying client into
        # the cooldown that exists for people who walk away from held slots.
        appointment.hold_released_at = None
        fields.append("hold_released_at")

    with slot_taken_on_conflict(starts_at=appointment.starts_at, staff=appointment.staff):
        with transaction.atomic():
            if to_status in ACTIVE_STATUSES:
                # Re-entering the constraint. Same ordering as an insert, for
                # the same reason — see booking.py's docstring on the deadlock.
                order_bookings_for(appointment.staff_id)
            appointment.save(update_fields=fields)

    if queued_release:
        # After the commit, so a revoke never races a row that has not landed.
        # Best-effort by design — the task re-checks before acting, so a failed
        # revoke costs nothing. See scheduling/holds.py.
        from scheduling.holds import cancel_scheduled_release

        cancel_scheduled_release(queued_release, appointment_id=appointment.pk)

    return appointment


def blocking_appointment_for(appointment):
    """What is in the way of undoing this one, for the message the staff member
    reads. Returns None when nothing is."""
    return (
        Appointment.objects.for_org(appointment.organization_id)
        .filter(
            staff_id=appointment.staff_id,
            status__in=ACTIVE_STATUSES,
            time_range__overlap=(appointment.starts_at, appointment.booked_ends_at),
        )
        .exclude(pk=appointment.pk)
        .select_related("service", "client")
        .first()
    )
