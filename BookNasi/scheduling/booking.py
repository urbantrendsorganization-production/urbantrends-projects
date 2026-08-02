"""The one function that creates an appointment.

Slices 4 (staff view / walk-ins) and 5 (public booking) both call
`create_appointment`, so it lands here, once. A second creation path would be a
second opinion about what "available" means, and the two would diverge on the
first change to the buffer rule.

## The two failures, kept separate

`SlotUnavailable` — the engine says no. The slot is outside working hours, the
shop is closed, someone else's appointment is already in the way, the lead time
has passed. We knew before we tried.

`SlotTaken` — the engine said yes and the *database* said no. Two people
confirmed the same slot inside the same instant and this one lost the race. This
is CLAUDE.md §4's scenario, and it is the reason the exclusion constraint exists
rather than an `if slot_is_free` check.

They render to the client as the same sentence ("that slot was just taken, pick
another"), and they must stay distinguishable in logs and metrics. A rising
`SlotTaken` rate means genuine contention; a rising `SlotUnavailable` rate means
a client is being shown slots that are not real, which is a bug in the engine or
a stale cache.

## Why the constraint name is matched exactly

Catching a bare `IntegrityError` and calling it "slot just taken" would render
*every* integrity failure in the codebase as that message — a null violation, a
broken FK, a check constraint on the snapshots — and each of those would then be
invisible, reported to the client as bad luck and to us as nothing at all. So
the wrapper matches `no_overlapping_appointments` specifically, structurally
where psycopg gives us the constraint name and by substring only as a fallback,
and re-raises everything else untouched.

## The deadlock, and the advisory lock

Two *genuinely* simultaneous inserts on the same slot do not both reach the
constraint check cleanly. Each transaction has to wait on the other to find out
whether its own row overlaps, and Postgres resolves that by killing one with

    deadlock detected
    CONTEXT: while checking exclusion constraint on tuple (0,1)
             in relation "appointments"

which arrives as `OperationalError` (SQLSTATE 40P01), **not**
`IntegrityError` — so a wrapper that only catches the latter lets it through as
a 500, at the precise moment a client is being asked for money. This is not
theoretical: the two-process test in `tests/test_cross_process_race.py` produced
it on the first run, and the thread-based tests never did, because their timing
always skewed by enough to serialise the checks.

Two things address it, and both are kept:

1. **A per-staff transaction-scoped advisory lock**, taken immediately before
   the insert. Concurrent bookings for one staff member are ordered, the
   exclusion check never has to wait on a peer, and the loser gets a clean
   constraint violation. Different staff never contend.
2. **Deadlock recognition** in the wrapper, narrowed to this constraint on this
   table. The lock covers this function; the recognition covers any future
   caller that inserts an appointment without going through it.

CLAUDE.md §4 forbids *replacing* the constraint with a lock — "the constraint
stays regardless of what else you add". It stays. The lock does not decide
anything; it only stops two transactions from asking Postgres the same question
at the same instant. Remove the lock and the code is still correct, just ruder
about how it says no.
"""

import uuid
from contextlib import contextmanager
from datetime import timedelta

from django.db import IntegrityError, OperationalError, connection, transaction
from django.utils import timezone

from scheduling.availability import Policy, is_bookable_start, local_date
from scheduling.cache import facts_for_staff_day
from scheduling.models import NO_OVERLAP_CONSTRAINT, REQUEST_ID_CONSTRAINT, Appointment
from scheduling.statuses import AppointmentStatus, BookingSource
from shops.durations import resolve_duration


class SlotUnavailable(Exception):
    """The engine does not offer this start. Known before the write."""

    def __init__(self, message="That time is not available.", *, starts_at=None, staff=None):
        self.starts_at = starts_at
        self.staff = staff
        super().__init__(message)


class SlotTaken(Exception):
    """Lost the race. The database refused the overlap.

    Distinct from SlotUnavailable so that "we were beaten by 200ms" and "we
    offered something that was never bookable" never collapse into one number.
    """

    def __init__(self, message="That slot was just taken.", *, starts_at=None, staff=None):
        self.starts_at = starts_at
        self.staff = staff
        super().__init__(message)


