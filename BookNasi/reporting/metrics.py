"""The owner dashboard's numbers, and the definitions behind each one.

CLAUDE.md §7: the owner dashboard is what renews the subscription. That only
holds if an owner who disagrees with a number can find out how it was reached,
so every counting rule in this module is stated rather than implied. A figure
nobody can reconstruct is a figure that gets argued with once and then ignored.

## The rules, in one place

**A booking belongs to the period its start falls in**, in EAT. Not the day it
was created: an owner asking how last week went means the work, not the
paperwork. A braid started at 16:00 that runs past midnight belongs to the day
it began.

**Revenue is billed, not banked.** `price_snapshot` on completed appointments —
what the shop charged. We observe the deposit and nothing else: the balance is
collected at the chair and CLAUDE.md §12 puts cash handling out of v1 entirely.
So `revenue_kes` is the shop's takings *if everyone paid what they owed*, and
`deposits_kes` beside it is the part we can actually prove. They are separate
columns for that reason and must never be added together.

**Deposit money is attributed to the booking, not to the day it arrived.** A
deposit paid today for a braid in six weeks counts in six weeks' time, with the
work. Keying it on `paid_at` instead would produce a report whose money column
described a different set of bookings than its appointment column, which is
exactly the kind of near-miss that makes a dashboard untrustworthy. Three
figures are deliberately keyed the other way — credit issued, refunds fallen
due, prompts sent — because they are questions about the shop's month rather
than about a set of bookings. `Money` says which is which.

**Only completed work earns.** A no-show earns nothing and forfeits its
deposit; a cancellation earns nothing and either refunds or becomes credit (§12);
a booking still sitting `confirmed` after its time has passed earns nothing
*yet* and is counted separately as `unresolved`. That last number is load-bearing
— see below.

**The no-show rate is `no_show / (completed + no_show)`.** Cancellations are
excluded from the denominator on purpose. A client who cancels told the shop,
which is the behaviour §12's credit rule is designed to encourage, and folding
them into the same rate would make a shop look worse for the thing it wants more
of. The raw counts are returned alongside so anyone can compute it differently.

**`unresolved` is published, not hidden.** Every appointment whose time has
passed while still `confirmed` or `in_progress` is one nobody pressed Finish on.
Those bookings are missing from revenue, from utilisation and from the no-show
rate. A shop where a third of last week is unresolved is being shown numbers
that are wrong by a third, and the honest response is to say so on the screen
rather than to quietly report a smaller month. It is also the only adoption
signal here — and deliberately not the "Thika Rd has recorded no walk-ins in 9
days" warning, which §12 rules out of v1.

**Repeat clients are counted over identified clients only.** A walk-in usually
has no client row — asking for a name is friction at the chair, and §4 forbids
adding it — so the rate is computed over the bookings that carry one, and
`attributed_share` reports how big that subset was. Without it the rate is a
number about a minority of a shop's trade presented as a number about the shop.

## What is deliberately not here

`no-show before vs after deposits`, for the reason in `period.py`: there is no
"before". The comparison drawn is against the shop's own preceding period.

Adoption warnings, per §12. `unresolved` above is a completeness caveat on
numbers being displayed, not a nudge about behaviour.
"""

from dataclasses import dataclass, field

from django.db.models import Count, Exists, OuterRef, Q, Sum

from payments.credit import Credit
from payments.models import Payment
from payments.states import PaymentState
from reporting import capacity
from reporting.period import Period
from scheduling.models import Appointment
from scheduling.statuses import ACTIVE_STATUSES, AppointmentStatus, BookingSource

#: Below this many terminal outcomes a rate is noise, and a headline drawn from
#: it is worse than no headline. Three weeks of a quiet barber, roughly.
MIN_OUTCOMES_FOR_A_VERDICT = 20

#: How much worse the no-show rate has to get before the dashboard says so, in
#: percentage points. Anything smaller is one Saturday.
NO_SHOW_DRIFT_POINTS = 2.0


class Verdict:
    """The conclusion the headline states. Worded on the client — the sentence
    is copy and §10 lets a host relabel copy — but *chosen* here, where it can
    be tested against numbers."""

    TOO_EARLY = "too_early"
    NO_DEPOSITS = "no_deposits"
    DEPOSITS_WORKING = "deposits_working"
    NO_SHOWS_RISING = "no_shows_rising"
    STEADY = "steady"


