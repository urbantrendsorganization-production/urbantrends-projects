"""The dashboard's response shape.

Read-only throughout — there is no writable serializer in this app and nothing
here has a `.save()`. A report is a view of rows other slices own.

## Rates go out as fractions, or as null

Every rate (`no_show_rate`, `utilisation`, `load`, `stk_completion`,
`repeat_rate`) is a float between 0 and 1, or **null** when its denominator is
zero. Null is not the same as zero and the difference matters on every one of
them: a stylist with no rostered hours is absent, not idle; a shop with no
finished bookings has an unknown no-show rate, not a perfect one. Rounding and
the `%` sign are the client's job, because the design prints one decimal place
in some places and none in others and that is a typographic decision.

## Counts travel next to every rate

`counted_out_of`, `capacity_minutes`, `pushes` — the denominators are all
returned. An owner who wants to check a number should be able to, and a third
party integrating this API (CLAUDE.md §1) needs the raw figures rather than our
arithmetic.
"""

from rest_framework import serializers


class OutcomesSerializer(serializers.Serializer):
    completed = serializers.IntegerField(read_only=True)
    no_show = serializers.IntegerField(read_only=True)
    cancelled = serializers.IntegerField(read_only=True)
    #: Bookings whose time has passed while still confirmed or in progress —
    #: nobody pressed Finish. Published rather than hidden: they are missing
    #: from revenue and from the no-show rate, so a large number here means the
    #: rest of this response understates the shop.
    unresolved = serializers.IntegerField(read_only=True)
    upcoming = serializers.IntegerField(read_only=True)
    total = serializers.IntegerField(read_only=True)


class NoShowSerializer(serializers.Serializer):
    rate = serializers.FloatField(read_only=True, allow_null=True)
    counted_out_of = serializers.IntegerField(read_only=True)


class MoneySerializer(serializers.Serializer):
    collected_kes = serializers.IntegerField(read_only=True)
    forfeited_kes = serializers.IntegerField(read_only=True)
    credit_issued_kes = serializers.IntegerField(read_only=True)
    refund_due_kes = serializers.IntegerField(read_only=True)
    pushes = serializers.IntegerField(read_only=True)
    pushes_succeeded = serializers.IntegerField(read_only=True)
    stk_completion = serializers.FloatField(read_only=True, allow_null=True)


class ClientsSerializer(serializers.Serializer):
    seen = serializers.IntegerField(read_only=True)
    repeat = serializers.IntegerField(read_only=True)
    repeat_rate = serializers.FloatField(read_only=True, allow_null=True)
    #: How much of the period this rate actually describes. Walk-ins carry no
    #: client record, so on a walk-in-heavy shop this is small and the rate
    #: above must be read as a statement about the booked half of the trade.
    attributed = serializers.IntegerField(read_only=True)
    completed = serializers.IntegerField(read_only=True)
    attributed_share = serializers.FloatField(read_only=True, allow_null=True)


class StaffRowSerializer(serializers.Serializer):
    """Field order is the design's column order, and it is load-bearing:
    "Keep deposits and no-shows adjacent" — the barber with no deposits is the
    one with seven no-shows, and that is the whole argument the table makes."""

    staff_id = serializers.CharField(read_only=True)
    display_name = serializers.CharField(read_only=True)
    shop_id = serializers.CharField(read_only=True)
    shop_name = serializers.CharField(read_only=True)
    services = serializers.IntegerField(read_only=True)
    revenue_kes = serializers.IntegerField(read_only=True)
    deposits_kes = serializers.IntegerField(read_only=True)
    no_shows = serializers.IntegerField(read_only=True)
    unresolved = serializers.IntegerField(read_only=True)
    shortened = serializers.IntegerField(read_only=True)
    booked_minutes = serializers.IntegerField(read_only=True)
    capacity_minutes = serializers.IntegerField(read_only=True)
    utilisation = serializers.FloatField(read_only=True, allow_null=True)


class ShopTodaySerializer(serializers.Serializer):
    shop_id = serializers.CharField(read_only=True)
    shop_name = serializers.CharField(read_only=True)
    appointments = serializers.IntegerField(read_only=True)
    walk_ins = serializers.IntegerField(read_only=True)
    booked_minutes = serializers.IntegerField(read_only=True)
    capacity_minutes = serializers.IntegerField(read_only=True)
    load = serializers.FloatField(read_only=True, allow_null=True)


class PeriodSerializer(serializers.Serializer):
    """Both ranges, always. The comparison is against the shop's own preceding
    period and never against a pre-BookNasi baseline we never observed — see
    `reporting/period.py` — so the dates it is being compared to are printed."""

    starts_on = serializers.DateField(read_only=True)
    ends_on = serializers.DateField(read_only=True)
    days = serializers.IntegerField(read_only=True)


def report_payload(report, *, organization, shops, shop_filter):
    """The whole response, assembled once.

    A function rather than a `ReportSerializer` with nine nested fields: the
    two comparison blocks (`no_show` now and previously) are the same shape
    drawn from two different objects, and a nested serializer would need a
    method field per block to say so.
    """
    return {
        "period": {
            **PeriodSerializer(report.period).data,
            "previous": PeriodSerializer(report.period.previous).data,
        },
        "scope": {
            "organization_id": str(organization.id),
            "organization_name": organization.name,
            "shop_id": str(shop_filter.id) if shop_filter else None,
            "shops": [{"id": str(shop.id), "name": shop.name} for shop in shops],
        },
        "verdict": report.verdict,
        "outcomes": OutcomesSerializer(report.outcomes).data,
        "no_show": {
            "rate": report.outcomes.no_show_rate,
            "counted_out_of": report.outcomes.terminal,
            "previous_rate": report.previous.no_show_rate,
            "previous_counted_out_of": report.previous.terminal,
        },
        # Billed, not banked. `revenue_kes` is `price_snapshot` on completed
        # work; `money.collected_kes` is the part that arrived by M-Pesa. They
        # are different questions and must never be summed — see
        # `reporting/metrics.py`.
        "revenue_kes": report.revenue_kes,
        "money": MoneySerializer(report.money).data,
        "clients": ClientsSerializer(report.clients).data,
        "staff": StaffRowSerializer(report.staff, many=True).data,
        "today": ShopTodaySerializer(report.today, many=True).data,
    }