def _violated_constraint(exc):
    """The constraint name from a psycopg error, when it is there.

    Django wraps the driver exception and hangs the original off `__cause__`;
    psycopg 3 carries the name on `diag`. Both `getattr` chains are defensive
    because this runs inside an exception handler, where a second failure would
    replace a useful error with a confusing one.
    """
    diag = getattr(getattr(exc, "__cause__", None), "diag", None)
    return getattr(diag, "constraint_name", None)


def _is_overlap_violation(exc):
    name = _violated_constraint(exc)
    if name is not None:
        return name == NO_OVERLAP_CONSTRAINT
    # Fallback only for a driver that does not populate `diag`. Kept narrow: it
    # matches the constraint name, not the word "overlap".
    return NO_OVERLAP_CONSTRAINT in str(exc)


#: SQLSTATE 40P01. See the module docstring — this is what two simultaneous
#: bookings look like when neither has taken the advisory lock.
DEADLOCK_SQLSTATE = "40P01"


def _is_exclusion_deadlock(exc):
    """A deadlock that Postgres raised *while checking this constraint*.

    Deliberately narrow. A deadlock elsewhere in a transaction that happens to
    contain an appointment insert is a different problem and must keep its own
    error — turning every 40P01 into "that slot was just taken" would hide real
    lock-ordering bugs behind a friendly sentence.

    Postgres does not put a constraint name on `diag` for a deadlock, so the
    table name in the CONTEXT line is the only structured thing available. That
    is a string match and it is acknowledged as one; the advisory lock in
    `create_appointment` is what makes this path rare enough for that to be an
    acceptable last resort rather than the primary defence.
    """
    cause = getattr(exc, "__cause__", None)
    if getattr(cause, "sqlstate", None) != DEADLOCK_SQLSTATE:
        return False
    message = str(exc)
    return "exclusion constraint" in message and Appointment._meta.db_table in message


@contextmanager
def slot_taken_on_conflict(*, starts_at=None, staff=None):
    """Turn a loss of *this* slot, and nothing else, into SlotTaken.

    Catches both shapes the loss can take: the ordinary constraint violation,
    and the deadlock two simultaneous checks produce. Everything else is
    re-raised untouched.
    """
    try:
        yield
    except IntegrityError as exc:
        if _is_overlap_violation(exc):
            raise SlotTaken(starts_at=starts_at, staff=staff) from exc
        raise
    except OperationalError as exc:
        if _is_exclusion_deadlock(exc):
            raise SlotTaken(starts_at=starts_at, staff=staff) from exc
        raise


def _advisory_key(staff_id):
    """A stable bigint for `pg_advisory_xact_lock`, derived from the staff UUID.

    Python's `hash()` is salted per process and would give two web workers
    different keys for the same stylist, which is the one thing this must not
    do. The UUID's own integer value is stable everywhere; the mask keeps it
    inside a positive signed 64-bit range. A collision between two staff members
    costs a little needless serialisation and nothing else.
    """
    return uuid.UUID(str(staff_id)).int & ((1 << 62) - 1)