@dataclass(frozen=True)
class Outcomes:
    """What happened to the period's bookings. The four are exhaustive with
    `upcoming`, so a reader can check they add up to `total`."""

    completed: int = 0
    no_show: int = 0
    cancelled: int = 0
    unresolved: int = 0
    upcoming: int = 0

    @property
    def total(self):
        return self.completed + self.no_show + self.cancelled + self.unresolved + self.upcoming

    @property
    def terminal(self):
        """The no-show rate's denominator. See the module docstring."""
        return self.completed + self.no_show

    @property
    def no_show_rate(self):
        """A fraction, or None when there is nothing to divide by.

        None rather than 0.0, deliberately: a shop with no finished bookings has
        an *unknown* no-show rate, and printing 0 % would be the most flattering
        possible lie to tell a new customer.
        """
        return None if not self.terminal else self.no_show / self.terminal


@dataclass(frozen=True)
class StaffRow:
    """One line of the revenue-per-staff table.

    The design's column order is `staff · services · revenue · deposits ·
    no-shows · utilisation`, and it says to keep deposits and no-shows adjacent
    because that adjacency *is* the argument: the stylist taking no deposits is
    the one with seven no-shows. The serializer preserves it.
    """

    staff_id: str
    display_name: str
    shop_id: str
    shop_name: str
    services: int = 0
    revenue_kes: int = 0
    deposits_kes: int = 0
    no_shows: int = 0
    unresolved: int = 0
    #: Bookings recorded shorter than the service's resolved duration, at full
    #: price — `Appointment.was_shortened`. Surfaced because it distorts
    #: utilisation downward and revenue-per-hour upward, and the comment on that
    #: column asks for the distortion to be shown next to the number rather than
    #: absorbed into it.
    shortened: int = 0
    booked_minutes: int = 0
    capacity_minutes: int = 0

    @property
    def utilisation(self):
        """Booked minutes over available minutes. None when nobody rostered
        them — a stylist with no working hours is not 0 % busy, they are absent,
        and a zero bar next to a colleague's 60 % says the wrong thing."""
        if not self.capacity_minutes:
            return None
        return self.booked_minutes / self.capacity_minutes


@dataclass(frozen=True)
class ShopToday:
    """One load meter. Today only, and deliberately not cached with the rest —
    see `reporting/cache.py`."""

    shop_id: str
    shop_name: str
    appointments: int = 0
    walk_ins: int = 0
    booked_minutes: int = 0
    capacity_minutes: int = 0

    @property
    def load(self):
        if not self.capacity_minutes:
            return None
        return self.booked_minutes / self.capacity_minutes


@dataclass(frozen=True)
class Money:
    """Every shilling on the screen, and **two different keys**.

    The first two are keyed on the *booking*: deposits attached to appointments
    whose time falls in the period, so they reconcile against the appointment
    counts sitting next to them.

    The last three are keyed on the *event* — when the credit was issued, when
    the refund fell due, when the prompt was sent. Those answer questions about
    the shop's month rather than about a set of bookings ("how much credit did
    I hand out", "are M-Pesa prompts getting through"), and forcing them onto
    the booking's date would make them answer neither. In practice the two keys
    almost coincide, because a credit is issued by a cancellation inside the
    refund window and a push happens at booking time — which is exactly why the
    difference has to be written down rather than noticed later.
    """

    #: Deposits that actually arrived by M-Pesa, for this period's bookings.
    collected_kes: int = 0
    #: The product's whole argument, in one number: deposits the shop keeps
    #: because the client did not turn up. CLAUDE.md §1 — "money that used to be
    #: zero".
    forfeited_kes: int = 0
    #: Late cancellations turned into shop credit (§12), issued in this period.
    #: Money the shop is holding against future work, not earnings.
    credit_issued_kes: int = 0
    #: Refunds that fell due in this period and are not yet marked sent. We are
    #: not the merchant — the money went to the shop's own paybill — so this is
    #: a liability we can only report.
    refund_due_kes: int = 0
    #: Prompts sent in this period and the share that ended `succeeded`. The
    #: health of the payment path, not of the bookings.
    pushes: int = 0
    pushes_succeeded: int = 0

    @property
    def stk_completion(self):
        return None if not self.pushes else self.pushes_succeeded / self.pushes


@dataclass(frozen=True)
class Clients:
    seen: int = 0
    repeat: int = 0
    #: Completed bookings in the period that carried a client record, over all
    #: completed bookings. The honesty column — see the module docstring.
    attributed: int = 0
    completed: int = 0

    @property
    def repeat_rate(self):
        return None if not self.seen else self.repeat / self.seen

    @property
    def attributed_share(self):
        return None if not self.completed else self.attributed / self.completed


