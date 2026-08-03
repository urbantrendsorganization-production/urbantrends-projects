"""`create_appointment` — the one function that creates an appointment.

Slices 4 and 5 both call it, so what it guarantees here is what they inherit:
the slot is re-derived and never trusted, the price and duration are frozen onto
the row, and losing is an exception with a name rather than a 500.
"""

from datetime import timedelta

import pytest

from clients.models import Client
from scheduling.availability import Policy
from scheduling.booking import (
    SlotUnavailable,
    create_appointment,
    default_status_for,
)
from scheduling.models import Appointment
from scheduling.statuses import AppointmentStatus, BookingSource
from scheduling.tests.conftest import eat
from shops.durations import ServiceNotOffered
from shops.models import Leave, Service, ShopClosure, StaffService

pytestmark = pytest.mark.django_db


def book(shop_setup, when, *, staff=None, service=None, source=BookingSource.STAFF, **kwargs):
    return create_appointment(
        staff=staff or shop_setup.wanjiku,
        service=service or shop_setup.braids,
        starts_at=when,
        source=source,
        now=kwargs.pop("now", when - timedelta(hours=2)),
        **kwargs,
    )


class TestTheHappyPath:
    def test_it_creates_an_appointment(self, shop_setup, wednesday):
        when = eat(wednesday, 10)

        appointment = book(shop_setup, when)

        assert appointment.pk
        assert appointment.starts_at == when
        assert appointment.ends_at == when + timedelta(minutes=240)

    def test_the_organization_is_derived_not_supplied(self, shop_setup, wednesday):
        appointment = book(shop_setup, eat(wednesday, 10))

        assert appointment.organization_id == shop_setup.organization.id

    def test_a_client_can_be_attached(self, shop_setup, wednesday):
        client = Client.objects.create(
            organization=shop_setup.organization, full_name="Amina", phone="0712345678"
        )

        appointment = book(shop_setup, eat(wednesday, 10), client=client)

        assert appointment.client == client
        assert client.phone == "+254712345678"

    def test_a_walk_in_has_no_client(self, shop_setup, wednesday):
        """Three taps, CLAUDE.md §4. Requiring a client record would be a fourth."""
        appointment = book(shop_setup, eat(wednesday, 10), source=BookingSource.WALK_IN)

        assert appointment.client_id is None


class TestSnapshots:
    def test_price_deposit_and_duration_are_frozen_onto_the_row(self, shop_setup, wednesday):
        appointment = book(shop_setup, eat(wednesday, 10))

        assert appointment.price_snapshot == 3500
        assert appointment.deposit_snapshot == 875
        assert appointment.duration_snapshot == 240

    def test_a_later_price_rise_does_not_rewrite_history(self, shop_setup, wednesday):
        """Slice 2 established that deactivating a service leaves its
        appointments intact. Editing one has to work the same way, or last
        week's revenue changes when someone updates a price list."""
        appointment = book(shop_setup, eat(wednesday, 10))

        service = Service.all_objects.get(pk=shop_setup.braids.pk)
        service.price = 6000
        service.save()

        appointment.refresh_from_db()
        assert appointment.price_snapshot == 3500
        assert appointment.deposit_snapshot == 875

    def test_a_later_duration_change_does_not_move_the_appointment(self, shop_setup, wednesday):
        when = eat(wednesday, 10)
        appointment = book(shop_setup, when)

        service = Service.all_objects.get(pk=shop_setup.braids.pk)
        service.duration_minutes = 60
        service.save()

        appointment.refresh_from_db()
        assert appointment.ends_at == when + timedelta(minutes=240)
        assert appointment.duration_snapshot == 240

    def test_the_snapshot_uses_the_staff_specific_duration(self, shop_setup, wednesday):
        """The whole point of CLAUDE.md §3's override. A junior's booking must
        be as long as the junior actually takes."""
        StaffService.objects.for_org(shop_setup.organization).filter(
            staff=shop_setup.wanjiku, service=shop_setup.braids
        ).update(duration_override_minutes=180)
        service = Service.all_objects.get(pk=shop_setup.braids.pk)

        appointment = book(shop_setup, eat(wednesday, 10), service=service)

        assert appointment.duration_snapshot == 180
        assert appointment.ends_at == eat(wednesday, 13)


