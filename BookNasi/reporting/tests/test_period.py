"""The range, and the comparison it is allowed to draw."""

from datetime import date, timedelta

import pytest

from reporting.period import DEFAULT_DAYS, MAX_DAYS, Period, PeriodInvalid, parse_period
from scheduling.tests.conftest import eat


class TestTheRangeItself:
    def test_both_ends_are_inclusive(self):
        assert Period(date(2026, 6, 1), date(2026, 6, 30)).days == 30

    def test_one_day_is_one_day(self):
        assert Period(date(2026, 6, 1), date(2026, 6, 1)).days == 1

    def test_the_utc_bounds_are_half_open(self):
        """Matching `time_range` everywhere else. A booking at exactly midnight
        EAT belongs to the day it starts and to no other."""
        period = Period(date(2026, 6, 1), date(2026, 6, 1))
        lo, hi = period.utc_bounds

        assert (hi - lo) == timedelta(days=1)
        assert period.contains(lo)
        assert not period.contains(hi)


class TestThePreviousPeriod:
    def test_it_is_the_same_length_and_immediately_before(self):
        period = Period(date(2026, 6, 1), date(2026, 6, 30))
        previous = period.previous

        assert previous.days == period.days
        assert previous.ends_on == date(2026, 5, 31)
        assert previous.starts_on == date(2026, 5, 2)

    def test_the_two_do_not_overlap(self):
        """An overlap would count the same booking on both sides of the
        comparison, and the trend would flatten toward zero as the range grew."""
        period = Period(date(2026, 6, 1), date(2026, 6, 7))

        assert period.previous.ends_on < period.starts_on


class TestParsing:
    def test_neither_end_given_is_the_last_thirty_days_ending_today(self):
        period = parse_period({}, now=eat(date(2026, 8, 14), 12))

        assert period.ends_on == date(2026, 8, 14)
        assert period.days == DEFAULT_DAYS

    def test_a_start_alone_runs_to_today(self):
        """ "Since the 1st" is a thing an owner means."""
        period = parse_period({"from": "2026-08-01"}, now=eat(date(2026, 8, 14), 12))

        assert (period.starts_on, period.ends_on) == (date(2026, 8, 1), date(2026, 8, 14))

    def test_a_backwards_range_is_refused(self):
        with pytest.raises(PeriodInvalid):
            parse_period({"from": "2026-08-14", "to": "2026-08-01"})

    def test_an_unparseable_date_is_refused_rather_than_defaulted(self):
        """A dashboard that silently substitutes a different range than the one
        asked for is a dashboard whose numbers cannot be checked."""
        with pytest.raises(PeriodInvalid):
            parse_period({"from": "last tuesday"})

    def test_a_range_longer_than_the_cap_is_refused(self):
        with pytest.raises(PeriodInvalid):
            parse_period({"from": "2020-01-01", "to": "2026-01-01"})

    def test_the_cap_itself_is_allowed(self):
        start = date(2026, 1, 1)
        period = parse_period(
            {"from": start.isoformat(), "to": (start + timedelta(days=MAX_DAYS - 1)).isoformat()}
        )

        assert period.days == MAX_DAYS
