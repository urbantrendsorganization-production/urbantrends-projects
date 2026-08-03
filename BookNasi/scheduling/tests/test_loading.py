"""The same rules as `test_derivation.py`, but read out of the database.

`test_derivation.py` proves the arithmetic. This proves the loader turns real
`shops` rows into the facts that arithmetic expects — the join between slice 2's
configuration and slice 3's engine, which is where a rule can be correct in
isolation and still never fire.

The precedence assertions here are the important ones: closure beats working
hours beats opening hours, in that order.
"""

from datetime import date, time, timedelta

import pytest

from scheduling.availability import Policy, derive_slots, local_date
from scheduling.loading import gather_shop_day, gather_staff_day, staff_for_service
from scheduling.models import Appointment
from scheduling.statuses import AppointmentStatus, BookingSource
from scheduling.tests.conftest import eat
from shops.models import Leave, OpeningHours, Service, ShopClosure, StaffService, WorkingHours

pytestmark = pytest.mark.django_db

NO_POLICY = Policy()


def slot_times(slots):
    from scheduling.availability import LOCAL_TZ

    return [s.starts_at.astimezone(LOCAL_TZ).strftime("%H:%M") for s in slots]


def slots_for(staff, day, duration, *, now=None, policy=NO_POLICY):
    facts = gather_staff_day(staff, day)
    return derive_slots(facts, duration_minutes=duration, policy=policy, now=now or eat(day, 5))


def book(shop_setup, staff, day, hour, minutes=60, status=AppointmentStatus.CONFIRMED):
    start = eat(day, hour)
    return Appointment.objects.create(
        shop=shop_setup.shop,
        staff=staff,
        service=shop_setup.braids,
        time_range=(start, start + timedelta(minutes=minutes)),
        status=status,
        source=BookingSource.STAFF,
        price_snapshot=3500,
        deposit_snapshot=875,
        duration_snapshot=minutes,
    )


class TestPrecedence:
    """Closure beats working hours beats opening hours, in that order."""

    def test_an_ordinary_day_has_slots(self, shop_setup, wednesday):
        assert slots_for(shop_setup.wanjiku, wednesday, 60)

    def test_a_weekday_the_shop_does_not_open_has_none(self, shop_setup):
        sunday = date(2026, 9, 13)

        assert slots_for(shop_setup.wanjiku, sunday, 60) == ()

    def test_a_closure_beats_working_hours(self, shop_setup, wednesday):
        """The stylist is rostered, and it is a public holiday. The closure is
        the fact that wins — a shop that cannot close for a day works around the
        product inside a month."""
        assert slots_for(shop_setup.wanjiku, wednesday, 60)

        ShopClosure.objects.create(
            shop=shop_setup.shop, starts_on=wednesday, ends_on=wednesday, reason="Public holiday"
        )

        assert slots_for(shop_setup.wanjiku, wednesday, 60) == ()

    def test_a_closure_beats_working_hours_for_every_staff_member(self, shop_setup, wednesday):
        ShopClosure.objects.create(shop=shop_setup.shop, starts_on=wednesday, ends_on=wednesday)

        facts = gather_shop_day(shop_setup.shop, wednesday)

        assert all(f.window is None for f in facts.values())

    def test_leave_beats_working_hours(self, shop_setup, wednesday):
        Leave.objects.create(
            staff=shop_setup.wanjiku, starts_on=wednesday, ends_on=wednesday, reason="Sick"
        )

        assert slots_for(shop_setup.wanjiku, wednesday, 60) == ()
        # And only for her.
        assert slots_for(shop_setup.grace, wednesday, 60)

    def test_working_hours_narrow_opening_hours_but_never_widen_them(self, shop_setup, wednesday):
        """A stylist rostered 07:00-22:00 at a shop open 08:00-20:00 is
        available 08:00-20:00, not 07:00-22:00."""
        WorkingHours.objects.for_org(shop_setup.organization).filter(
            staff=shop_setup.wanjiku, weekday=wednesday.weekday()
        ).update(starts_at=time(7, 0), ends_at=time(22, 0))

        times = slot_times(slots_for(shop_setup.wanjiku, wednesday, 60))

        assert times[0] == "08:00"
        assert times[-1] == "19:00"

    def test_a_closure_range_covers_every_day_inside_it(self, shop_setup, wednesday):
        ShopClosure.objects.create(
            shop=shop_setup.shop,
            starts_on=wednesday - timedelta(days=1),
            ends_on=wednesday + timedelta(days=1),
            reason="Renovation",
        )

        for offset in (-1, 0, 1):
            assert slots_for(shop_setup.wanjiku, wednesday + timedelta(days=offset), 60) == ()