def order_bookings_for(staff_id):
    """Serialise concurrent inserts for one staff member.

    Transaction-scoped: released on commit or rollback, with no unlock call to
    forget. Does not decide whether the slot is free — the constraint still
    does that, and still would if this line were deleted.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_advisory_key(staff_id)])


def default_status_for(source):
    """Online bookings hold the slot while the STK push is outstanding; anything
    entered by a person standing in the shop is already real.

    Slice 6 owns the push itself. This only decides what the row starts as.
    """
    if source == BookingSource.ONLINE:
        return AppointmentStatus.PENDING_PAYMENT
    return AppointmentStatus.CONFIRMED


def existing_for_request(shop, client_request_id):
    """The row a previous attempt at this same request already wrote, if any.

    Slice 4's staff app renders a walk-in optimistically and retries the write
    when the shop's connection drops mid-request — at which point the server may
    well have committed the row that the phone never heard about. Without this,
    the retry inserts a second appointment, the exclusion constraint refuses it,
    and the staff member is told their own walk-in just took their slot.
    """
    if not client_request_id:
        return None
    return (
        Appointment.objects.for_org(shop.organization_id)
        .filter(shop=shop, client_request_id=client_request_id)
        .first()
    )


def create_appointment(
    *,
    staff,
    service,
    starts_at,
    source,
    client=None,
    status=None,
    now=None,
    policy=None,
    duration_minutes=None,
    client_request_id=None,
):
    """Book `service` with `staff` at `starts_at`, or raise.

    `starts_at` is a UTC instant and is **re-derived, never trusted** —
    CLAUDE.md §4. The caller may have computed it from a cached slot list that
    was already stale when it rendered.

    `duration_minutes` overrides the resolved duration and exists for exactly
    one caller: a staff member who has been shown an overlap and chosen
    "shorten to 12:00". It never shortens silently — the value comes back from
    an `Option` the engine itself produced. `duration_snapshot` records the
    shortened length, because that is what was sold.

    Returns the created `Appointment`.
    """
    now = now or timezone.now()

    already = existing_for_request(staff.shop, client_request_id)
    if already is not None:
        return already

    if policy is None:
        policy = (
            Policy.for_public(staff.shop) if source == BookingSource.ONLINE else Policy.for_staff()
        )

    # Iterating `.all()` rather than filtering in SQL so a caller that has
    # already prefetched the links — the staff day view will — pays nothing.
    link = next((row for row in service.staff_links.all() if row.staff_id == staff.id), None)
    # Raises ServiceNotOffered when this person does not do this job. Not caught
    # here: it is a programming error on the write path, not a busy calendar.
    duration = duration_minutes or resolve_duration(service=service, staff_service=link)

    day = local_date(starts_at)
    facts = facts_for_staff_day(staff, day)
    if not is_bookable_start(
        facts, starts_at=starts_at, duration_minutes=duration, policy=policy, now=now
    ):
        raise SlotUnavailable(starts_at=starts_at, staff=staff)

    ends_at = starts_at + timedelta(minutes=duration)
    resolved_status = status or default_status_for(source)
    appointment = Appointment(
        shop=staff.shop,
        staff=staff,
        service=service,
        client=client,
        time_range=(starts_at, ends_at),
        status=resolved_status,
        source=source,
        # Snapshots, taken here and never refreshed. See Appointment's docstring.
        price_snapshot=service.price,
        # CLAUDE.md §12 and the design's walk-in screen: "Deposit — Not for
        # walk-ins". Nothing was pushed and nothing is owed up front, so the
        # snapshot records zero rather than an amount nobody was asked for.
        deposit_snapshot=0 if source == BookingSource.WALK_IN else service.deposit_amount,
        duration_snapshot=duration,
        client_request_id=client_request_id or None,
        started_at=now if resolved_status == AppointmentStatus.IN_PROGRESS else None,
        # A `pending_payment` row *is* a hold, so it is never written without an
        # expiry. Set here rather than by the caller so no code path can create
        # one the sweep in `tasks.py` would then find with a null expiry and
        # have to guess about.
        hold_expires_at=(
            now + timedelta(minutes=staff.shop.hold_ttl_minutes)
            if resolved_status == AppointmentStatus.PENDING_PAYMENT
            else None
        ),
    )

    try:
        with slot_taken_on_conflict(starts_at=starts_at, staff=staff):
            # `atomic` so the constraint violation rolls back cleanly and the
            # connection is usable afterwards — without it the failed statement
            # poisons the surrounding transaction and the caller's next query
            # dies with a confusing TransactionManagementError instead.
            with transaction.atomic():
                order_bookings_for(staff.id)
                appointment.save()
    except IntegrityError as exc:
        # Two retries of one offline write, racing each other. The check above
        # catches the ordinary case where the first attempt has already
        # committed; this catches the narrow one where both are in flight. The
        # unique constraint decides, and the loser returns the row the winner
        # wrote — which is the row the phone was asking for.
        settled = (
            existing_for_request(staff.shop, client_request_id)
            if REQUEST_ID_CONSTRAINT in str(exc)
            else None
        )
        if settled is None:
            raise
        return settled

    return appointment
