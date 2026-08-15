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

**(f) Shop configuration binds the public and advises staff.** Slice 4. Opening
hours, closures, the grid and the buffer are rules on the public booking page
and advice on the staff screen — a 6:15 pm walk-in when hours end at 6:00 pm
must be recordable, and so must one at 11:04, which is on no grid. Collisions
are never advisory. See `Policy`.

**(e) A staff-day is a calendar date in EAT.** Opening and working hours are
stored as EAT wall-clock times; this module converts them to UTC instants
against the given date and returns UTC. Africa/Nairobi is UTC+3 with no DST —
CLAUDE.md §4 forbids a timezone abstraction layer — so the conversion is exact
and reversible.

Overnight *trading hours* (a 21:00–01:00 shop) are not expressible: slice 2's
`opening_hours_close_after_open` check constraint refuses them at the database —
see the class docstring on `shops.models.OpeningHours`, which points back here.
That is a real limitation and it is stated rather than hidden. It is also what
makes this file simple and the cache key correct: every *offered* slot lies
inside one EAT calendar date, so `(staff_id, EAT date)` partitions availability
with no overlap.

Since slice 4 the two sides of that are no longer symmetrical, and the asymmetry
is deliberate. Staff writes ignore opening hours (decision (f) below), so an
overnight **appointment** is already recordable — a 23:30 walk-in running to
03:30 exists today. That is handled rather than prevented: `loading.py` widens
its appointment window by a day either side, `invalidation.on_appointment_write`
drops both dates, and a test asserts the span shows busy on both. What is still
refused is overnight **hours**, because those are what the grid, the window
intersection and the key are derived from.

Lifting the constraint therefore needs a `closes_next_day` boolean, a second
window in `DayWindow`, and a decision about what a staff-day means once a shift
crosses midnight — the key and the engine have to keep agreeing, and slice 4's
machinery does not settle that.
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
class Busy:
    """An occupied span, and whether the database would defend it.

    `is_active` mirrors `statuses.ACTIVE_STATUSES` — the exclusion constraint's
    condition. It is carried here rather than re-derived because it is the one
    fact that distinguishes "somebody else has this chair" from "this time was
    already worked", and slice 4's collision resolver has to tell a staff member
    which. A completed appointment blocks the *offer* and not the *write*; see
    `scheduling/statuses.py` for why that divergence exists.
    """

    starts_at: datetime
    ends_at: datetime
    is_active: bool = True
    #: Which appointment this span belongs to, as a string. Carried so that a
    #: booking being *moved* can be excluded from the check that decides where
    #: it may move to — see `is_free`. Without it a client rescheduling to
    #: 11:00 on the same day is blocked by their own 10:00 booking, which is
    #: the booking that is about to stop existing at 10:00.
    #:
    #: Defaulted so the many places that construct a `Busy` for a test or a
    #: derived interval do not have to invent one.
    appointment_id: str = ""

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
    busy: tuple[Busy, ...] = field(default_factory=tuple)
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
    """The caller's answers to (c) and (d), plus who the rules bind.

    ## Shop configuration is a rule for the public and advice for staff

    Slice 4's decision, and the reason `enforce_shop_config` exists. A stylist
    taking a 6:15 pm walk-in when the shop's hours end at 6:00 pm must succeed.
    So must one recorded at 11:04, which is not on any 15-minute grid, and one
    started the moment the previous client left, which is inside the turnaround
    buffer. Every one of those is a staff member describing something that is
    physically happening in front of them. Software that answers "no" to a fact
    is software that gets worked around, and a calendar that is worked around
    stops matching the shop within a week — which is the adoption failure
    CLAUDE.md §4 is about.

    `enforce_shop_config=False` therefore switches off exactly four things:
    opening hours, dated closures, the slot grid, and the buffer. It is one
    decision, so it is one flag; splitting it into four would invite three of
    them being switched back on by someone reading only their own line.

    What it does **not** switch off is collisions. Two people cannot occupy one
    chair, the exclusion constraint would refuse the write regardless, and the
    refusal would arrive as an error with no remedy attached. Checking it here
    is what lets `scheduling/collisions.py` turn it into a choice instead —
    "shorten to 12:00" or "give it to Brian" — which is the shape the design
    asks for and the shape a standing, one-handed staff member can act on.

    A consequence worth stating because tests depend on it: under
    `Policy.for_staff()`, `SlotUnavailable` can *only* mean a collision. Nothing
    else is left to refuse.
    """

    min_lead_minutes: int = 0
    horizon_days: int | None = None
    #: Opening hours, closures, the slot grid, the buffer. See above.
    enforce_shop_config: bool = True
    #: Backfill. Set only after a staff member has been shown the overlap and
    #: chosen to record it anyway — see `scheduling/collisions.py`. Never
    #: reachable from the public API, and it does not weaken the constraint:
    #: an overlap with a *live* booking is still refused, here and in Postgres.
    allow_over_completed: bool = False

    def __post_init__(self):
        # "One decision, one flag" made structural. A lead time or a horizon
        # alongside `enforce_shop_config=False` would be silently ignored by
        # `is_bookable_start`, which is exactly the kind of quiet no-op that
        # takes an afternoon to find.
        if not self.enforce_shop_config and (self.min_lead_minutes or self.horizon_days):
            raise ValueError(
                "enforce_shop_config=False means collisions only; a lead time or "
                "horizon set alongside it would never be applied."
            )

    @classmethod
    def for_public(cls, shop):
        return cls(min_lead_minutes=shop.min_lead_minutes, horizon_days=shop.booking_horizon_days)

    @classmethod
    def for_staff(cls, *, allow_over_completed=False):
        """Collisions only.

        No lead time — a walk-in starts now. No horizon — staff can book a
        regular six months out if the client asks. No shop configuration —
        see above.
        """
        return cls(
            min_lead_minutes=0,
            horizon_days=None,
            enforce_shop_config=False,
            allow_over_completed=allow_over_completed,
        )


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


