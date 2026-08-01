"""The derivation engine, with no database and no Redis.

These run against `StaffDayFacts` built by hand. That is the point of the engine
being pure: the highest-risk code in the repo can be exercised at the speed of
arithmetic, and a failure here points at the rule rather than at a fixture.

The database-backed versions of the same rules live in `test_loading.py`.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from scheduling.availability import (
    LOCAL_TZ,
    Interval,
    Policy,
    StaffDayFacts,
    derive_slots,
    is_bookable_start,
    local_date,
    local_midnight,
)

UTC = ZoneInfo("UTC")
DAY = date(2026, 9, 9)


def eat(hour, minute=0, day=DAY):
    return datetime.combine(day, time(hour, minute), tzinfo=LOCAL_TZ).astimezone(UTC)


def facts(
    *,
    opens=8,
    closes=20,
    works_from=9,
    works_to=18,
    busy=(),
    buffer_minutes=0,
    interval=15,
    shop_open=True,
    working=True,
):
    return StaffDayFacts(
        staff_id="s1",
        day=DAY,
        shop_window=Interval(eat(opens), eat(closes)) if shop_open else None,
        staff_window=Interval(eat(works_from), eat(works_to)) if working else None,
        busy=tuple(Interval(eat(*s), eat(*e)) for s, e in busy),
        buffer_minutes=buffer_minutes,
        slot_interval_minutes=interval,
    )


def starts(slots):
    """Slot starts as EAT `HH:MM` strings — the form the assertions read in."""
    return [s.starts_at.astimezone(LOCAL_TZ).strftime("%H:%M") for s in slots]


NO_POLICY = Policy()
EARLY = eat(5)


class TestTheWindow:
    def test_slots_start_where_shop_and_staff_hours_overlap(self):
        slots = derive_slots(facts(), duration_minutes=60, policy=NO_POLICY, now=EARLY)

        # Shop opens 08:00 but this stylist starts at 09:00.
        assert starts(slots)[0] == "09:00"

    def test_the_last_slot_ends_by_the_earlier_of_the_two_closes(self):
        slots = derive_slots(facts(), duration_minutes=60, policy=NO_POLICY, now=EARLY)

        # Works to 18:00, so the last hour-long slot starts at 17:00.
        assert starts(slots)[-1] == "17:00"

    def test_a_closed_shop_yields_nothing(self):
        """Zero availability is an empty tuple, never an error. Slice 4's day
        view renders it as 'closed', and an exception here would render as a
        500 on an ordinary Sunday."""
        assert (
            derive_slots(facts(shop_open=False), duration_minutes=60, policy=NO_POLICY, now=EARLY)
            == ()
        )

    def test_a_staff_member_who_is_off_yields_nothing(self):
        assert (
            derive_slots(facts(working=False), duration_minutes=60, policy=NO_POLICY, now=EARLY)
            == ()
        )

    def test_hours_that_do_not_overlap_yield_nothing(self):
        """A stylist rostered 06:00-07:00 at a shop that opens at 08:00. An
        owner can save this; it is not an error, and it is not availability."""
        day = facts(opens=8, closes=20, works_from=6, works_to=7)

        assert day.window is None
        assert derive_slots(day, duration_minutes=30, policy=NO_POLICY, now=EARLY) == ()

    def test_a_service_longer_than_the_remaining_hours_yields_nothing(self):
        """A ten-hour braid at a stylist who works nine. Not an error — the
        service is real and bookable on a longer day, just not this one."""
        assert derive_slots(facts(), duration_minutes=600, policy=NO_POLICY, now=EARLY) == ()

    def test_a_service_that_exactly_fills_the_day_yields_one_slot(self):
        slots = derive_slots(facts(), duration_minutes=9 * 60, policy=NO_POLICY, now=EARLY)

        assert starts(slots) == ["09:00"]


class TestTheGrid:
    """Decision (a): fixed clock grid, anchored to midnight EAT."""

    def test_slots_land_on_the_interval(self):
        slots = derive_slots(facts(interval=15), duration_minutes=60, policy=NO_POLICY, now=EARLY)

        assert starts(slots)[:4] == ["09:00", "09:15", "09:30", "09:45"]

    def test_the_interval_is_configurable(self):
        slots = derive_slots(facts(interval=30), duration_minutes=60, policy=NO_POLICY, now=EARLY)

        assert starts(slots)[:3] == ["09:00", "09:30", "10:00"]

    def test_the_grid_is_anchored_to_midnight_not_to_opening_time(self):
        """Two shops with the same interval offer the same clock times, and
        moving opening time by five minutes does not shift the whole day."""
        slots = derive_slots(
            facts(works_from=9, interval=30), duration_minutes=30, policy=NO_POLICY, now=EARLY
        )
        shifted = facts(interval=30)
        shifted = StaffDayFacts(
            staff_id="s1",
            day=DAY,
            shop_window=Interval(eat(8, 5), eat(20)),
            staff_window=Interval(eat(9, 5), eat(18)),
            buffer_minutes=0,
            slot_interval_minutes=30,
        )
        shifted_slots = derive_slots(shifted, duration_minutes=30, policy=NO_POLICY, now=EARLY)

        assert starts(slots)[0] == "09:00"
        # Opening five minutes later moves the first slot to the next grid
        # point, not to 09:05.
        assert starts(shifted_slots)[0] == "09:30"

    def test_an_opening_time_off_the_grid_rounds_up_never_down(self):
        """Rounding down would offer a slot before the shop opens."""
        odd = StaffDayFacts(
            staff_id="s1",
            day=DAY,
            shop_window=Interval(eat(8), eat(20)),
            staff_window=Interval(eat(9, 20), eat(18)),
            slot_interval_minutes=15,
        )
        slots = derive_slots(odd, duration_minutes=30, policy=NO_POLICY, now=EARLY)

        assert starts(slots)[0] == "09:30"


class TestBusyTime:
    def test_an_appointment_removes_the_slots_it_covers(self):
        slots = derive_slots(
            facts(busy=[((10,), (11,))]), duration_minutes=60, policy=NO_POLICY, now=EARLY
        )

        assert "10:00" not in starts(slots)
        assert "09:15" not in starts(slots)  # would run into the 10:00 booking
        assert "09:00" in starts(slots)
        assert "11:00" in starts(slots)

    def test_a_slot_may_start_the_instant_another_ends(self):
        """Half-open ranges, `[start, end)`. Back-to-back is the normal case in
        a busy shop and must not be treated as a collision."""
        slots = derive_slots(
            facts(busy=[((10,), (11,))]), duration_minutes=60, policy=NO_POLICY, now=EARLY
        )

        assert "11:00" in starts(slots)

    def test_two_bookings_leave_the_gap_between_them(self):
        slots = derive_slots(
            facts(busy=[((9,), (10,)), ((11,), (12,))]),
            duration_minutes=60,
            policy=NO_POLICY,
            now=EARLY,
        )

        assert "10:00" in starts(slots)

    def test_a_gap_too_short_for_the_service_is_not_offered(self):
        slots = derive_slots(
            facts(busy=[((9,), (10,)), ((10, 30), (12,))]),
            duration_minutes=60,
            policy=NO_POLICY,
            now=EARLY,
        )

        assert "10:00" not in starts(slots)

    def test_leave_mid_day_splits_availability_into_two_windows(self):
        """Leave arrives as a busy interval from the loader when it is partial;
        the engine's job is to leave a clean window either side of it."""
        slots = starts(
            derive_slots(
                facts(busy=[((12,), (14,))]),
                duration_minutes=60,
                policy=NO_POLICY,
                now=EARLY,
            )
        )

        assert "11:00" in slots  # ends exactly at 12:00
        assert "11:15" not in slots
        assert "12:00" not in slots
        assert "13:00" not in slots
        assert "14:00" in slots
        # Two contiguous runs, not one and not three.
        assert slots[0] == "09:00" and slots[-1] == "17:00"


