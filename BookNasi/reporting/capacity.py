"""How many minutes each stylist was actually available, over a range.

The denominator of the utilisation bar. Revenue per staff without it is a
ranking of who works the most days: the stylist who does three afternoons a week
sits at the bottom of the table and looks like a problem, when the number that
would tell the owner something is how full those three afternoons were.

## Why this does not call the availability engine per day

`loading.gather_shop_day` is five queries per shop-day. A 30-day report on a
three-shop organization would be 450 queries, and a 90-day one 1,350 — for a
screen the design explicitly describes as cached aggregates with no realtime
requirement. So the weekly pattern is fetched **once** (opening hours, working
hours) alongside every closure and leave row that touches the range, and the
per-day arithmetic happens in Python.

## Why it is still the engine's answer

The precedence rules — a dated closure beats working hours beats opening hours,
and availability is the *intersection* of the shop being open and the person
being in — are not restated here. `StaffDayFacts.window` is constructed and
read, exactly as `gather_shop_day` constructs and the engine reads it. This
module decides only which rows feed it.

That is a real risk of divergence and it has a test pointed straight at it:
`test_capacity.py` asserts that for a given shop-day this module's window is
identical to `gather_shop_day`'s, including the awkward cases (closure, leave,
a stylist rostered outside opening hours). If the two ever disagree, the
utilisation column is quietly wrong in whichever direction nobody checks.

## What capacity is not

It is not "hours the shop could have sold". Buffers between services are
excluded from neither side: a stylist's window includes the turnaround time,
and the appointments measured against it do not, so nobody reaches 100 %. That
is honest — 100 % utilisation would mean a stylist who never swept up — and it
means the number is only ever compared against other stylists in the same shop,
which is the comparison the table is for.
"""

from collections import defaultdict

from scheduling.availability import Interval, StaffDayFacts, to_utc
from shops.models import Leave, OpeningHours, ShopClosure, WorkingHours

MINUTE_SECONDS = 60


def windows_for(shop, staff_rows, period):
    """`{staff_id: {date: Interval | None}}` for every day in `period`.

    None means "not available at all that day" — shut, on leave, not rostered,
    or rostered outside opening hours. A caller counting days worked should
    count the non-None entries rather than the keys.
    """
    staff_ids = [row.id for row in staff_rows]
    org = shop.organization_id

    closures = list(
        ShopClosure.objects.for_org(org).filter(
            shop=shop, starts_on__lte=period.ends_on, ends_on__gte=period.starts_on
        )
    )
    opening = {row.weekday: row for row in OpeningHours.objects.for_org(org).filter(shop=shop)}
    working = defaultdict(dict)
    for row in WorkingHours.objects.for_org(org).filter(staff_id__in=staff_ids):
        working[row.staff_id][row.weekday] = row

    leave = defaultdict(list)
    for row in Leave.objects.for_org(org).filter(
        staff_id__in=staff_ids, starts_on__lte=period.ends_on, ends_on__gte=period.starts_on
    ):
        leave[row.staff_id].append(row)

    out = {staff_id: {} for staff_id in staff_ids}
    for day in period.dates():
        is_closed = any(closure.covers(day) for closure in closures)
        open_row = None if is_closed else opening.get(day.weekday())
        shop_window = (
            None
            if open_row is None
            else Interval(to_utc(day, open_row.opens_at), to_utc(day, open_row.closes_at))
        )
        for staff_id in staff_ids:
            work_row = working[staff_id].get(day.weekday())
            on_leave = any(row.covers(day) for row in leave[staff_id])
            staff_window = (
                None
                if work_row is None or on_leave
                else Interval(to_utc(day, work_row.starts_at), to_utc(day, work_row.ends_at))
            )
            # Constructed rather than intersected by hand: `.window` is the
            # engine's own rule, and this module deliberately owns no copy of it.
            facts = StaffDayFacts(
                staff_id=str(staff_id),
                day=day,
                shop_window=shop_window,
                staff_window=staff_window,
            )
            out[staff_id][day] = facts.window
    return out


def minutes_for(shop, staff_rows, period):
    """`{staff_id: minutes}` — total available minutes across the whole range."""
    windows = windows_for(shop, staff_rows, period)
    return {
        staff_id: sum(
            int((window.ends_at - window.starts_at).total_seconds() // MINUTE_SECONDS)
            for window in by_day.values()
            if window is not None
        )
        for staff_id, by_day in windows.items()
    }
