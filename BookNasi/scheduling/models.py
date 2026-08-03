"""The appointment row and the constraint that makes double-booking impossible.

CLAUDE.md §4: "Double-booking is prevented at the database, not in Python. Two
clients tapping 'confirm' in the same second both pass an application-level
`if slot_is_free` check." Everything else in this module exists to make that
constraint usable — a range type it can index, a status set it can filter on,
and snapshots so the row still means something after the service it points at
has changed.
"""

from datetime import timedelta

from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.backends.postgresql.psycopg_any import DateTimeTZRange
from django.db.models import Q

from core.models import OrgDerivedModel
from scheduling.statuses import ACTIVE_STATUSES, AppointmentStatus, BookingSource

#: Referenced by the migration and by `scheduling/booking.py`, which turns a
#: violation of *this* constraint — and no other — into SlotTaken.
NO_OVERLAP_CONSTRAINT = "no_overlapping_appointments"

#: The offline-retry guard. Matched by name in `booking.py` for the same reason
#: the one above is: a bare IntegrityError tells the caller nothing about which
#: rule it broke, and the two mean opposite things — one is "somebody else has
#: this chair", the other is "you already sent this".
REQUEST_ID_CONSTRAINT = "one_appointment_per_client_request"

#: `[start, end)`. An appointment ending at 10:00 and one starting at 10:00 do
#: not overlap, which is the whole reason back-to-back bookings work. Postgres
#: would otherwise default to `[)` for tstzrange anyway; stating it means a
#: future `default_bounds` change cannot quietly make every adjacent pair
#: collide.
RANGE_BOUNDS = "[)"


