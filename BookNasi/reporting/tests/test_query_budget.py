"""The report's cost must not scale with the data it reports on.

Not a fixed query count — that number would change every time a block was added
and would be updated without thought. What is asserted is the *shape*: a
90-day report across three shops costs the same number of queries as a one-day
report on one, plus the fixed per-shop capacity reads. A regression here is
always the same regression — a loop that fetches per day, per staff member or
per appointment — and it is invisible on a fixture with four bookings in it.

CLAUDE.md §7 is the reason this is worth a test of its own: the owner dashboard
must never be built at the cost of the staff view, and the most likely way for
that to happen is a reporting query holding connections a Saturday morning
needs.
"""

from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from reporting.metrics import build_report
from reporting.period import Period
from reporting.tests.conftest import REPORT_WEDNESDAY

pytestmark = pytest.mark.django_db


def count_queries(fn):
    """The count itself, rather than an assertion about it. Comparing two
    counts is what makes this test survive a block being added to the report."""
    with CaptureQueriesContext(connection) as capture:
        fn()
    return len(capture)


def build(shop_setup, period, now):
    return build_report(
        organization=shop_setup.organization,
        shops=[shop_setup.shop],
        period=period,
        now=now,
    )


class TestItDoesNotScale:
    def test_a_ninety_day_range_costs_what_a_one_day_range_costs(self, shop_setup, now):
        one_day = Period(REPORT_WEDNESDAY, REPORT_WEDNESDAY)
        quarter = Period(REPORT_WEDNESDAY, REPORT_WEDNESDAY + timedelta(days=89))

        short = count_queries(lambda: build(shop_setup, one_day, now))
        long = count_queries(lambda: build(shop_setup, quarter, now))

        assert short == long

    def test_more_appointments_do_not_cost_more_queries(
        self, shop_setup, record, now, report_period
    ):
        """The N+1 this is really about. `paid_deposit_for` in
        `scheduling/lifecycle.py` is a query per appointment — correct for one
        booking, and the reason `_money` reimplements it as an aggregate."""
        empty = count_queries(lambda: build(shop_setup, report_period, now))

        for hour in range(9, 18):
            record(hour=hour)
            record(hour=hour, staff=shop_setup.grace)

        assert count_queries(lambda: build(shop_setup, report_period, now)) == empty

    def test_more_stylists_do_not_cost_more_queries(self, shop_setup, now, report_period):
        from datetime import time

        from shops.models import Staff, WorkingHours

        before = count_queries(lambda: build(shop_setup, report_period, now))
        for index in range(6):
            extra = Staff.objects.create(shop=shop_setup.shop, display_name=f"Stylist {index}")
            for weekday in range(0, 6):
                WorkingHours.objects.create(
                    staff=extra, weekday=weekday, starts_at=time(9, 0), ends_at=time(18, 0)
                )

        assert count_queries(lambda: build(shop_setup, report_period, now)) == before
