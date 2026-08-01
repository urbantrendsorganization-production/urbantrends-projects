"""Appointment status, and the two sets derived from it.

Kept in its own module so that the exclusion constraint, the migration, the
availability engine and the API all import the *same object*. Two literal lists
that happen to agree today is how a slot ends up bookable in the engine and
rejected by the database, which surfaces to a client as an unexplained failure
at the exact moment they are being asked for money.
"""

from django.db import models


class AppointmentStatus(models.TextChoices):
    #: Slot is held while the STK push is outstanding. Released by a Celery job
    #: after `Shop.hold_ttl_minutes` if the callback never arrives (slice 6).
    PENDING_PAYMENT = "pending_payment", "Awaiting payment"
    CONFIRMED = "confirmed", "Confirmed"
    IN_PROGRESS = "in_progress", "In progress"
    COMPLETED = "completed", "Completed"
    #: Did not turn up. The deposit is what makes this survivable — CLAUDE.md §1.
    NO_SHOW = "no_show", "No show"
    CANCELLED = "cancelled", "Cancelled"


#: **The** collision set. Used by the exclusion constraint in
#: `scheduling/models.py`, by its migration, and by the engine. Nothing else may
#: restate it.
#:
#: Cancelled is absent so a cancelled booking frees its slot immediately — that
#: is the point of cancelling. No-show is absent for the same reason: the chair
#: is empty and a walk-in should be able to take it.
ACTIVE_STATUSES = (
    AppointmentStatus.PENDING_PAYMENT,
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.IN_PROGRESS,
)

#: What the *engine* treats as busy. Derived from ACTIVE_STATUSES rather than
#: written out again.
#:
#: Wider than the constraint by exactly one status, and the asymmetry is
#: deliberate. The constraint exists to arbitrate concurrent writes on live
#: bookings; a completed appointment is not live and cannot be raced. But that
#: time *was worked* — offering it again would let a staff member record a
#: retroactive walk-in on top of a job that already happened, and would make
#: today's staff view show a free slot at 11:00 for a cut that finished at
#: 11:30. So the engine refuses to offer it, and `create_appointment` re-derives
#: before every insert, which is what closes the gap the constraint leaves open.
BLOCKING_STATUSES = (*ACTIVE_STATUSES, AppointmentStatus.COMPLETED)


class BookingSource(models.TextChoices):
    #: The public booking page or the embedded widget. Always deposit-backed.
    ONLINE = "online", "Online"
    #: Recorded at the chair. CLAUDE.md §4: the majority of Kenyan salon trade,
    #: and it must stay three taps.
    WALK_IN = "walk_in", "Walk-in"
    #: Entered by staff for a client who phoned or came by the counter.
    STAFF = "staff", "Booked by staff"