@dataclass(frozen=True)
class Report:
    period: Period
    outcomes: Outcomes
    previous: Outcomes
    money: Money
    clients: Clients
    staff: list = field(default_factory=list)
    today: list = field(default_factory=list)

    @property
    def revenue_kes(self):
        return sum(row.revenue_kes for row in self.staff)

    @property
    def verdict(self):
        return verdict_for(self)


def verdict_for(report):
    """The headline's conclusion, in the order the checks have to happen.

    "You are not taking deposits" comes before any praise, because a shop with
    every service set to no-deposit is the shop that churns, and the dashboard
    saying something encouraging to it is the single most expensive sentence
    this product could print.
    """
    outcomes = report.outcomes
    if outcomes.terminal < MIN_OUTCOMES_FOR_A_VERDICT:
        return Verdict.TOO_EARLY
    if report.money.collected_kes < 1:
        return Verdict.NO_DEPOSITS

    rate = outcomes.no_show_rate
    previous = report.previous.no_show_rate
    if previous is None or report.previous.terminal < MIN_OUTCOMES_FOR_A_VERDICT:
        # Nothing to compare against. Forfeits alone are still a real result —
        # money that would have been zero — but they are not a trend.
        return Verdict.DEPOSITS_WORKING if report.money.forfeited_kes else Verdict.STEADY

    drift = (rate - previous) * 100
    if drift > NO_SHOW_DRIFT_POINTS:
        return Verdict.NO_SHOWS_RISING
    if rate < previous:
        return Verdict.DEPOSITS_WORKING
    return Verdict.STEADY


# ------------------------------------------------------------ the queries


def build_report(*, organization, shops, period, now, include_today=True, today_shops=None):
    """Every number on the dashboard, for one organization and a set of shops.

    Query count is a fixed shape plus four per shop for capacity — not one per
    day and not one per staff member. See `reporting/capacity.py` on why that
    matters for a 90-day range across a chain.

    `include_today=False` is what `reporting/cache.py` stores: the load meters
    are recomputed on every request and must never be served from a cache entry.

    `today_shops` is the full branch list when `shops` has been narrowed by a
    shop filter. The load meters are the switcher, and a switcher that hides
    every branch but the selected one cannot be switched with.
    """
    shop_ids = [shop.id for shop in shops]
    lo, hi = period.utc_bounds

    staff_rows = _staff_rows(organization, shop_ids)
    per_staff = _per_staff(organization, shop_ids, period, now, staff_rows, shops)

    return Report(
        period=period,
        outcomes=_outcomes(organization, shop_ids, period, now),
        previous=_outcomes(organization, shop_ids, period.previous, now),
        money=_money(organization, shop_ids, period, lo, hi),
        clients=_clients(organization, shop_ids, lo, hi),
        staff=per_staff,
        today=today_for(organization, today_shops or shops, now) if include_today else [],
    )


def _staff_rows(organization, shop_ids):
    from shops.models import Staff

    return list(
        Staff.objects.for_org(organization)
        .filter(shop_id__in=shop_ids, is_active=True)
        .select_related("shop")
        .order_by("display_name")
    )


def _period_appointments(organization, shop_ids, period):
    """Bookings whose **start** falls inside the period.

    `time_range__startswith` rather than `__overlap`: overlap would pull in a
    braid that began the evening before the range and count its whole price in
    a period it mostly did not happen in. A booking belongs to one day, and that
    day is the one it started.
    """
    lo, hi = period.utc_bounds
    return Appointment.objects.for_org(organization).filter(
        shop_id__in=shop_ids, time_range__startswith__gte=lo, time_range__startswith__lt=hi
    )


def _outcome_filters(now):
    """The status buckets, as one dict so `_outcomes` and `_per_staff` cannot
    drift apart — the same mistake `scheduling/statuses.py` is written to
    prevent one layer down."""
    past = Q(time_range__startswith__lt=now)
    return {
        "completed": Q(status=AppointmentStatus.COMPLETED),
        "no_show": Q(status=AppointmentStatus.NO_SHOW),
        "cancelled": Q(status=AppointmentStatus.CANCELLED),
        "unresolved": Q(status__in=ACTIVE_STATUSES) & past,
        "upcoming": Q(status__in=ACTIVE_STATUSES) & ~past,
    }


