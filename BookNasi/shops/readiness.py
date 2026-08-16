"""Why the booking page is empty, in the order the owner should fix it.

An owner finishes signup and gets a shop with no hours, no services and no
staff. Its public booking page loads, offers nothing, and says nothing about
why. Every ingredient is a separate endpoint under `shops/urls.py`, and the one
question nobody could ask was the only one that matters: *is this thing
bookable yet, and if not, what is missing?*

## Why this is derived on the server

The same reason availability is (CLAUDE.md §4) and the same reason the
dashboard's verdict is (§12): the rule for "bookable" is not a list of
non-empty tables. It is the engine's own composition rule, and the parts of it
that surprise people are exactly the parts a frontend reimplementation would
get wrong:

- **A missing `StaffService` row means the stylist does not offer the service.**
  Not "offers it with the default duration" — `loading.staff_for_service`
  requires the link to exist *and* be `is_offered`. A shop can have five staff
  and five services and produce zero slots.
- **A service with no deposit is not publicly bookable** (§5), so it counts
  towards a staff member's skills but not towards a bookable shop.
- **Rosters are per weekday, and so are opening hours.** A stylist rostered
  only on Sunday at a shop that closes Sundays is fully configured and produces
  nothing.
- **A window shorter than the service does not fit it.** Rostering 09:00–10:00
  and selling a three-hour braid is complete on every checklist and still
  yields no slot.

Restating that in TypeScript would be a second implementation of the rule §4
says must have exactly one, and it would drift the first time somebody changed
the engine. So the screen asks and renders the answer.

## What this is not

It is not a gate. Nothing here blocks a write, and a shop that fails every
check still serves its API normally — staff can book into it by hand, which is
how a shop that has not finished setup still records walk-ins on day one. This
only ever answers a question.

It is also not the adoption warning §12 ruled out of v1. That was unprompted
advice about how somebody is running their business ("no walk-ins in 9 days").
This is a factual answer about whether a feature the owner is trying to turn on
is switched on yet, asked for by the screen that turns it on.
"""

from dataclasses import asdict, dataclass

from core.mpesa import TILL as MPESA_TILL
from shops.durations import ServiceNotOffered, resolve_duration
from shops.models import CollectsVia, OpeningHours, Service, Staff, WorkingHours


@dataclass(frozen=True)
class Check:
    """One requirement, and what to do about it when it is unmet.

    `action` names the section of the setup screen that fixes it rather than a
    URL, so the API is not describing somebody's frontend routing. A third
    party embedding this (CLAUDE.md §1) gets a machine-readable key and writes
    its own link.
    """

    key: str
    done: bool
    title: str
    detail: str
    action: str


def _weekday_overlap_minutes(opening, working):
    """Minutes both the shop and the stylist are open, on one weekday.

    Wall-clock EAT on both sides, single timezone, no DST (CLAUDE.md §4), so
    this is arithmetic on minutes-past-midnight and deliberately not a datetime
    computation.
    """
    starts = max(opening.opens_at, working.starts_at)
    ends = min(opening.closes_at, working.ends_at)
    if ends <= starts:
        return 0
    return (ends.hour * 60 + ends.minute) - (starts.hour * 60 + starts.minute)


def _collection_detail(shop):
    """Why this shop cannot take a deposit, in the owner's terms.

    Three different sentences because they are three different problems and
    only one of them is the owner's to fix. A shop on the platform account when
    the deployment has none is our misconfiguration, and telling an owner to go
    and connect something would send them looking for a screen that would not
    help.
    """
    if shop.collects_via == CollectsVia.PLATFORM:
        return (
            "This shop is set to collect through BookNasi's own M-Pesa account, "
            "which is not configured on this deployment. Contact support."
        )
    if not shop.mpesa_shortcode:
        return (
            "Deposits need somewhere to land. Add your Paybill or Till and the "
            "Daraja keys from your Safaricom developer account."
        )
    return (
        "Your M-Pesa details are half-filled in, so no deposit can be taken yet. "
        "Nothing has been collected into the wrong account — a shop is never "
        "quietly switched to somebody else's till."
    )


def _collection_summary(shop):
    if shop.collects_via == CollectsVia.PLATFORM:
        return "Deposits collect into the BookNasi platform account."
    if shop.mpesa_transaction_type == MPESA_TILL:
        return f"Deposits go to till {shop.mpesa_till_number}."
    return f"Deposits go to paybill {shop.mpesa_shortcode}."


