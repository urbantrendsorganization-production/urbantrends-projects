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
#: ## Why this is wider than the constraint, and must stay wider
#:
#: `COMPLETED` is in here and deliberately **not** in the exclusion constraint.
#: An unexplained divergence between what the database enforces and what the
#: engine enforces is the kind of thing a later reader "tidies up", so the reason
#: is written here rather than left to be inferred.
#:
#: The two sets answer two different questions:
#:
#: - The constraint answers *may this row exist?* It is a concurrency device. It
#:   arbitrates two people confirming the same slot in the same instant, which
#:   can only happen between live bookings.
#: - `BLOCKING_STATUSES` answers *should we offer this time?* It is an offer
#:   policy. Time that was worked is not on offer: a cut that ran 10:00–11:30
#:   must not leave the staff view showing a free 11:00.
#:
#: The case that needs the divergence is **walk-in backfill**. A stylist finishes
#: at 11:30, and at 16:00 remembers the shave they did at 11:15 and never
#: recorded. That walk-in overlaps a completed appointment. The engine will not
#: *offer* 11:15 — correctly, because nobody should be booked into worked time by
#: accident — but the write itself has to be possible, because it is a correction
#: to history, and history is the thing the owner dashboard reads. With
#: `COMPLETED` inside the constraint the database would refuse it outright, and a
#: staff member with no way to record what actually happened stops recording
#: anything, which is the adoption failure CLAUDE.md §4 is about.
#:
#: So the split is load-bearing in both directions, and `scheduling/collisions.py`
#: depends on it: an overlap with an *active* appointment can only be resolved by
#: shortening or moving, because the database will refuse it either way, while an
#: overlap with a *completed* one can additionally be recorded as-is.
#:
#: Tidying this in either direction breaks something concrete:
#:
#: - Adding `COMPLETED` to the constraint makes backfill impossible and turns a
#:   correction into an `IntegrityError` with no remedy path.
#: - Removing `COMPLETED` from here makes the engine offer worked time, and the
#:   first booking taken against it collides with nothing in the database and
#:   with a real person in the chair.
BLOCKING_STATUSES = (*ACTIVE_STATUSES, AppointmentStatus.COMPLETED)


class BookingSource(models.TextChoices):
    #: The public booking page or the embedded widget. Always deposit-backed.
    ONLINE = "online", "Online"
    #: Recorded at the chair. CLAUDE.md §4: the majority of Kenyan salon trade,
    #: and it must stay three taps.
    WALK_IN = "walk_in", "Walk-in"
    #: Entered by staff for a client who phoned or came by the counter.
    STAFF = "staff", "Booked by staff"