def blockers(facts, buffer_minutes, *, active_only=False, exclude_appointment_id=""):
    """Existing appointments, each holding its own trailing buffer — decision (b).

    `active_only` drops completed work, which the database would also let a
    write straight through. Used by the backfill path only: a staff member
    recording, at 16:00, the shave they did at 11:15 and never entered.
    """
    padding = timedelta(minutes=buffer_minutes)
    return tuple(
        Busy(b.starts_at, b.ends_at + padding, b.is_active, b.appointment_id)
        for b in facts.busy
        # `and exclude_appointment_id` first, and it is load-bearing: `Busy`
        # defaults `appointment_id` to `""` for every span built in a test or
        # derived from a leave block, and the default for this parameter is also
        # `""`. Comparing them without the truthiness guard excluded *every*
        # unattributed busy span from every check — silently making the whole
        # day look free.
        if (b.is_active or not active_only)
        and not (exclude_appointment_id and b.appointment_id == exclude_appointment_id)
    )


def _collides(blocked, starts_at, ends_at, buffer_minutes):
    candidate = Interval(starts_at, ends_at + timedelta(minutes=buffer_minutes))
    return [busy for busy in blocked if candidate.overlaps(busy)]


def is_free(
    facts,
    *,
    starts_at,
    duration_minutes,
    buffer_minutes,
    active_only=False,
    exclude_appointment_id="",
):
    """Does this span collide with anything already on this staff member's day?

    The one check no policy switches off — see `Policy`. Split out so that the
    offer list below and the write check further down share a single
    implementation of what "in the way" means; two would diverge on the first
    change to the buffer rule.

    `buffer_minutes` is passed rather than read off `facts` because it is a
    policy question, not a fact: the shop's turnaround applies to what the
    public is offered, and not to a staff member recording a walk-in that
    started the moment the last client stood up.
    """
    if duration_minutes <= 0:
        return False
    ends_at = starts_at + timedelta(minutes=duration_minutes)
    blocked = blockers(
        facts,
        buffer_minutes,
        active_only=active_only,
        exclude_appointment_id=exclude_appointment_id,
    )
    return not _collides(blocked, starts_at, ends_at, buffer_minutes)


def derive_slots(facts, *, duration_minutes, policy, now, exclude_appointment_id=""):
    """The bookable starts for one staff member, one service, one day.

    **The offer list.** Always bounded by the working window and always on the
    grid, whatever the policy says — an enumeration needs bounds, and a staff
    member picking a time for next Thursday should be picking from the same
    tidy list a client sees. `enforce_shop_config` governs what may be *written*
    (`is_bookable_start`), not what is *offered*, and the two are different
    questions: the design's walk-in flow never picks from this list at all, it
    defaults to now.

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
    # `exclude_appointment_id` is slice 7's reschedule: the booking being moved
    # does not block the slot it is moving to. Empty for every other caller, and
    # a `Busy` with no id can never match it.
    blocked = blockers(facts, facts.buffer_minutes, exclude_appointment_id=exclude_appointment_id)

    slots = []
    for start in _grid_starts(window, facts.day, facts.slot_interval_minutes):
        if start < earliest or start >= latest:
            continue
        end = start + duration
        # The service itself must finish before closing. Its trailing buffer
        # need not: there is no following client to turn the chair around for.
        if end > window.ends_at:
            break
        if _collides(blocked, start, end, facts.buffer_minutes):
            continue
        slots.append(Slot(start, end))
    return tuple(slots)


def is_bookable_start(
    facts, *, starts_at, duration_minutes, policy, now, exclude_appointment_id=""
):
    """May this exact instant be written?

    CLAUDE.md §4: "Never trust a client-supplied slot as valid — always
    re-derive on write." `booking.create_appointment` calls this rather than
    doing its own arithmetic, so the write path and the read path cannot
    disagree about what is bookable.

    Two branches, because slice 4 established that shop configuration binds the
    public and advises staff — see `Policy`.

    Under the public policy the answer is **membership in the offer list**, not
    a second implementation of it. A re-derivation here that agreed with
    `derive_slots` today would diverge from it on the first change to the buffer
    rule, and the failure would be a client shown a slot the write path then
    refuses — at the moment they are being asked for money.

    Under `Policy.for_staff()` there is no list to be a member of: 11:04 is not
    on the grid and 18:15 is outside the window, and both are things that are
    actually happening. What is left is the collision check — literally nothing
    else, including no lower bound in time, because recording the shave you did
    at 11:15 and forgot to enter is the case backfill exists for. That is what
    makes `SlotUnavailable` mean exactly one thing on the staff path.

    `now` is therefore unused on the relaxed branch, and stays in the signature
    because the caller does not know which branch it will take.

    `exclude_appointment_id` is slice 7's reschedule: the booking being moved
    must not block the slot it is moving to. Excluding it here rather than in
    the caller keeps the write check and the offer list agreeing, which is the
    whole point of this function — a client is shown their own 11:00 as free
    and the write must not then refuse it.
    """
    if duration_minutes <= 0:
        return False
    if policy.enforce_shop_config:
        return any(
            slot.starts_at == starts_at
            for slot in derive_slots(
                facts,
                duration_minutes=duration_minutes,
                policy=policy,
                now=now,
                exclude_appointment_id=exclude_appointment_id,
            )
        )
    return is_free(
        facts,
        starts_at=starts_at,
        duration_minutes=duration_minutes,
        buffer_minutes=0,
        active_only=policy.allow_over_completed,
        exclude_appointment_id=exclude_appointment_id,
    )
