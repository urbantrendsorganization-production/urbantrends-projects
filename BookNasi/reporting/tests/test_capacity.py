"""Capacity has to be the availability engine's answer, not a second opinion.

`reporting/capacity.py` reads the same rows as `loading.gather_shop_day` but
fetches them in bulk, and it constructs a `StaffDayFacts` so the intersection
rule stays in one place. That is a real risk of divergence, and this file is
pointed straight at it: for every awkward shop-day, the window this module
produces must be *identical* to the engine's.

If those two ever disagree, the utilisation column is quietly wrong — in
whichever direction nobody checks, because a percentage on a bar looks equally
plausible at 48 % and 61 %.
"""

from datetime import date, time, timedelta

import pytest

from reporting import capacity
from reporting.period import Period
from scheduling.loading import gather_shop_day
from shops.models import Leave, OpeningHours, ShopClosure, WorkingHours

pytestmark = pytest.mark.django_db

WEDNESDAY = date(2026, 6, 10)
SUNDAY = date(2026, 6, 14)


def one_day(day):
    return Period(day, day)


def engine_window(shop_setup, staff, day):
    return gather_shop_day(shop_setup.shop, day, staff=[staff])[staff.id].window


def reporting_window(shop_setup, staff, day):
    return capacity.windows_for(shop_setup.shop, [staff], one_day(day))[staff.id][day]


class TestItAgreesWithTheEngine:
    def test_on_an_ordinary_trading_day(self, shop_setup):
        assert reporting_window(shop_setup, shop_setup.wanjiku, WEDNESDAY) == engine_window(
            shop_setup, shop_setup.wanjiku, WEDNESDAY
        )

    def test_when_the_shop_is_shut_that_weekday(self, shop_setup):
        """The fixture opens Monday-Saturday."""
        assert reporting_window(shop_setup, shop_setup.wanjiku, SUNDAY) is None
        assert engine_window(shop_setup, shop_setup.wanjiku, SUNDAY) is None

    def test_when_a_dated_closure_beats_the_weekly_pattern(self, shop_setup):
        """A public holiday. The closure wins over opening hours and over a
        stylist who is rostered — the ordering the engine documents."""
        ShopClosure.objects.create(
            shop=shop_setup.shop, starts_on=WEDNESDAY, ends_on=WEDNESDAY, reason="Madaraka Day"
        )

        assert reporting_window(shop_setup, shop_setup.wanjiku, WEDNESDAY) is None
        assert engine_window(shop_setup, shop_setup.wanjiku, WEDNESDAY) is None

    def test_when_the_stylist_is_on_leave(self, shop_setup):
        Leave.objects.create(
            staff=shop_setup.wanjiku, starts_on=WEDNESDAY, ends_on=WEDNESDAY + timedelta(days=3)
        )

        assert reporting_window(shop_setup, shop_setup.wanjiku, WEDNESDAY) is None
        assert engine_window(shop_setup, shop_setup.wanjiku, WEDNESDAY) is None

    def test_when_the_stylist_is_rostered_outside_opening_hours(self, shop_setup):
        """An owner can save this and it is not an error. It is also not
        availability, and both modules have to reach that conclusion."""
        WorkingHours.objects.for_org(shop_setup.organization).filter(
            staff=shop_setup.grace, weekday=WEDNESDAY.weekday()
        ).update(starts_at=time(21, 0), ends_at=time(23, 0))

        assert reporting_window(shop_setup, shop_setup.grace, WEDNESDAY) is None
        assert engine_window(shop_setup, shop_setup.grace, WEDNESDAY) is None

    def test_when_working_hours_extend_past_closing(self, shop_setup):
        """The intersection, not the roster. A stylist who starts at 07:00 in a
        shop that opens at 08:00 is doing setup."""
        OpeningHours.objects.for_org(shop_setup.organization).filter(
            shop=shop_setup.shop, weekday=WEDNESDAY.weekday()
        ).update(opens_at=time(10, 0), closes_at=time(16, 0))

        mine = reporting_window(shop_setup, shop_setup.wanjiku, WEDNESDAY)

        assert mine == engine_window(shop_setup, shop_setup.wanjiku, WEDNESDAY)
        assert (mine.ends_at - mine.starts_at) == timedelta(hours=6)


class TestMinutes:
    def test_an_ordinary_week_is_the_rostered_hours(self, shop_setup):
        """09:00-18:00 six days a week, intersected with 08:00-20:00 opening:
        nine hours a day, Monday to Saturday, and nothing on Sunday."""
        week = Period(WEDNESDAY - timedelta(days=2), WEDNESDAY + timedelta(days=4))
        minutes = capacity.minutes_for(shop_setup.shop, [shop_setup.wanjiku], week)

        assert minutes[shop_setup.wanjiku.id] == 6 * 9 * 60

    def test_leave_removes_whole_days(self, shop_setup):
        week = Period(WEDNESDAY - timedelta(days=2), WEDNESDAY + timedelta(days=4))
        Leave.objects.create(
            staff=shop_setup.wanjiku, starts_on=WEDNESDAY, ends_on=WEDNESDAY + timedelta(days=1)
        )
        minutes = capacity.minutes_for(shop_setup.shop, [shop_setup.wanjiku], week)

        assert minutes[shop_setup.wanjiku.id] == 4 * 9 * 60

    def test_a_stylist_with_no_working_hours_has_no_capacity(self, shop_setup):
        """Not zero-because-idle. The report turns this into a null utilisation
        rather than a 0 % bar — see `StaffRow.utilisation`."""
        WorkingHours.objects.for_org(shop_setup.organization).filter(
            staff=shop_setup.grace
        ).delete()
        week = Period(WEDNESDAY, WEDNESDAY + timedelta(days=4))

        assert capacity.minutes_for(shop_setup.shop, [shop_setup.grace], week) == {
            shop_setup.grace.id: 0
        }


class TestItDoesNotQueryPerDay:
    def test_a_long_range_costs_the_same_as_a_short_one(
        self, shop_setup, django_assert_num_queries
    ):
        """The whole reason this module exists rather than a loop over
        `gather_shop_day`. Four queries — closures, opening hours, working
        hours, leave — however many days are asked for."""
        staff = [shop_setup.wanjiku, shop_setup.grace]
        quarter = Period(WEDNESDAY, WEDNESDAY + timedelta(days=89))

        with django_assert_num_queries(4):
            capacity.minutes_for(shop_setup.shop, staff, quarter)
