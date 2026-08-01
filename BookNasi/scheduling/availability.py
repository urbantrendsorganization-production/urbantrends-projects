"""The availability engine. Derived, never stored — CLAUDE.md §4.

**Nothing in this module touches the database, the cache, or the clock.** Every
input arrives as a value; `now` is passed in. That is not tidiness, it is what
makes the highest-risk code in the repo testable without a calendar, without
Redis, and without a fixture that drifts as the real date moves. `loading.py`
does the queries, `cache.py` wraps `loading.py`, and both call into here. The
arrows never point the other way.

## The rules, in the order they are applied

    shop closed for the day (dated closure)      -> nothing
    shop not open on this weekday                -> nothing
    staff on leave                               -> nothing
    staff not working this weekday               -> nothing
    open hours ∩ working hours                   -> the window
    - existing appointments, padded by buffer    -> the free intervals
    - service duration for THIS staff member     -> the slots that fit
    - minimum lead time, booking horizon         -> the slots still offerable

A closure beats working hours beats opening hours. The order matters: a stylist
rostered on a public holiday is not available, and the closure is the fact that
wins.

## Decisions this module encodes

**(a) Slots land on a clock grid, not packed against the previous booking.**
`Shop.slot_interval_minutes`, default 15, anchored to midnight EAT — so a shop
opening at 08:00 offers 08:00, 08:15, 08:30. Salons think and speak in clock
times ("come at half ten"), the design draws three chips per row of equal
weight, and a packed layout produces times like 11:47 that read as a mistake.
The cost is real and worth naming: packing fits more work into a day, and a
grid can strand a 10-minute gap that a walk-in could have used. Walk-ins are
recorded directly rather than picked from this grid, so that gap is recoverable
where it matters most.

**(b) The buffer is applied after a service, never before.** An existing
appointment `[s, e)` blocks `[s, e + buffer)`, and a candidate `[c, c + dur)`
claims `[c, c + dur + buffer)`. Applying it on both sides would put *two*
buffers between two consecutive appointments — 30 minutes of turnaround for one
sweep-up — and would push the first appointment of the day later than opening
for no reason. Applied after only, the gap between any two appointments is
exactly one buffer, in both directions, which is what a shop actually means by
"give me fifteen minutes between clients". The trailing buffer is not required
against closing time: there is no next client to turn the chair around for.

**(e) A staff-day is a calendar date in EAT.** Opening and working hours are
stored as EAT wall-clock times; this module converts them to UTC instants
against the given date and returns UTC. Africa/Nairobi is UTC+3 with no DST —
CLAUDE.md §4 forbids a timezone abstraction layer — so the conversion is exact
and reversible.

Overnight trading (a 21:00–01:00 shop) is *not expressible* in v1: slice 2's
`opening_hours_end_after_start` check constraint refuses it at the database.
That is a real limitation and it is stated rather than hidden. It is also what
makes this file simple and the cache key correct: every slot lies inside one EAT
calendar date, so `(staff_id, EAT date)` partitions availability with no
overlap. Adding overnight shops later means a `closes_next_day` boolean, a
second window in `DayWindow`, and a cache key that invalidates two days per
write — not a reshape of anything here.
"""

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings

#: EAT. Not a per-org setting and not a user preference — CLAUDE.md §4 is
#: explicit that there is one timezone and no abstraction over it.
LOCAL_TZ = ZoneInfo(settings.DISPLAY_TIME_ZONE)
UTC = ZoneInfo("UTC")

MINUTE = timedelta(minutes=1)


@dataclass(frozen=True, order=True)
class Slot:
    """A bookable start, in UTC. Rendered in EAT by the API layer."""

    starts_at: datetime
    ends_at: datetime

    @property
    def duration_minutes(self):
        return int((self.ends_at - self.starts_at) / MINUTE)


@dataclass(frozen=True)
class Interval:
    """A half-open span of UTC time. Used for both the working window and the
    busy periods, so the arithmetic below has one shape to reason about."""

    starts_at: datetime
    ends_at: datetime

    def overlaps(self, other):
        return self.starts_at < other.ends_at and other.starts_at < self.ends_at


@dataclass(frozen=True)
class StaffDayFacts:
    """Everything the engine needs about one staff member on one EAT date.

    Service-independent on purpose. Duration is *not* here — it varies per
    service and per staff member, and keeping it out is what lets `cache.py`
    key on `(staff_id, date)` alone, exactly as specified, with no service
    dimension to fan out across on invalidation.

    Plain values only, so this can be pickled into Redis and compared in a test
    without a database.
    """

    staff_id: str
    day: object  # datetime.date, in EAT
    #: None when the shop is shut that day — closure or no opening row.
    shop_window: Interval | None = None
    #: None when the staff member is off — leave or no working row.
    staff_window: Interval | None = None
    busy: tuple[Interval, ...] = field(default_factory=tuple)
    buffer_minutes: int = 0
    slot_interval_minutes: int = 15

    @property
    def window(self):
        """Where the shop being open and this person working coincide."""
        if self.shop_window is None or self.staff_window is None:
            return None
        starts_at = max(self.shop_window.starts_at, self.staff_window.starts_at)
        ends_at = min(self.shop_window.ends_at, self.staff_window.ends_at)
        if ends_at <= starts_at:
            # A stylist rostered outside the shop's opening hours. Not an error
            # — an owner can save this — and not availability either.
            return None
        return Interval(starts_at, ends_at)


