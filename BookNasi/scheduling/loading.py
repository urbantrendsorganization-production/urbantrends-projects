"""Turning rows into `StaffDayFacts`. The only module here that queries.

Split from `availability.py` so that the engine stays a pure function, and from
`cache.py` so that the cache can be removed entirely without touching either.
The layering is:

    views / booking  ->  cache.py  ->  loading.py  ->  the database
                    \\-> availability.py (pure, called with the facts)

`gather_shop_day` fetches a whole shop-day for every staff member in a fixed
number of queries — five, asserted by a test. The staff day view shows eight
stylists side by side; doing this per-staff would be forty queries before anyone
had scrolled.
"""

from collections import defaultdict
from datetime import timedelta

from scheduling.availability import Busy, Interval, StaffDayFacts, local_midnight, to_utc
from scheduling.statuses import BLOCKING_STATUSES
from shops.models import Leave, OpeningHours, ShopClosure, Staff, WorkingHours


def gather_shop_day(shop, day, *, staff=None):
    """Facts for every bookable staff member at `shop` on the EAT date `day`.

    Returns `{staff_id: StaffDayFacts}`. Fixed query count regardless of how
    many staff there are.
    """
    staff_rows = list(staff) if staff is not None else list(shop.staff.filter(is_active=True))
    staff_ids = [s.id for s in staff_rows]

    # 1. Is the shop shut for the day? A dated closure beats everything else,
    #    so this is checked first and short-circuits the rest of the shape.
    closed = ShopClosure.objects.for_org(shop.organization_id).filter(
        shop=shop, starts_on__lte=day, ends_on__gte=day
    )
    is_closed = closed.exists()

    # 2. The weekly pattern.
    opening = (
        None
        if is_closed
        else OpeningHours.objects.for_org(shop.organization_id)
        .filter(shop=shop, weekday=day.weekday())
        .first()
    )
    shop_window = (
        None
        if opening is None
        else Interval(to_utc(day, opening.opens_at), to_utc(day, opening.closes_at))
    )

    # 3. Who is on leave.
    on_leave = set(
        Leave.objects.for_org(shop.organization_id)
        .filter(staff_id__in=staff_ids, starts_on__lte=day, ends_on__gte=day)
        .values_list("staff_id", flat=True)
    )

    # 4. Who works this weekday, and between what times.
    working = {
        row.staff_id: row
        for row in WorkingHours.objects.for_org(shop.organization_id).filter(
            staff_id__in=staff_ids, weekday=day.weekday()
        )
    }

    # 5. What is already booked. Widened by a day on each side because a long
    #    braid started at 16:00 the previous EAT day can still be running, and
    #    the UTC instants either side of local midnight belong to a different
    #    calendar date.
    day_start = local_midnight(day)
    day_end = local_midnight(day + timedelta(days=1))
    busy = defaultdict(list)
    from scheduling.models import Appointment  # local: avoids an import cycle at app load

    appointments = (
        Appointment.objects.for_org(shop.organization_id)
        .filter(
            staff_id__in=staff_ids,
            status__in=BLOCKING_STATUSES,
            time_range__overlap=(day_start, day_end),
        )
        .order_by("time_range")
    )
    for appointment in appointments:
        # `is_active` mirrors the exclusion constraint's condition and travels
        # with the interval, so the collision resolver can tell a chair that is
        # taken from time that was already worked. See scheduling/statuses.py.
        busy[appointment.staff_id].append(
            Busy(appointment.starts_at, appointment.ends_at, appointment.is_active)
        )

    return {
        row.id: StaffDayFacts(
            staff_id=str(row.id),
            day=day,
            shop_window=shop_window,
            staff_window=(
                None
                if row.id in on_leave or row.id not in working
                else Interval(
                    to_utc(day, working[row.id].starts_at), to_utc(day, working[row.id].ends_at)
                )
            ),
            busy=tuple(busy.get(row.id, ())),
            buffer_minutes=shop.buffer_minutes,
            slot_interval_minutes=shop.slot_interval_minutes,
        )
        for row in staff_rows
    }


def gather_staff_day(staff, day):
    """One staff member. A thin wrapper so callers that genuinely need one
    person do not have to know the shape of the batch call."""
    return gather_shop_day(staff.shop, day, staff=[staff])[staff.id]


def staff_for_service(service):
    """Bookable staff who actually offer this service, with their links.

    Returns `[(staff, staff_service)]`. The link is carried along rather than
    looked up again, because `shops.durations.resolve_duration` takes the
    already-fetched row precisely so the engine can loop without a query per
    staff member.
    """
    links = (
        Staff.objects.for_org(service.organization_id)
        .filter(shop_id=service.shop_id, is_active=True, is_bookable=True)
        .prefetch_related("service_links")
    )
    out = []
    for staff_row in links:
        link = next(
            (link for link in staff_row.service_links.all() if link.service_id == service.id), None
        )
        if link is not None and link.is_offered:
            out.append((staff_row, link))
    return out
