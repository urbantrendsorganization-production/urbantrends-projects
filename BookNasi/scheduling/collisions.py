"""A walk-in that overlaps something becomes a choice, never an error.

The design is explicit and this module exists to honour it: "If a walk-in
overlaps an existing booking, tap 3 becomes a single choice ('shorten to 12:00'
/ 'give it to Brian') — never a validation error above a form."

The reason is the posture. A client is standing at the chair. The staff member
has one wet hand on a phone. A red message above a form asks them to re-derive
the schedule in their head and try again, which on a busy Saturday means they
stop using the product and go back to the notebook — the exact regression
CLAUDE.md §4 names. A single button with a time on it does not.

So every option here is **computed from the engine**, never guessed in the UI.
The client app renders `options[0]` as the button and the rest behind "other
options". It does no arithmetic of its own: a UI that computed "shorten to
12:00" would be a second availability engine, in TypeScript, on the far side of
a network boundary.

## The four options, and the ranking

Ranked by what leaves the shop in the best state, which is not the same as what
is least work:

1. **`shorten`** — same stylist, same start, finish early. Offered *only* when
   the client still gets at least `SHORTEN_FLOOR` of the booked time. A four-hour
   braid trimmed to twenty minutes is not a shorter service, it is a different
   one at the same price, and `price_snapshot` would record the full amount
   against it. Ranked first when it qualifies because nothing is displaced: same
   person, same chair, same client, a few minutes earlier.
2. **`other_staff`** — same start, same full duration, a colleague who actually
   offers this service and is free. Second rather than first because it moves
   revenue to another stylist's name and needs that stylist to agree — but it
   delivers the whole service, which is why it beats a heavy trim.
3. **`later`** — same stylist, same full duration, the next start that fits
   today. Third because it asks the client to wait, and a walk-in who waits is a
   walk-in who may leave.
4. **`record_anyway`** — only ever offered when every overlap is *completed*
   work. Not a ranking peer: when it applies the others are answering a question
   nobody asked, because the staff member is recording the past rather than
   filling a chair. See `scheduling/statuses.py` for why the database permits
   this write and the engine still declines to offer it.

When nothing qualifies the list is empty and the UI says so plainly, naming the
appointment in the way — an empty state that names the next real option, per the
design's rule about never showing a generic apology.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from scheduling.availability import blockers, is_free, local_date
from scheduling.cache import facts_for_staff_day
from scheduling.loading import staff_for_service
from shops.durations import ServiceNotOffered, resolve_duration
from shops.models import MIN_SERVICE_MINUTES

#: How much of the booked time a shortened service must keep. Below this the
#: option is withheld rather than offered and quietly regretted: the client
#: agreed to a service, not to whatever fits.
SHORTEN_FLOOR = 0.75

#: How far past the collision `later` will look. One working day is the useful
#: horizon for somebody standing in the shop; beyond that they are booking, not
#: walking in, and the booking screen is the right tool.
LATER_HORIZON_HOURS = 12


@dataclass(frozen=True)
class Option:
    """One resolution, ready to render and ready to submit back unchanged.

    `kind` drives the copy; `staff_id`, `starts_at` and `duration_minutes` are
    exactly what the walk-in endpoint takes, so choosing an option is a resubmit
    and not a second negotiation.
    """

    kind: str
    label: str
    staff_id: str
    staff_name: str
    starts_at: datetime
    duration_minutes: int
    allow_over_completed: bool = False


def _eat(moment):
    from scheduling.availability import LOCAL_TZ

    return moment.astimezone(LOCAL_TZ).strftime("%-I:%M %p").lower()


def what_is_in_the_way(facts, *, starts_at, duration_minutes):
    """The overlapping spans, unpadded. Buffer is advisory for staff, so a
    walk-in starting the second the last client stood up is not "in the way" of
    itself — see `Policy`."""
    ends_at = starts_at + timedelta(minutes=duration_minutes)
    return [
        busy for busy in blockers(facts, 0) if busy.starts_at < ends_at and starts_at < busy.ends_at
    ]


def _shorten(facts, *, staff, starts_at, duration_minutes, in_the_way):
    """Finish at the first thing that is in the way, if enough time remains."""
    next_start = min(busy.starts_at for busy in in_the_way)
    available = int((next_start - starts_at) / timedelta(minutes=1))
    if available < MIN_SERVICE_MINUTES or available < duration_minutes * SHORTEN_FLOOR:
        return None
    return Option(
        kind="shorten",
        label=f"Shorten to {_eat(next_start)}",
        staff_id=str(staff.id),
        staff_name=staff.display_name,
        starts_at=starts_at,
        duration_minutes=available,
    )


def _other_staff(service, *, day, starts_at, exclude_staff_id):
    """A colleague free at this exact time, with their own duration for the job.

    Their duration, not the original stylist's — CLAUDE.md §3 is explicit that a
    senior does in 30 minutes what a junior takes 50 for, and handing the job
    over at the wrong length would put a lie straight into the calendar.
    """
    out = []
    for staff_row, link in staff_for_service(service):
        if str(staff_row.id) == str(exclude_staff_id):
            continue
        try:
            duration = resolve_duration(service=service, staff_service=link)
        except ServiceNotOffered:
            continue
        their_facts = facts_for_staff_day(staff_row, day)
        if not is_free(
            their_facts, starts_at=starts_at, duration_minutes=duration, buffer_minutes=0
        ):
            continue
        out.append(
            Option(
                kind="other_staff",
                label=f"Give it to {staff_row.display_name}",
                staff_id=str(staff_row.id),
                staff_name=staff_row.display_name,
                starts_at=starts_at,
                duration_minutes=duration,
            )
        )
    return out


def _later(facts, *, staff, starts_at, duration_minutes, in_the_way):
    """The next start that fits the whole service, on this stylist, today.

    Anchored to the end of each thing in the way rather than to a grid: staff
    writes are off-grid by design (decision (f)), and "11:47" is the honest
    answer when 11:47 is when the chair frees up.
    """
    horizon = starts_at + timedelta(hours=LATER_HORIZON_HOURS)
    candidates = sorted({busy.ends_at for busy in blockers(facts, 0) if busy.ends_at > starts_at})
    for candidate in candidates:
        if candidate > horizon:
            break
        if is_free(facts, starts_at=candidate, duration_minutes=duration_minutes, buffer_minutes=0):
            return Option(
                kind="later",
                label=f"Start at {_eat(candidate)} instead",
                staff_id=str(staff.id),
                staff_name=staff.display_name,
                starts_at=candidate,
                duration_minutes=duration_minutes,
            )
    return None


def resolve(*, staff, service, starts_at, duration_minutes, day=None):
    """Ranked options for a walk-in that the engine has refused.

    Returns `(options, in_the_way)`. `in_the_way` is the raw overlap list, so
    the caller can name what is blocking rather than only offering ways round
    it; an empty `options` with a non-empty `in_the_way` is a real state and the
    UI has copy for it.
    """
    day = day or local_date(starts_at)
    facts = facts_for_staff_day(staff, day)
    in_the_way = what_is_in_the_way(facts, starts_at=starts_at, duration_minutes=duration_minutes)
    if not in_the_way:
        return [], []

    # Backfill: every overlap is finished work, so the database would take this
    # write. Offer it and stop — the alternatives answer a different question.
    if all(not busy.is_active for busy in in_the_way):
        return [
            Option(
                kind="record_anyway",
                label="Record it anyway",
                staff_id=str(staff.id),
                staff_name=staff.display_name,
                starts_at=starts_at,
                duration_minutes=duration_minutes,
                allow_over_completed=True,
            )
        ], in_the_way

    options = []
    shorter = _shorten(
        facts,
        staff=staff,
        starts_at=starts_at,
        duration_minutes=duration_minutes,
        in_the_way=in_the_way,
    )
    if shorter is not None:
        options.append(shorter)
    options.extend(_other_staff(service, day=day, starts_at=starts_at, exclude_staff_id=staff.id))
    postponed = _later(
        facts,
        staff=staff,
        starts_at=starts_at,
        duration_minutes=duration_minutes,
        in_the_way=in_the_way,
    )
    if postponed is not None:
        options.append(postponed)
    return options, in_the_way
