"""Weekly hours, dated closures, and which one wins.

Config only. No slot maths, no staff, no appointments — that is slice 3, and it
imports `Shop.is_open_on` as one of its inputs rather than reimplementing it.
"""

from datetime import date, time

import pytest
from django.db.utils import IntegrityError

from shops.models import Leave, OpeningHours, ShopClosure, WorkingHours

pytestmark = pytest.mark.django_db

# 2026-08-03 is a Monday; 2026-08-09 is the following Sunday.
MONDAY = date(2026, 8, 3)
SATURDAY = date(2026, 8, 8)
SUNDAY = date(2026, 8, 9)


class TestOpeningHours:
    def test_open_on_a_weekday_with_hours(self, shop_setup):
        assert shop_setup.shop.is_open_on(MONDAY) is True

    def test_closed_on_a_weekday_with_no_row(self, shop_setup):
        """Absence of a row is how a day off is expressed — the design's hours
        screen is per-day toggles, and toggling off removes the row."""
        assert shop_setup.shop.is_open_on(SUNDAY) is False

    def test_one_row_per_weekday(self, shop_setup):
        with pytest.raises(IntegrityError):
            OpeningHours.objects.create(
                shop=shop_setup.shop, weekday=0, opens_at=time(14, 0), closes_at=time(16, 0)
            )

    def test_closing_before_opening_is_refused_by_the_database(self, shop_setup):
        with pytest.raises(IntegrityError):
            OpeningHours.objects.create(
                shop=shop_setup.shop, weekday=6, opens_at=time(18, 0), closes_at=time(9, 0)
            )


class TestClosuresWin:
    def test_a_closure_beats_the_weekly_pattern(self, shop_setup):
        """Public holidays, renovations, a death in the family. A shop that
        cannot close for a day works around the product within a month."""
        assert shop_setup.shop.is_open_on(MONDAY) is True

        ShopClosure.objects.create(
            shop=shop_setup.shop, starts_on=MONDAY, ends_on=MONDAY, reason="Madaraka Day"
        )

        assert shop_setup.shop.is_open_on(MONDAY) is False

    def test_a_closure_range_covers_every_day_inside_it(self, shop_setup):
        ShopClosure.objects.create(
            shop=shop_setup.shop, starts_on=MONDAY, ends_on=SATURDAY, reason="Renovation"
        )

        assert shop_setup.shop.is_open_on(MONDAY) is False
        assert shop_setup.shop.is_open_on(SATURDAY) is False

    def test_a_closure_does_not_open_a_day_that_was_already_closed(self, shop_setup):
        ShopClosure.objects.create(shop=shop_setup.shop, starts_on=SUNDAY, ends_on=SUNDAY)

        assert shop_setup.shop.is_open_on(SUNDAY) is False

    def test_days_outside_the_closure_are_unaffected(self, shop_setup):
        ShopClosure.objects.create(shop=shop_setup.shop, starts_on=MONDAY, ends_on=MONDAY)

        assert shop_setup.shop.is_open_on(date(2026, 8, 4)) is True

    def test_overlapping_closures_are_allowed(self, shop_setup):
        """The union is what matters; rejecting overlaps would only make an
        owner delete one closure to add another."""
        ShopClosure.objects.create(shop=shop_setup.shop, starts_on=MONDAY, ends_on=SATURDAY)
        ShopClosure.objects.create(shop=shop_setup.shop, starts_on=date(2026, 8, 5), ends_on=SUNDAY)

        assert shop_setup.shop.is_open_on(date(2026, 8, 5)) is False

    def test_a_closure_ending_before_it_starts_is_refused(self, shop_setup):
        with pytest.raises(IntegrityError):
            ShopClosure.objects.create(shop=shop_setup.shop, starts_on=SATURDAY, ends_on=MONDAY)

    def test_covers_is_inclusive_at_both_ends(self, shop_setup):
        closure = ShopClosure.objects.create(
            shop=shop_setup.shop, starts_on=MONDAY, ends_on=SATURDAY
        )

        assert closure.covers(MONDAY)
        assert closure.covers(SATURDAY)
        assert not closure.covers(SUNDAY)


class TestWorkingHoursAndLeave:
    def test_one_working_row_per_weekday(self, shop_setup):
        with pytest.raises(IntegrityError):
            WorkingHours.objects.create(
                staff=shop_setup.wanjiku, weekday=0, starts_at=time(14, 0), ends_at=time(16, 0)
            )

    def test_ending_before_starting_is_refused(self, shop_setup):
        with pytest.raises(IntegrityError):
            WorkingHours.objects.create(
                staff=shop_setup.wanjiku, weekday=6, starts_at=time(18, 0), ends_at=time(9, 0)
            )

    def test_leave_is_recorded_as_an_inclusive_range(self, shop_setup):
        leave = Leave.objects.create(
            staff=shop_setup.wanjiku, starts_on=MONDAY, ends_on=SATURDAY, reason="Upcountry"
        )

        assert leave.covers(MONDAY)
        assert leave.covers(SATURDAY)
        assert not leave.covers(SUNDAY)

    def test_leave_ending_before_it_starts_is_refused(self, shop_setup):
        with pytest.raises(IntegrityError):
            Leave.objects.create(staff=shop_setup.wanjiku, starts_on=SATURDAY, ends_on=MONDAY)

    def test_leave_does_not_close_the_shop(self, shop_setup):
        """Slice 2 keeps these separate on purpose: a stylist on leave is a
        staff-availability fact, not a shop-hours fact. Combining them is slice
        3's job."""
        Leave.objects.create(staff=shop_setup.wanjiku, starts_on=MONDAY, ends_on=SATURDAY)

        assert shop_setup.shop.is_open_on(MONDAY) is True


class TestWeekdayNumbering:
    def test_weekday_matches_python(self, shop_setup):
        """`Weekday.MONDAY == 0 == date.weekday()`, so slice 3 needs no
        translation layer between the two."""
        from shops.models import Weekday

        assert Weekday.MONDAY == MONDAY.weekday() == 0
        assert Weekday.SUNDAY == SUNDAY.weekday() == 6