def report_for(shop):
    """The checklist for one shop, plus whether the whole chain holds.

    One pass over five small querysets. Called by a settings screen on a
    laptop, not by the booking flow on 3G, so it reads for clarity over query
    count — but it is still a fixed number of queries regardless of shop size.
    """
    org = shop.organization_id

    opening = list(OpeningHours.objects.for_org(org).filter(shop=shop))
    open_weekdays = {row.weekday for row in opening}

    services = list(Service.objects.for_org(org).filter(shop=shop, is_active=True))
    bookable_services = [s for s in services if s.is_publicly_bookable]
    # Deliberately separate from "has no services at all". A shop that entered
    # five services and set every one of them to no-deposit has done the work
    # and hit §5's rule, and telling it "add a service" would be wrong.
    deposit_free = [s for s in services if not s.is_publicly_bookable]

    staff = list(
        Staff.objects.for_org(org)
        .filter(shop=shop, is_active=True, is_bookable=True)
        .prefetch_related("service_links")
    )
    staff_ids = [row.id for row in staff]

    rosters = {}
    for row in WorkingHours.objects.for_org(org).filter(staff_id__in=staff_ids):
        rosters.setdefault(row.staff_id, []).append(row)

    # A stylist is rostered only if their working days overlap the days the
    # shop is actually open. Sunday-only staff at a Monday-to-Saturday shop are
    # configured and still produce nothing.
    rostered = [
        row
        for row in staff
        if any(shift.weekday in open_weekdays for shift in rosters.get(row.id, []))
    ]

    # Who can do what. `is_offered` and the link's existence both matter — see
    # this module's header.
    by_id = {service.id: service for service in bookable_services}

    def offers(staff_row):
        return [
            link
            for link in staff_row.service_links.all()
            if link.is_offered and link.service_id in by_id
        ]

    skilled = [row for row in rostered if offers(row)]

    # The last check: does any rostered stylist have a window long enough for
    # something they actually offer? Uses `resolve_duration` rather than
    # `service.duration_minutes` so a per-staff override is honoured — a senior
    # stylist's 30 minutes may fit where the service's default 50 does not.
    #
    # `any` over a generator rather than four nested loops with break flags:
    # it short-circuits on the first fit, which is the common case, and there
    # is no partial state to get wrong.
    hours_by_weekday = {}
    for row in opening:
        hours_by_weekday.setdefault(row.weekday, []).append(row)

    def fits_somewhere(staff_row):
        shifts = [s for s in rosters.get(staff_row.id, []) if s.weekday in open_weekdays]
        for link in offers(staff_row):
            try:
                duration = resolve_duration(service=by_id[link.service_id], staff_service=link)
            except ServiceNotOffered:  # pragma: no cover — `offers` already filtered these out
                continue
            for shift in shifts:
                for row in hours_by_weekday.get(shift.weekday, ()):
                    if _weekday_overlap_minutes(row, shift) >= duration:
                        return True
        return False

    fits = any(fits_somewhere(staff_row) for staff_row in skilled)

    checks = [
        Check(
            key="hours",
            done=bool(opening),
            title="Set your opening hours",
            detail=(
                "Clients are offered times inside these hours and no others."
                if not opening
                else f"Open {len(opening)} {'day' if len(opening) == 1 else 'days'} a week."
            ),
            action="hours",
        ),
        Check(
            key="services",
            done=bool(services),
            title="Add what you sell",
            detail=(
                "A service needs a name, how long it takes and a price."
                if not services
                else f"{len(services)} {'service' if len(services) == 1 else 'services'}."
            ),
            action="services",
        ),
        Check(
            key="deposits",
            done=bool(bookable_services),
            title="Take a deposit on at least one service",
            detail=(
                # §5's rule and the reason for it, in the place where somebody
                # is about to wonder why their service will not appear.
                "A service with no deposit can be booked by staff and recorded as a "
                "walk-in, but not booked online: the M-Pesa prompt is what verifies "
                "the client's number, so without it an unverified number holds a slot "
                "for free."
                if not bookable_services
                else f"{len(bookable_services)} of {len(services)} bookable online."
            ),
            action="services",
        ),
        Check(
            key="collects",
            done=shop.can_take_deposits,
            title="Connect your M-Pesa",
            detail=(
                _collection_detail(shop)
                if not shop.can_take_deposits
                else _collection_summary(shop)
            ),
            action="mpesa",
        ),
        Check(
            key="staff",
            done=bool(staff),
            title="Add the people who do the work",
            detail=(
                "Every booking belongs to one person's chair."
                if not staff
                else f"{len(staff)} bookable."
            ),
            action="staff",
        ),
        Check(
            key="rosters",
            done=bool(rostered),
            title="Say which days each person works",
            detail=(
                "Nobody works a day the shop is open, so there is nowhere to put a booking."
                if not rostered
                else f"{len(rostered)} rostered on days you are open."
            ),
            action="staff",
        ),
        Check(
            key="skills",
            done=bool(skilled),
            title="Say who does which service",
            detail=(
                # The one that catches people out, so it says the rule outright.
                "A stylist offers nothing until you tick it. This is also where a "
                "senior stylist's shorter time for the same service is set."
                if not skilled
                else f"{len(skilled)} with at least one service ticked."
            ),
            action="staff",
        ),
        Check(
            key="fits",
            done=fits,
            title="Leave a shift long enough for a service",
            detail=(
                "Everything is set up, but no shift is long enough for a service that "
                "person offers. Lengthen a shift or shorten a service."
                if not fits
                else "There is room in the week for at least one booking."
            ),
            action="staff",
        ),
    ]

    return {
        "shop_id": str(shop.id),
        "is_bookable": all(check.done for check in checks),
        "booking_url": f"https://{shop.slug}.booknasi.co.ke",
        "checks": [asdict(check) for check in checks],
        # Named separately from the `deposits` check because it is a different
        # sentence: the check asks whether *any* service is bookable, this says
        # which ones are not, and a shop can pass the check with four of five
        # services silently invisible online.
        "deposit_free_services": [
            {"id": str(service.id), "name": service.name} for service in deposit_free
        ],
    }
