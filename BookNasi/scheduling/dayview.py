"""Today, for the person standing at the chair.

CLAUDE.md §7: "Staff view must be faster than the notebook for the two things
they do all day: see today's list, add a walk-in. That's the adoption bar." So
this module has one job and does it in one query.

## What is deliberately not computed here

**The bands.** The design draws today as three bands — Now, Next, and earlier
work sunk to grey — and every one of them is a function of the current second.
Computing them server-side would bake a timestamp into the response that is
already wrong by the time it paints, and would make the "Now" heading jump only
when the page was refetched. The API sends statuses and instants; the client
already runs a clock for the in-progress elapsed counter and bands off that.

**Availability.** A day view is a list of what is booked, not a derivation of
what is free. Keeping them apart is what holds this to two queries no matter how
many appointments there are — the five-query shop-day loader is for the walk-in
sheet, which genuinely needs to know who is free.

## Deposits

`deposit_total_kes` is the sum of what the day's bookings *carry* as a deposit,
taken from the snapshots. It is not "money received": there is no payment record
until slice 6, and calling it money in the till before the M-Pesa callback
exists would put a number on the stat tile that nobody can reconcile. The label
on the tile says `Deposits`, not `Deposits in`, until slice 6 can tell the
difference.
"""

from dataclasses import dataclass
from datetime import timedelta

from scheduling.availability import local_midnight
from scheduling.models import Appointment
from scheduling.statuses import AppointmentStatus, BookingSource


@dataclass(frozen=True)
class DayTotals:
    """The three stat tiles. Counted in Python off rows already fetched, so
    they cost nothing — three aggregate queries for three small numbers would
    triple the cost of the screen staff open most often."""

    appointments: int
    walk_ins: int
    deposit_total_kes: int


def appointments_for_day(shop, day, *, staff=None):
    """Everything on the day view for `shop` on the EAT date `day`, in one query.

    Cancelled bookings are absent: they are not work, and the design's three
    bands have nowhere to put them. Everything else appears, including no-shows
    (the design draws them struck through) and unpaid online holds (the design
    draws the countdown).

    The window is widened by a day either side for the same reason the
    availability loader widens it — a long braid started before local midnight
    is still running at 09:00 — and then filtered back, so an appointment that
    began yesterday and is still in the chair shows up on today's list.
    """
    window = (local_midnight(day) - timedelta(days=1), local_midnight(day + timedelta(days=1)))
    query = (
        Appointment.objects.for_org(shop.organization_id)
        .filter(shop=shop, time_range__overlap=window)
        .exclude(status=AppointmentStatus.CANCELLED)
        # One query, not one per row. The detail card needs the service name and
        # the client's name; without this the day view is N+1 at exactly the
        # moment a busy Saturday makes it visible.
        .select_related("service", "client", "staff")
        .order_by("time_range")
    )
    if staff is not None:
        query = query.filter(staff__in=staff)
    return list(query)


def totals_for(appointments):
    return DayTotals(
        appointments=len(appointments),
        walk_ins=sum(1 for a in appointments if a.source == BookingSource.WALK_IN),
        deposit_total_kes=sum(a.deposit_snapshot for a in appointments),
    )


def top_services_for(staff, *, limit=5):
    """This staff member's five most-recorded services, commonest first.

    Tap 1 of the three-tap walk-in. Ranked by what this person has actually
    done rather than by what the shop sells, because the barber who does forty
    fades a week should not scroll past the bridal package to reach one.

    A new staff member has no history, so the fallback is the shop's own service
    order — an empty first tap would make the flow four taps on somebody's first
    day, which is the worst possible day for it.
    """
    from django.db.models import Count

    from shops.models import Service, StaffService

    offered = (
        StaffService.objects.for_org(staff.organization_id)
        .filter(staff=staff, is_offered=True, service__is_active=True)
        .values_list("service_id", flat=True)
    )
    ranked = (
        Appointment.objects.for_org(staff.organization_id)
        .filter(staff=staff, service_id__in=list(offered))
        .exclude(status=AppointmentStatus.CANCELLED)
        .values("service_id")
        .annotate(times=Count("id"))
        .order_by("-times")[:limit]
    )
    order = [row["service_id"] for row in ranked]

    services = {
        service.id: service
        for service in Service.objects.for_org(staff.organization_id).filter(id__in=list(offered))
    }
    ranked_services = [services[sid] for sid in order if sid in services]
    if len(ranked_services) < limit:
        seen = set(order)
        for service in services.values():
            if service.id in seen:
                continue
            ranked_services.append(service)
            if len(ranked_services) == limit:
                break
    return ranked_services[:limit]