class Appointment(OrgDerivedModel):
    """One booking, one staff member, one span of time.

    ## Why the range is the source of truth

    `time_range` is a single `tstzrange` column, not a start plus an end. The
    exclusion constraint operates on a range — with two loose columns there is
    nothing for `&&` to index, and the constraint cannot exist. `starts_at` and
    `ends_at` below are read-only views onto it, so there is no second place
    that could disagree about when this appointment is.

    ## Why the snapshots

    Slice 2 established that deactivating a service leaves its appointments
    intact. The same reasoning applies to editing one: a price rise next month
    must not rewrite what last week's booking cost, and a duration change must
    not retroactively move an appointment's end. Reports, refunds and the M-Pesa
    reconciliation in slice 6 all read the snapshot; none of them may join to
    the live `Service` row for a number.
    """

    org_source = "shop"

    shop = models.ForeignKey("shops.Shop", on_delete=models.CASCADE, related_name="appointments")
    # PROTECT, not CASCADE: staff and services are deactivated, never deleted
    # (slice 2), so a delete here would mean somebody bypassed the API — and
    # losing the appointment history is worse than the failed delete.
    staff = models.ForeignKey("shops.Staff", on_delete=models.PROTECT, related_name="appointments")
    service = models.ForeignKey(
        "shops.Service", on_delete=models.PROTECT, related_name="appointments"
    )
    #: Null until slice 5 collects a phone number at checkout. A walk-in
    #: recorded in three taps has no client either, and never will — CLAUDE.md
    #: §4 is explicit that anything adding friction there is a regression.
    #: SET_NULL rather than CASCADE so a DPA §9 erasure scrubs the person
    #: without deleting the shop's revenue history.
    client = models.ForeignKey(
        "clients.Client",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
    )

    time_range = DateTimeRangeField(
        default_bounds=RANGE_BOUNDS,
        help_text="UTC. Half-open: the end instant belongs to the next appointment.",
    )

    status = models.CharField(
        max_length=16,
        choices=AppointmentStatus.choices,
        default=AppointmentStatus.PENDING_PAYMENT,
        db_index=True,
    )
    source = models.CharField(max_length=8, choices=BookingSource.choices)

    #: Whole shillings, as everywhere. See shops/money.py.
    price_snapshot = models.PositiveIntegerField()
    deposit_snapshot = models.PositiveIntegerField()
    #: The duration **as booked**. After a `completed` transition `time_range`
    #: holds what actually happened, so this is also how the booked end is
    #: recovered when a staff member undoes a mis-tapped "Finish now".
    duration_snapshot = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])

    #: This appointment was booked shorter than the service's resolved duration,
    #: at full price.
    #:
    #: It happens on one path: a walk-in that collided, where the engine offered
    #: "shorten to 12:00" and the staff member took it — see
    #: `scheduling/collisions.py`. `duration_snapshot` records the shortened
    #: length because that is the time sold; `price_snapshot` stays at the full
    #: price because nobody renegotiated it with the client standing there, and
    #: asking a stylist to set a price mid-collision is the shop owner's
    #: decision being pushed onto the wrong person.
    #:
    #: The flag exists so that drift is **measurable rather than invisible**.
    #: Revenue-per-staff stays true to what the shop charged; any future
    #: revenue-per-*hour* would silently flatter whoever shortens most, which is
    #: also whoever is under most pressure. With this column the dashboard can
    #: show the distortion next to the number instead of absorbing it.
    #:
    #: Not the same thing as finishing early. "Finish now" at 11:00 on a booking
    #: that ran to 13:30 trims `time_range` and stamps `finished_at`; it does not
    #: change what was booked or what was charged, so it does not set this.
    was_shortened = models.BooleanField(default=False, editable=False)

    #: When the chair was actually taken and given up. Distinct from
    #: `time_range`, which is what was booked until the appointment completes.
    #: Null on a row that has not started; the design's "waiting, not started"
    #: walk-in is exactly `confirmed` with no `started_at` — see transitions.py.
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    #: Supplied by the staff app, not by the server. Slice 4 renders a walk-in
    #: optimistically and retries the write on a shop phone with a bad
    #: connection; without this a retry that the server had already accepted
    #: would insert a second row, collide with the first, and surface to the
    #: staff member as "that slot was just taken" — by themselves. Scoped to the
    #: shop rather than globally so two shops cannot collide on a generated id.
    #:
    #: `null=True` on a CharField, against the usual Django advice, because the
    #: unique constraint below is partial and needs NULL to mean *absent*. With
    #: `""` as the empty value every online booking in the shop would share one
    #: key and the second would be refused.
    client_request_id = models.CharField(  # noqa: DJ001 — see above
        max_length=64, null=True, blank=True, editable=False
    )

    #: When a `pending_payment` hold stops holding. Set at creation from
    #: `Shop.hold_ttl_minutes`, because a pending_payment row *is* a hold and
    #: there is no state in which one exists without an expiry. Server
    #: authoritative: the countdown on the client is a rendering of this and
    #: never the thing that decides.
    hold_expires_at = models.DateTimeField(null=True, blank=True, editable=False)
    #: The Celery task that will release it. Stored so the task can be revoked
    #: when the hold is resolved early. Revoking is an optimisation only — the
    #: task re-checks the row's status before doing anything, and the Beat sweep
    #: is what actually guarantees release. See `scheduling/tasks.py`.
    hold_release_task_id = models.CharField(  # noqa: DJ001 — null means "never scheduled"
        max_length=64, null=True, blank=True, editable=False
    )
    #: Stamped when a hold was released by *expiry* rather than by a client who
    #: cancelled. The difference is what `scheduling/abuse.py` throttles on: a
    #: client who cancels politely is not penalised, one who walks away from
    #: held slots repeatedly is.
    hold_released_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        db_table = "appointments"
        ordering = ["time_range"]
        indexes = [
            # The staff day view's query, and the engine's busy-interval fetch.
            models.Index(fields=["staff", "status"], name="appt_staff_status_idx"),
            models.Index(fields=["shop", "status"], name="appt_shop_status_idx"),
        ]
        constraints = [
            # CLAUDE.md §4, verbatim in intent. `staff_id WITH =` needs
            # btree_gist, enabled in slice 1's core/0001 rather than here
            # because creating an extension takes privileges a normal migration
            # user may not have.
            #
            # The condition uses ACTIVE_STATUSES from scheduling/statuses.py —
            # the same tuple the engine imports. Never a literal list.
            ExclusionConstraint(
                name=NO_OVERLAP_CONSTRAINT,
                expressions=[
                    ("staff", RangeOperators.EQUAL),
                    ("time_range", RangeOperators.OVERLAPS),
                ],
                condition=Q(status__in=ACTIVE_STATUSES),
            ),
            models.CheckConstraint(
                condition=Q(deposit_snapshot__lte=models.F("price_snapshot")),
                name="appointment_deposit_within_price",
            ),
            models.CheckConstraint(
                condition=Q(duration_snapshot__gte=1), name="appointment_has_a_duration"
            ),
            # An empty or unbounded range would sit in the exclusion constraint
            # without ever colliding, which is worse than useless: it would be a
            # booking nobody could see and nothing could displace.
            models.CheckConstraint(
                condition=Q(time_range__isempty=False), name="appointment_range_not_empty"
            ),
            # The offline retry guard. Partial, because the overwhelming
            # majority of rows have no id: online bookings, and anything an
            # older client wrote.
            models.UniqueConstraint(
                fields=["shop", "client_request_id"],
                condition=Q(client_request_id__isnull=False),
                name="one_appointment_per_client_request",
            ),
        ]

    def save(self, *args, **kwargs):
        # `time_range=(start, end)` is the natural thing for a caller to write,
        # and Django leaves that tuple exactly as it found it until the row is
        # read back — so `starts_at` on a freshly created instance would explode
        # on a tuple, and the signal receiver in invalidation.py would be the
        # thing that discovered it. Coercing here also pins the bounds: a caller
        # cannot accidentally build a `[]` range and make every adjacent
        # appointment collide.
        if self.time_range is not None and not isinstance(self.time_range, DateTimeTZRange):
            lower, upper = self.time_range
            self.time_range = DateTimeTZRange(lower, upper, RANGE_BOUNDS)
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.staff.display_name} · {self.service.name} · {self.starts_at:%Y-%m-%d %H:%M}"

    # --- derived views onto the range -----------------------------------
    #
    # Read-only on purpose. A writable `starts_at` would be a second source of
    # truth for the same fact, and the one the constraint does not read.

    @property
    def starts_at(self):
        return self.time_range.lower

    @property
    def ends_at(self):
        return self.time_range.upper

    @property
    def is_active(self):
        """Does this row currently occupy its slot as far as the constraint is
        concerned? Reads the shared tuple, never a literal list."""
        return self.status in ACTIVE_STATUSES

    @property
    def booked_ends_at(self):
        """Where the appointment was *scheduled* to end.

        Equal to `ends_at` until a `completed` transition trims the range to
        what actually happened. Recovered from `duration_snapshot` rather than
        stored a second time, which is the reason that snapshot is taken.
        """
        return self.starts_at + timedelta(minutes=self.duration_snapshot)

    @property
    def is_hold_expired(self):
        from django.utils import timezone

        return (
            self.status == AppointmentStatus.PENDING_PAYMENT
            and self.hold_expires_at is not None
            and self.hold_expires_at <= timezone.now()
        )

    @property
    def is_waiting(self):
        """The design's "waiting, not started" walk-in state.

        Derived, not a seventh status: the row is confirmed, its start time has
        passed, and nobody has hit Start. Adding a status would have meant
        touching the tuple the exclusion constraint filters on — a migration
        against the constraint that protects the product's core guarantee, to
        express something the two existing columns already say.
        """
        return self.status == AppointmentStatus.CONFIRMED and self.started_at is None

    def clean(self):
        if self.staff_id and self.shop_id and self.staff.shop_id != self.shop_id:
            raise ValidationError({"staff": "That staff member works at a different shop."})
        if self.service_id and self.shop_id and self.service.shop_id != self.shop_id:
            raise ValidationError({"service": "That service belongs to a different shop."})
        if self.client_id and self.shop_id and self.client.organization_id != self.organization_id:
            raise ValidationError({"client": "That client belongs to a different organization."})