class TestLeaveSplittingTheDay:
    """Whole-day leave removes the day. A *booked-out* block splits it, and that
    is the shape the engine has to get right."""

    def test_a_mid_day_block_leaves_two_windows(self, shop_setup, wednesday):
        book(shop_setup, shop_setup.wanjiku, wednesday, 12, minutes=120)

        times = slot_times(slots_for(shop_setup.wanjiku, wednesday, 60))
        morning = [t for t in times if t < "12:00"]
        afternoon = [t for t in times if t >= "14:00"]

        assert morning[0] == "09:00"
        # Buffer is 10 minutes in the fixture, so the last morning slot must
        # finish by 11:50.
        assert morning[-1] == "10:45"
        assert afternoon[0] == "14:15"  # 14:00 + one buffer
        assert times == morning + afternoon  # nothing in between

    def test_two_blocks_leave_three_windows(self, shop_setup, wednesday):
        book(shop_setup, shop_setup.wanjiku, wednesday, 10, minutes=60)
        book(shop_setup, shop_setup.wanjiku, wednesday, 14, minutes=60)

        times = slot_times(slots_for(shop_setup.wanjiku, wednesday, 30))

        assert "09:00" in times
        assert "11:15" in times
        assert "15:15" in times
        assert "10:00" not in times
        assert "14:00" not in times


class TestBlockingStatuses:
    def test_a_cancelled_appointment_frees_its_slot(self, shop_setup, wednesday):
        appointment = book(shop_setup, shop_setup.wanjiku, wednesday, 10)
        assert "10:00" not in slot_times(slots_for(shop_setup.wanjiku, wednesday, 60))

        appointment.status = AppointmentStatus.CANCELLED
        appointment.save(update_fields=["status"])

        assert "10:00" in slot_times(slots_for(shop_setup.wanjiku, wednesday, 60))

    def test_a_completed_appointment_does_not_free_its_slot(self, shop_setup, wednesday):
        """Wider than the exclusion constraint by exactly one status, on
        purpose — see scheduling/statuses.py. That time was worked; offering it
        again would let a staff member record a walk-in on top of a job that
        already happened, and would make today's staff view show a free 11:00
        for a cut that finished at 11:30."""
        appointment = book(shop_setup, shop_setup.wanjiku, wednesday, 10)
        appointment.status = AppointmentStatus.COMPLETED
        appointment.save(update_fields=["status"])

        assert "10:00" not in slot_times(slots_for(shop_setup.wanjiku, wednesday, 60))

    def test_a_no_show_frees_its_slot(self, shop_setup, wednesday):
        appointment = book(shop_setup, shop_setup.wanjiku, wednesday, 10)
        appointment.status = AppointmentStatus.NO_SHOW
        appointment.save(update_fields=["status"])

        assert "10:00" in slot_times(slots_for(shop_setup.wanjiku, wednesday, 60))

    def test_a_pending_payment_hold_blocks_its_slot(self, shop_setup, wednesday):
        """The hold is the product. If it did not block, the deposit would be
        collected for a slot someone else had already taken."""
        book(
            shop_setup,
            shop_setup.wanjiku,
            wednesday,
            10,
            status=AppointmentStatus.PENDING_PAYMENT,
        )

        assert "10:00" not in slot_times(slots_for(shop_setup.wanjiku, wednesday, 60))

    def test_another_staff_members_booking_does_not_block_this_one(self, shop_setup, wednesday):
        book(shop_setup, shop_setup.grace, wednesday, 10)

        assert "10:00" in slot_times(slots_for(shop_setup.wanjiku, wednesday, 60))