def book_online(shop_setup, when, **kwargs):
    """Same call, public policy. `Policy.for_public` is chosen by the source."""
    return book(shop_setup, when, source=BookingSource.ONLINE, **kwargs)


class TestTheSlotIsReDerivedForTheClient:
    """CLAUDE.md §4: never trust a client-supplied slot. Every request here is a
    hand-crafted body, not something the API ever offered."""

    def test_an_off_grid_start_is_refused(self, shop_setup, wednesday):
        with pytest.raises(SlotUnavailable):
            book_online(shop_setup, eat(wednesday, 10, 7))

    def test_a_start_outside_working_hours_is_refused(self, shop_setup, wednesday):
        with pytest.raises(SlotUnavailable):
            book_online(shop_setup, eat(wednesday, 7))

    def test_a_start_that_would_run_past_closing_is_refused(self, shop_setup, wednesday):
        """A four-hour braid at 16:00 ends at 20:00; the stylist finishes at
        18:00."""
        with pytest.raises(SlotUnavailable):
            book_online(shop_setup, eat(wednesday, 16))

    def test_a_closed_day_is_refused(self, shop_setup, wednesday):
        ShopClosure.objects.create(shop=shop_setup.shop, starts_on=wednesday, ends_on=wednesday)

        with pytest.raises(SlotUnavailable):
            book_online(shop_setup, eat(wednesday, 10))

    def test_a_day_the_staff_member_is_on_leave_is_refused(self, shop_setup, wednesday):
        Leave.objects.create(staff=shop_setup.wanjiku, starts_on=wednesday, ends_on=wednesday)

        with pytest.raises(SlotUnavailable):
            book_online(shop_setup, eat(wednesday, 10))

    def test_a_buffer_adjacent_slot_is_refused(self, shop_setup, wednesday):
        """The fixture buffer is ten minutes and the grid is fifteen, so the
        first legal start after a 09:00-13:00 braid is 13:15 — free from 13:10,
        rounded up to the next grid point."""
        book(shop_setup, eat(wednesday, 9))

        with pytest.raises(SlotUnavailable):
            book_online(shop_setup, eat(wednesday, 13))

        assert book_online(shop_setup, eat(wednesday, 13, 15))