class TestBuffer:
    """Decision (b): applied after a service, never before."""

    def test_the_slot_immediately_after_a_booking_is_pushed_out_by_the_buffer(self):
        slots = starts(
            derive_slots(
                facts(busy=[((10,), (11,))], buffer_minutes=15),
                duration_minutes=60,
                policy=NO_POLICY,
                now=EARLY,
            )
        )

        assert "11:00" not in slots
        assert "11:15" in slots

    def test_the_exactly_buffer_adjacent_slot_is_offered(self):
        """The boundary case. One minute either way here is the difference
        between a stylist with no turnaround and a stylist losing a slot a day."""
        slots = starts(
            derive_slots(
                facts(busy=[((10,), (11,))], buffer_minutes=30),
                duration_minutes=60,
                policy=NO_POLICY,
                now=EARLY,
            )
        )

        assert "11:30" in slots
        assert "11:15" not in slots

    def test_the_buffer_also_applies_before_the_next_booking(self):
        """Applied *after* a service means the candidate carries its own
        trailing buffer, so the gap works out to exactly one buffer on both
        sides rather than two."""
        slots = starts(
            derive_slots(
                facts(busy=[((12,), (13,))], buffer_minutes=15),
                duration_minutes=60,
                policy=NO_POLICY,
                now=EARLY,
            )
        )

        assert "11:00" not in slots  # would end at 12:00 with no turnaround
        assert "10:45" in slots  # ends 11:45, then 15 minutes before 12:00

    def test_exactly_one_buffer_sits_between_two_appointments(self):
        """The reason it is not applied on both sides: two buffers would be 30
        minutes of turnaround for one sweep-up."""
        slots = starts(
            derive_slots(
                facts(busy=[((9,), (10,)), ((11, 30), (12, 30))], buffer_minutes=15),
                duration_minutes=60,
                policy=NO_POLICY,
                now=EARLY,
            )
        )

        assert "10:15" in slots  # 10:00 + one buffer, ends 11:15, +15 = 11:30

    def test_the_first_slot_of_the_day_is_not_pushed_out_by_the_buffer(self):
        """There is nothing to turn the chair around from at opening time."""
        slots = derive_slots(
            facts(buffer_minutes=30), duration_minutes=60, policy=NO_POLICY, now=EARLY
        )

        assert starts(slots)[0] == "09:00"

    def test_the_last_slot_may_end_exactly_at_closing(self):
        """The trailing buffer is for the next client, and there is not one."""
        slots = derive_slots(
            facts(buffer_minutes=30), duration_minutes=60, policy=NO_POLICY, now=EARLY
        )

        assert starts(slots)[-1] == "17:00"