def _outcomes(organization, shop_ids, period, now):
    counts = _period_appointments(organization, shop_ids, period).aggregate(
        **{name: Count("id", filter=condition) for name, condition in _outcome_filters(now).items()}
    )
    return Outcomes(**counts)


def _money(organization, shop_ids, period, lo, hi):
    """Every shilling figure. Four aggregates, no per-appointment queries.

    `paid_deposit_for` in `scheduling/lifecycle.py` is the single-appointment
    version of the first two, and reads credit redemptions as well as payments.
    This does not, on purpose: redeemed credit is money that arrived in an
    *earlier* period and was already counted then. Adding it here would report
    the same shilling twice and would do so in the shop's favour.
    """
    in_period = Q(
        appointment__shop_id__in=shop_ids,
        appointment__time_range__startswith__gte=lo,
        appointment__time_range__startswith__lt=hi,
    )
    deposits = (
        Payment.objects.for_org(organization)
        .filter(in_period, state=PaymentState.SUCCEEDED)
        # `Exists`, not a join to `appointment__credits_issued`. A filtered
        # aggregate's join applies to the whole queryset, so a booking with two
        # credits against it would have contributed its deposit to `collected`
        # twice — a double-count that would only appear on the rows that
        # already had something unusual about them.
        .annotate(
            booking_has_credit=Exists(
                Credit.objects.for_org(organization).filter(
                    source_appointment_id=OuterRef("appointment_id")
                )
            )
        )
    )
    money = deposits.aggregate(
        collected=Sum("amount", default=0),
        # The forfeit rule, in bulk, matching `lifecycle.is_forfeited`: the
        # client did not turn up, real money arrived, and no credit was issued
        # against that booking. The credit exclusion is what stops a late
        # cancellation being reported as a forfeit — see that function.
        forfeited=Sum(
            "amount",
            filter=Q(appointment__status=AppointmentStatus.NO_SHOW, booking_has_credit=False),
            default=0,
        ),
    )

    credits = Credit.objects.for_org(organization).filter(
        shop_id__in=shop_ids, created_at__gte=lo, created_at__lt=hi
    )
    refunds = Payment.objects.for_org(organization).filter(
        appointment__shop_id__in=shop_ids,
        refund_due_at__gte=lo,
        refund_due_at__lt=hi,
        queue_resolved_at__isnull=True,
    )
    pushes = Payment.objects.for_org(organization).filter(
        appointment__shop_id__in=shop_ids, pushed_at__gte=lo, pushed_at__lt=hi
    )

    return Money(
        collected_kes=money["collected"] or 0,
        forfeited_kes=money["forfeited"] or 0,
        credit_issued_kes=credits.aggregate(total=Sum("amount_kes", default=0))["total"] or 0,
        refund_due_kes=refunds.aggregate(total=Sum("amount", default=0))["total"] or 0,
        **pushes.aggregate(
            pushes=Count("id"),
            pushes_succeeded=Count("id", filter=Q(state=PaymentState.SUCCEEDED)),
        ),
    )


def _clients(organization, shop_ids, lo, hi):
    """Repeat clients, over the bookings that identify one.

    "Repeat" means a completed booking at this organization that started
    *before* this client's first one in the period — org-wide, not shop-wide,
    because CLAUDE.md §3 is explicit that a regular visiting two branches is one
    person with one history. Two queries regardless of how many clients there
    are.
    """
    completed = Appointment.objects.for_org(organization).filter(
        shop_id__in=shop_ids,
        status=AppointmentStatus.COMPLETED,
        time_range__startswith__gte=lo,
        time_range__startswith__lt=hi,
    )
    totals = completed.aggregate(
        total=Count("id"), attributed=Count("id", filter=Q(client__isnull=False))
    )
    client_ids = set(completed.exclude(client__isnull=True).values_list("client_id", flat=True))
    if not client_ids:
        return Clients(completed=totals["total"], attributed=totals["attributed"])

    returning = set(
        Appointment.objects.for_org(organization)
        .filter(
            client_id__in=client_ids,
            status=AppointmentStatus.COMPLETED,
            time_range__startswith__lt=lo,
        )
        .values_list("client_id", flat=True)
    )
    return Clients(
        seen=len(client_ids),
        repeat=len(returning),
        attributed=totals["attributed"],
        completed=totals["total"],
    )