class TestShopConfigIsAdvisoryForStaff:
    """Slice 4's decision (f), from the other side of the same fixture.

    Every request in the class above is refused for a client and permitted for a
    staff member, and that is the whole of the difference between the two
    policies. Each one is a thing that is physically happening in front of
    somebody: a client who turned up at seven, a stylist working through the
    lunchtime closure, a shave squeezed in at 11:07.
    """

    def test_an_off_grid_start_is_recorded(self, shop_setup, wednesday):
        appointment = book(shop_setup, eat(wednesday, 10, 7), service=shop_setup.shave)

        assert appointment.starts_at == eat(wednesday, 10, 7)

    def test_a_start_before_opening_is_recorded(self, shop_setup, wednesday):
        assert book(shop_setup, eat(wednesday, 7), service=shop_setup.shave)

    def test_a_service_running_past_closing_is_recorded(self, shop_setup, wednesday):
        """The 6:15 walk-in when hours end at 6:00. It must succeed."""
        appointment = book(shop_setup, eat(wednesday, 17, 55), service=shop_setup.shave)

        assert appointment.ends_at == eat(wednesday, 18, 15)

    def test_a_closed_day_is_recorded(self, shop_setup, wednesday):
        ShopClosure.objects.create(shop=shop_setup.shop, starts_on=wednesday, ends_on=wednesday)

        assert book(shop_setup, eat(wednesday, 10), service=shop_setup.shave)

    def test_a_leave_day_is_recorded(self, shop_setup, wednesday):
        """A stylist who came in anyway. The leave row is not deleted and the
        client's booking page still shows them away; this only records that
        somebody sat in the chair."""
        Leave.objects.create(staff=shop_setup.wanjiku, starts_on=wednesday, ends_on=wednesday)

        assert book(shop_setup, eat(wednesday, 10), service=shop_setup.shave)

    def test_the_buffer_does_not_block_a_walk_in(self, shop_setup, wednesday):
        """Back-to-back walk-ins are the common case on a Saturday. Making the
        second one wait ten minutes for a turnaround that has already happened
        would add a tap to the flow that must stay at three."""
        book(shop_setup, eat(wednesday, 9))

        assert book(shop_setup, eat(wednesday, 13), service=shop_setup.shave)

    def test_a_collision_is_still_refused(self, shop_setup, wednesday):
        """The one thing that is never advisory. Two people, one chair."""
        book(shop_setup, eat(wednesday, 10))

        with pytest.raises(SlotUnavailable):
            book(shop_setup, eat(wednesday, 10))

    def test_unavailable_can_only_mean_a_collision(self, shop_setup, wednesday):
        """The property the walk-in endpoint depends on: with hours, closures,
        the grid, the lead time and the buffer all switched off, nothing else is
        left to refuse. So a `SlotUnavailable` on the staff path is always
        resolvable into a choice, and the endpoint never has to guess."""
        ShopClosure.objects.create(shop=shop_setup.shop, starts_on=wednesday, ends_on=wednesday)
        Leave.objects.create(staff=shop_setup.wanjiku, starts_on=wednesday, ends_on=wednesday)

        # Shut, on leave, off-grid, outside hours — and still fine.
        assert book(shop_setup, eat(wednesday, 6, 3), service=shop_setup.shave)
        # Only the second one, on top of the first, fails.
        with pytest.raises(SlotUnavailable):
            book(shop_setup, eat(wednesday, 6, 3), service=shop_setup.shave)

    def test_a_staff_member_who_does_not_offer_the_service_raises(self, shop_setup, wednesday):
        """Loudly, and as a different exception. This is a programming error on
        the write path, not a busy calendar."""
        StaffService.objects.for_org(shop_setup.organization).filter(
            staff=shop_setup.wanjiku, service=shop_setup.braids
        ).update(is_offered=False)
        service = Service.all_objects.get(pk=shop_setup.braids.pk)

        with pytest.raises(ServiceNotOffered):
            book(shop_setup, eat(wednesday, 10), service=service)


class TestPolicy:
    def test_an_online_booking_respects_the_lead_time(self, shop_setup, wednesday):
        when = eat(wednesday, 10)

        with pytest.raises(SlotUnavailable):
            book(
                shop_setup,
                when,
                source=BookingSource.ONLINE,
                now=when - timedelta(minutes=5),  # inside the 30-minute default
            )

    def test_a_walk_in_ignores_the_lead_time(self, shop_setup, wednesday):
        """The three-tap walk-in would be impossible otherwise: the client is
        already in the chair."""
        when = eat(wednesday, 10)

        appointment = book(
            shop_setup, when, source=BookingSource.WALK_IN, now=when - timedelta(minutes=1)
        )

        assert appointment.pk

    def test_an_online_booking_respects_the_horizon(self, shop_setup, wednesday):
        far = wednesday + timedelta(days=196)  # 28 weeks: still a Wednesday

        with pytest.raises(SlotUnavailable):
            create_appointment(
                staff=shop_setup.wanjiku,
                service=shop_setup.braids,
                starts_at=eat(far, 10),
                source=BookingSource.ONLINE,
                now=eat(wednesday, 8),
            )

    def test_staff_can_book_beyond_the_horizon(self, shop_setup, wednesday):
        """A regular asking for their usual slot in six months is an ordinary
        request at the counter."""
        far = wednesday + timedelta(days=196)  # 28 weeks: still a Wednesday

        appointment = create_appointment(
            staff=shop_setup.wanjiku,
            service=shop_setup.braids,
            starts_at=eat(far, 10),
            source=BookingSource.STAFF,
            now=eat(wednesday, 8),
        )

        assert appointment.pk

    def test_an_explicit_policy_overrides_the_source_default(self, shop_setup, wednesday):
        when = eat(wednesday, 10)

        appointment = book(
            shop_setup,
            when,
            source=BookingSource.ONLINE,
            now=when - timedelta(minutes=1),
            policy=Policy.for_staff(),
        )

        assert appointment.pk