class TestLeadTimeAndHorizon:
    """Decisions (c) and (d)."""

    def test_a_slot_starting_within_the_lead_time_is_not_offered(self):
        """Nobody should book something starting in 90 seconds."""
        slots = starts(
            derive_slots(
                facts(),
                duration_minutes=60,
                policy=Policy(min_lead_minutes=30),
                now=eat(10, 50),
            )
        )

        assert "11:00" not in slots
        assert "11:30" in slots

    def test_a_slot_exactly_at_the_lead_boundary_is_offered(self):
        slots = starts(
            derive_slots(
                facts(), duration_minutes=60, policy=Policy(min_lead_minutes=30), now=eat(10, 30)
            )
        )

        assert "11:00" in slots

    def test_staff_have_no_lead_time(self):
        """A walk-in starts now. `Policy.for_staff()` is what makes the
        three-tap walk-in possible at all — CLAUDE.md §4."""
        slots = starts(
            derive_slots(facts(), duration_minutes=60, policy=Policy.for_staff(), now=eat(10, 59))
        )

        assert "11:00" in slots

    def test_a_day_beyond_the_horizon_yields_nothing(self):
        """An unbounded horizon lets one script fill a stylist's entire year
        with pending_payment holds; the horizon is what bounds that blast
        radius to `booking_horizon_days` of damage."""
        assert (
            derive_slots(
                facts(),
                duration_minutes=60,
                policy=Policy(horizon_days=7),
                now=eat(5, 0, day=DAY - timedelta(days=30)),
            )
            == ()
        )

    def test_the_last_day_inside_the_horizon_is_fully_available(self):
        """The horizon is a whole number of days, so it does not shrink through
        the afternoon — otherwise the bookable set would change under a client
        who left the page open."""
        slots = derive_slots(
            facts(),
            duration_minutes=60,
            policy=Policy(horizon_days=7),
            now=eat(16, 0, day=DAY - timedelta(days=7)),
        )

        assert starts(slots)[-1] == "17:00"

    def test_one_day_past_the_horizon_is_empty(self):
        assert (
            derive_slots(
                facts(),
                duration_minutes=60,
                policy=Policy(horizon_days=7),
                now=eat(16, 0, day=DAY - timedelta(days=8)),
            )
            == ()
        )