class TestPerStaffDuration:
    def test_an_override_changes_the_slot_set_for_that_staff_only(self, shop_setup, wednesday):
        """CLAUDE.md §3: "A senior stylist does in 30 min what a junior takes 50
        for. If the schedule can't express that, the calendar lies and staff
        stop trusting it."
        """
        StaffService.objects.for_org(shop_setup.organization).filter(
            staff=shop_setup.wanjiku, service=shop_setup.braids
        ).update(duration_override_minutes=180)

        wanjiku = gather_staff_day(shop_setup.wanjiku, wednesday)
        grace = gather_staff_day(shop_setup.grace, wednesday)

        # 180 minutes fits until 15:00; the service's own 240 only until 14:00.
        wanjiku_times = slot_times(
            derive_slots(wanjiku, duration_minutes=180, policy=NO_POLICY, now=eat(wednesday, 5))
        )
        grace_times = slot_times(
            derive_slots(grace, duration_minutes=240, policy=NO_POLICY, now=eat(wednesday, 5))
        )

        assert wanjiku_times[-1] == "15:00"
        assert grace_times[-1] == "14:00"

    def test_a_staff_member_who_does_not_offer_the_service_is_omitted(self, shop_setup):
        StaffService.objects.for_org(shop_setup.organization).filter(
            staff=shop_setup.grace, service=shop_setup.braids
        ).update(is_offered=False)

        offering = [row.id for row, _ in staff_for_service(shop_setup.braids)]

        assert shop_setup.wanjiku.id in offering
        assert shop_setup.grace.id not in offering

    def test_a_deactivated_staff_member_is_omitted(self, shop_setup):
        shop_setup.grace.is_active = False
        shop_setup.grace.save(update_fields=["is_active"])

        offering = [row.id for row, _ in staff_for_service(shop_setup.braids)]

        assert shop_setup.grace.id not in offering

    def test_a_non_bookable_staff_member_is_omitted(self, shop_setup):
        """`is_bookable=False` is the shop manager who does not take clients."""
        shop_setup.grace.is_bookable = False
        shop_setup.grace.save(update_fields=["is_bookable"])

        offering = [row.id for row, _ in staff_for_service(shop_setup.braids)]

        assert shop_setup.grace.id not in offering


class TestLongAppointmentsAcrossTheDayBoundary:
    def test_a_booking_that_started_yesterday_evening_is_still_seen(self, shop_setup, wednesday):
        """The loader widens its window by a day either side. Without that, a
        long service started before local midnight would be invisible to the
        next day's derivation and the slot would be offered twice.

        Today the check constraint on opening hours makes this unreachable
        through the API — see availability.py decision (e) — so this is the
        regression test for the day someone adds `closes_next_day`.
        """
        start = eat(wednesday - timedelta(days=1), 23)
        Appointment.objects.create(
            shop=shop_setup.shop,
            staff=shop_setup.wanjiku,
            service=shop_setup.braids,
            time_range=(start, start + timedelta(hours=11)),  # runs to 10:00 today
            status=AppointmentStatus.CONFIRMED,
            source=BookingSource.STAFF,
            price_snapshot=3500,
            deposit_snapshot=875,
            duration_snapshot=660,
        )

        times = slot_times(slots_for(shop_setup.wanjiku, wednesday, 60))

        assert "09:00" not in times
        # Free from 10:10 (10:00 plus the fixture's 10-minute buffer), but the
        # grid is anchored to midnight at 15-minute steps, so the first
        # *offerable* start is 10:15. Decision (a) stranding five minutes,
        # visible in a test rather than described in a comment.
        assert "10:10" not in times
        assert "10:15" in times