@dataclass(frozen=True)
class Policy:
    """The caller's answers to (c) and (d).

    Staff booking at the chair pass `Policy.for_staff()`: a walk-in starts now,
    and refusing it because `now + 30min` is in the future would make the
    product unusable for the majority of Kenyan salon trade.
    """

    min_lead_minutes: int = 0
    horizon_days: int | None = None

    @classmethod
    def for_public(cls, shop):
        return cls(min_lead_minutes=shop.min_lead_minutes, horizon_days=shop.booking_horizon_days)

    @classmethod
    def for_staff(cls):
        """No lead time, no horizon. Staff can record what is happening now and
        can book a regular six months out if the client asks."""
        return cls(min_lead_minutes=0, horizon_days=None)


def local_midnight(day):
    """The UTC instant at which this EAT calendar date begins."""
    return datetime.combine(day, time.min, tzinfo=LOCAL_TZ).astimezone(UTC)


def to_utc(day, wall_clock):
    """An EAT wall-clock time on an EAT date, as a UTC instant."""
    return datetime.combine(day, wall_clock, tzinfo=LOCAL_TZ).astimezone(UTC)


def local_date(moment):
    """Which staff-day a UTC instant belongs to. The inverse of the above, and
    the function `cache.py` uses to build its key — so the key and the engine
    cannot disagree about where a day starts."""
    return moment.astimezone(LOCAL_TZ).date()


def _grid_starts(window, day, interval_minutes):
    """Candidate starts on the clock grid, anchored to midnight EAT.

    Anchored to midnight rather than to opening time so that two shops with the
    same interval offer the same clock times, and so that changing opening hours
    by five minutes does not shift every slot in the day.
    """
    step = timedelta(minutes=interval_minutes)
    anchor = local_midnight(day)

    elapsed = window.starts_at - anchor
    steps_in = -(-elapsed // step)  # ceiling division: first grid point at or after opening
    candidate = anchor + steps_in * step

    while candidate < window.ends_at:
        yield candidate
        candidate += step


def derive_slots(facts, *, duration_minutes, policy, now):
    """The bookable starts for one staff member, one service, one day.

    Pure. Returns a tuple so a caller cannot mutate a cached result, and so two
    derivations can be compared with `==` in the cache-equivalence test.

    `now` is a required keyword and never read from the clock, which is what
    makes a "slot in 90 seconds" test deterministic.
    """
    window = facts.window
    if window is None or duration_minutes <= 0:
        return ()

    earliest = max(window.starts_at, now + timedelta(minutes=policy.min_lead_minutes))
    latest = window.ends_at
    if policy.horizon_days is not None:
        # The horizon is a whole number of days, so it ends at the close of the
        # last permitted EAT date rather than at this time-of-day N days out.
        # Otherwise the set of offerable days would shift through the afternoon.
        horizon_end = local_midnight(local_date(now) + timedelta(days=policy.horizon_days + 1))
        latest = min(latest, horizon_end)
    if latest <= earliest:
        return ()

    duration = timedelta(minutes=duration_minutes)
    buffer_ = timedelta(minutes=facts.buffer_minutes)
    # Each existing appointment holds its own trailing buffer — decision (b).
    blocked = tuple(Interval(b.starts_at, b.ends_at + buffer_) for b in facts.busy)

    slots = []
    for start in _grid_starts(window, facts.day, facts.slot_interval_minutes):
        if start < earliest or start >= latest:
            continue
        end = start + duration
        # The service itself must finish before closing. Its trailing buffer
        # need not: there is no following client to turn the chair around for.
        if end > window.ends_at:
            break
        candidate = Interval(start, end + buffer_)
        if any(candidate.overlaps(busy) for busy in blocked):
            continue
        slots.append(Slot(start, end))
    return tuple(slots)


def is_bookable_start(facts, *, starts_at, duration_minutes, policy, now):
    """Is this exact instant one of the derived slots?

    CLAUDE.md §4: "Never trust a client-supplied slot as valid — always
    re-derive on write." `booking.create_appointment` calls this rather than
    doing its own arithmetic, so the write path and the read path cannot
    disagree about what is bookable.
    """
    return any(
        slot.starts_at == starts_at
        for slot in derive_slots(facts, duration_minutes=duration_minutes, policy=policy, now=now)
    )