class TestTimezoneBoundaries:
    """Decision (e): a staff-day is a calendar date in EAT."""

    def test_a_staff_day_is_an_eat_calendar_date(self):
        """09:00 EAT is 06:00 UTC. The day it belongs to is the EAT one."""
        moment = eat(9)

        assert moment.astimezone(UTC).hour == 6
        assert local_date(moment) == DAY

    def test_an_early_morning_slot_belongs_to_the_eat_day_not_the_utc_one(self):
        """01:00 EAT on the 9th is 22:00 UTC on the 8th. Keying the cache on the
        UTC date would put it in the wrong bucket and invalidation would miss
        it — which is why `cache.key_for` uses `local_date`."""
        moment = eat(1)

        assert moment.astimezone(UTC).date() == DAY - timedelta(days=1)
        assert local_date(moment) == DAY

    def test_local_midnight_is_2100_utc_the_previous_day(self):
        assert local_midnight(DAY).astimezone(UTC).strftime("%Y-%m-%d %H:%M") == "2026-09-08 21:00"

    def test_every_slot_of_a_day_shares_one_local_date(self):
        """What makes `(staff_id, local_date)` a correct partition. It holds
        because slice 2's check constraint makes overnight opening hours
        inexpressible — see availability.py, decision (e)."""
        slots = derive_slots(facts(), duration_minutes=30, policy=NO_POLICY, now=EARLY)

        assert {local_date(s.starts_at) for s in slots} == {DAY}
        assert {local_date(s.ends_at - timedelta(seconds=1)) for s in slots} == {DAY}


class TestReDerivationOnWrite:
    def test_a_derived_start_is_bookable(self):
        day = facts()
        slot = derive_slots(day, duration_minutes=60, policy=NO_POLICY, now=EARLY)[0]

        assert is_bookable_start(
            day, starts_at=slot.starts_at, duration_minutes=60, policy=NO_POLICY, now=EARLY
        )

    def test_an_off_grid_start_is_not_bookable(self):
        """CLAUDE.md §4: never trust a client-supplied slot. A hand-crafted
        request body asking for 09:07 is refused even though it is inside
        working hours and collides with nothing."""
        assert not is_bookable_start(
            facts(), starts_at=eat(9, 7), duration_minutes=60, policy=NO_POLICY, now=EARLY
        )

    def test_a_start_inside_a_booking_is_not_bookable(self):
        assert not is_bookable_start(
            facts(busy=[((10,), (11,))]),
            starts_at=eat(10),
            duration_minutes=60,
            policy=NO_POLICY,
            now=EARLY,
        )

    @pytest.mark.parametrize("duration", [0, -30])
    def test_a_nonsense_duration_yields_nothing_rather_than_a_full_day(self, duration):
        """A zero duration would otherwise make every grid point 'fit'."""
        assert derive_slots(facts(), duration_minutes=duration, policy=NO_POLICY, now=EARLY) == ()