class TestQueryCount:
    def test_a_shop_day_across_eight_staff_is_a_fixed_number_of_queries(
        self, shop_setup, wednesday, django_assert_num_queries
    ):
        """Asserted as a *number* so slice 4 cannot quietly make the staff day
        view N+1. The day view draws eight stylists side by side; a per-staff
        loader would be forty-eight queries before anyone scrolled.

        If this fails because the loader legitimately needs another query, raise
        the number deliberately and say why in the commit. Do not make it a
        range.
        """
        from shops.models import Staff

        for index in range(6):
            staff = Staff.objects.create(shop=shop_setup.shop, display_name=f"Stylist {index}")
            WorkingHours.objects.create(
                staff=staff,
                weekday=wednesday.weekday(),
                starts_at=time(9, 0),
                ends_at=time(18, 0),
            )
        everyone = list(shop_setup.shop.staff.filter(is_active=True))
        assert len(everyone) == 8

        with django_assert_num_queries(5):
            gather_shop_day(shop_setup.shop, wednesday, staff=everyone)

    def test_the_query_count_does_not_grow_with_staff(
        self, shop_setup, wednesday, django_assert_num_queries
    ):
        """Two staff and eight staff cost the same. That is the property that
        matters, and it is the one that silently breaks."""
        two = list(shop_setup.shop.staff.filter(is_active=True))

        with django_assert_num_queries(5):
            gather_shop_day(shop_setup.shop, wednesday, staff=two)

    def test_the_count_holds_with_appointments_present(
        self, shop_setup, wednesday, django_assert_num_queries
    ):
        for hour in (9, 11, 15):
            book(shop_setup, shop_setup.wanjiku, wednesday, hour)
        everyone = list(shop_setup.shop.staff.filter(is_active=True))

        with django_assert_num_queries(5):
            gather_shop_day(shop_setup.shop, wednesday, staff=everyone)


class TestFactsAreServiceIndependent:
    def test_the_same_facts_serve_every_service(self, shop_setup, wednesday):
        """Why the cache can key on `(staff_id, date)` with no service
        dimension — see scheduling/cache.py."""
        facts = gather_staff_day(shop_setup.wanjiku, wednesday)

        long_service = derive_slots(
            facts, duration_minutes=240, policy=NO_POLICY, now=eat(wednesday, 5)
        )
        short_service = derive_slots(
            facts, duration_minutes=20, policy=NO_POLICY, now=eat(wednesday, 5)
        )

        assert len(short_service) > len(long_service)
        assert facts.day == wednesday

    def test_the_day_on_the_facts_is_the_eat_date(self, shop_setup, wednesday):
        facts = gather_staff_day(shop_setup.wanjiku, wednesday)

        assert facts.day == wednesday
        assert local_date(facts.shop_window.starts_at) == wednesday


class TestServiceChangesAreVisible:
    def test_changing_a_service_duration_changes_the_slot_set(self, shop_setup, wednesday):
        service = Service.all_objects.get(pk=shop_setup.braids.pk)
        service.duration_minutes = 60
        service.save()

        _, link = next(
            pair for pair in staff_for_service(service) if pair[0].id == shop_setup.wanjiku.id
        )

        assert link.effective_duration_minutes == 60

    def test_opening_hours_changes_move_the_first_slot(self, shop_setup, wednesday):
        OpeningHours.objects.for_org(shop_setup.organization).filter(
            shop=shop_setup.shop, weekday=wednesday.weekday()
        ).update(opens_at=time(11, 0))

        times = slot_times(slots_for(shop_setup.wanjiku, wednesday, 60))

        assert times[0] == "11:00"