class TestStatus:
    def test_an_online_booking_starts_as_a_hold(self, shop_setup, wednesday):
        """Slice 6 fires the STK push and confirms it; here it only has to start
        in the state that blocks the slot."""
        appointment = book(shop_setup, eat(wednesday, 10), source=BookingSource.ONLINE)

        assert appointment.status == AppointmentStatus.PENDING_PAYMENT

    @pytest.mark.parametrize("source", [BookingSource.WALK_IN, BookingSource.STAFF])
    def test_anything_entered_by_a_person_is_already_confirmed(self, shop_setup, wednesday, source):
        appointment = book(shop_setup, eat(wednesday, 10), source=source)

        assert appointment.status == AppointmentStatus.CONFIRMED

    def test_the_default_is_a_function_not_a_literal(self):
        assert default_status_for(BookingSource.ONLINE) == AppointmentStatus.PENDING_PAYMENT
        assert default_status_for(BookingSource.WALK_IN) == AppointmentStatus.CONFIRMED

    def test_a_hold_blocks_the_slot_it_holds(self, shop_setup, wednesday):
        book(shop_setup, eat(wednesday, 10), source=BookingSource.ONLINE)

        with pytest.raises(SlotUnavailable):
            book(shop_setup, eat(wednesday, 10))


class TestCacheInteraction:
    def test_booking_leaves_no_stale_slot_behind(self, shop_setup, wednesday, clear_cache):
        """The read after the write must not still offer what was just taken.
        Without the invalidation receiver this is the bug that produces two
        clients in one chair via two separate requests."""
        from scheduling.availability import derive_slots
        from scheduling.cache import facts_for_staff_day

        when = eat(wednesday, 10)
        before = derive_slots(
            facts_for_staff_day(shop_setup.wanjiku, wednesday),
            duration_minutes=240,
            policy=Policy.for_staff(),
            now=eat(wednesday, 5),
        )
        assert when in [s.starts_at for s in before]

        book(shop_setup, when)

        after = derive_slots(
            facts_for_staff_day(shop_setup.wanjiku, wednesday),
            duration_minutes=240,
            policy=Policy.for_staff(),
            now=eat(wednesday, 5),
        )
        assert when not in [s.starts_at for s in after]


class TestTenantIsolation:
    def test_an_appointment_carries_its_own_shops_organization(
        self, shop_setup, rival_shop, wednesday
    ):
        ours = book(shop_setup, eat(wednesday, 10))
        theirs = create_appointment(
            staff=rival_shop.wanjiku,
            service=rival_shop.braids,
            starts_at=eat(wednesday, 10),
            source=BookingSource.STAFF,
            now=eat(wednesday, 8),
        )

        assert ours.organization_id != theirs.organization_id
        assert Appointment.objects.for_org(shop_setup.organization).count() == 1

    def test_the_derived_organization_cannot_be_forged(self, shop_setup, rival_shop, wednesday):
        """`OrgDerivedModel` recomputes it from the parent on every save, so a
        supplied value is overwritten rather than trusted."""
        start = eat(wednesday, 10)
        appointment = Appointment.objects.create(
            shop=shop_setup.shop,
            organization=rival_shop.organization,  # a lie
            staff=shop_setup.wanjiku,
            service=shop_setup.braids,
            time_range=(start, start + timedelta(hours=1)),
            status=AppointmentStatus.CONFIRMED,
            source=BookingSource.STAFF,
            price_snapshot=3500,
            deposit_snapshot=875,
            duration_snapshot=60,
        )

        assert appointment.organization_id == shop_setup.organization.id