def _per_staff(organization, shop_ids, period, now, staff_rows, shops):
    """The table. One aggregate over appointments, one capacity pass per shop.

    A stylist with no bookings at all still gets a row: an empty line in the
    table is information, and dropping them would hide exactly the person an
    owner most needs to see.
    """
    filters = _outcome_filters(now)
    aggregated = {
        row["staff_id"]: row
        for row in _period_appointments(organization, shop_ids, period)
        .values("staff_id")
        .annotate(
            services=Count("id", filter=filters["completed"]),
            revenue=Sum("price_snapshot", filter=filters["completed"], default=0),
            no_shows=Count("id", filter=filters["no_show"]),
            unresolved=Count("id", filter=filters["unresolved"]),
            shortened=Count("id", filter=Q(was_shortened=True) & ~filters["cancelled"]),
            # Time the chair was committed. A no-show occupied it as surely as a
            # completed booking did — nobody else could be given that hour — so
            # both count, which is what makes a stylist with high utilisation and
            # low revenue legible as a no-show problem rather than a lazy one.
            # Cancellations do not: the slot went back on sale.
            booked=Sum(
                "duration_snapshot",
                filter=filters["completed"] | filters["no_show"],
                default=0,
            ),
        )
    }
    deposits = dict(
        Payment.objects.for_org(organization)
        .filter(
            appointment__shop_id__in=shop_ids,
            appointment__time_range__startswith__gte=period.utc_bounds[0],
            appointment__time_range__startswith__lt=period.utc_bounds[1],
            state=PaymentState.SUCCEEDED,
        )
        .values_list("appointment__staff_id")
        .annotate(total=Sum("amount"))
    )

    minutes = {}
    by_shop = {shop.id: [row for row in staff_rows if row.shop_id == shop.id] for shop in shops}
    for shop in shops:
        minutes.update(capacity.minutes_for(shop, by_shop[shop.id], period))

    out = []
    for row in staff_rows:
        stats = aggregated.get(row.id, {})
        out.append(
            StaffRow(
                staff_id=str(row.id),
                display_name=row.display_name,
                shop_id=str(row.shop_id),
                shop_name=row.shop.name,
                services=stats.get("services", 0),
                revenue_kes=stats.get("revenue") or 0,
                deposits_kes=deposits.get(row.id, 0),
                no_shows=stats.get("no_shows", 0),
                unresolved=stats.get("unresolved", 0),
                shortened=stats.get("shortened", 0),
                booked_minutes=stats.get("booked") or 0,
                capacity_minutes=minutes.get(row.id, 0),
            )
        )
    # Ordered by revenue, as the design has it. Ties fall back to the name so
    # the table does not reshuffle between two refreshes that show the same
    # numbers.
    out.sort(key=lambda r: (-r.revenue_kes, r.display_name))
    return out


def today_for(organization, shops, now):
    """The load meters. Always today, whatever range the report covers.

    The date picker moves the rest of the dashboard; this row answers "what is
    happening in my shops right now", which is a different question and the one
    an owner opens the page for on a Saturday morning.
    """
    from reporting.period import Period, today_eat

    day = today_eat(now)
    one_day = Period(day, day)
    lo, hi = one_day.utc_bounds

    shop_ids = [shop.id for shop in shops]
    counts = {
        row["shop_id"]: row
        for row in Appointment.objects.for_org(organization)
        .filter(
            shop_id__in=shop_ids,
            time_range__startswith__gte=lo,
            time_range__startswith__lt=hi,
        )
        .exclude(status=AppointmentStatus.CANCELLED)
        .values("shop_id")
        .annotate(
            appointments=Count("id"),
            walk_ins=Count("id", filter=Q(source=BookingSource.WALK_IN)),
            booked=Sum("duration_snapshot", default=0),
        )
    }

    out = []
    for shop in shops:
        staff_rows = list(shop.staff.filter(is_active=True))
        minutes = capacity.minutes_for(shop, staff_rows, one_day)
        stats = counts.get(shop.id, {})
        out.append(
            ShopToday(
                shop_id=str(shop.id),
                shop_name=shop.name,
                appointments=stats.get("appointments", 0),
                walk_ins=stats.get("walk_ins", 0),
                booked_minutes=stats.get("booked") or 0,
                capacity_minutes=sum(minutes.values()),
            )
        )
    return out


__all__ = [
    "Clients",
    "Money",
    "Outcomes",
    "Report",
    "ShopToday",
    "StaffRow",
    "Verdict",
    "build_report",
    "today_for",
    "verdict_for",
]
