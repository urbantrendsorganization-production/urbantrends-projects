"""LOAD-BEARING. Double-booking, prevented at the database.

CLAUDE.md §4: "Two clients tapping 'confirm' in the same second both pass an
application-level `if slot_is_free` check. Enable `btree_gist` and add an
exclusion constraint... Do not replace this with a lock, a queue, or a
`select_for_update` and call it done — the constraint stays regardless of what
else you add."

**Real threads, real connections, no mocks.** A mocked race proves that the mock
was written to agree with the code. These tests open concurrent database
connections and let Postgres arbitrate, which is the only arrangement that can
fail if the constraint is dropped.

If any test here starts failing after a change to `scheduling/models.py` or its
migration, the change is wrong. This is the single most expensive bug this
product can ship: two clients arrive for the same chair at the same time, one of
them has already paid a deposit, and the shop finds out in front of both.
"""

import threading
from datetime import timedelta

import pytest
from django.db import connection, connections, transaction

from scheduling.availability import Policy, is_bookable_start
from scheduling.booking import (
    SlotTaken,
    SlotUnavailable,
    create_appointment,
    slot_taken_on_conflict,
)
from scheduling.cache import facts_for_staff_day
from scheduling.models import NO_OVERLAP_CONSTRAINT, Appointment
from scheduling.statuses import ACTIVE_STATUSES, AppointmentStatus, BookingSource
from scheduling.tests.conftest import eat
from shops.models import Staff

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.loadbearing]


def book(staff, service, when, **kwargs):
    return create_appointment(
        staff=staff,
        service=service,
        starts_at=when,
        source=BookingSource.STAFF,
        now=when - timedelta(hours=2),
        **kwargs,
    )


class TestTwoThreadsOneSlot:
    def test_exactly_one_of_two_simultaneous_confirms_wins(self, shop_setup, wednesday):
        """The scenario from CLAUDE.md §4, run for real."""
        when = eat(wednesday, 10)
        barrier = threading.Barrier(2)
        results = []

        def confirm():
            barrier.wait()  # line both threads up on the same instant
            try:
                results.append(("ok", book(shop_setup.wanjiku, shop_setup.braids, when)))
            except Exception as exc:  # noqa: BLE001 — the type is the assertion
                results.append(("error", exc))
            finally:
                connections.close_all()

        threads = [threading.Thread(target=confirm) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        outcomes = [kind for kind, _ in results]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("error") == 1, results
        assert Appointment.all_objects.filter(staff=shop_setup.wanjiku).count() == 1

    def test_the_loser_raises_SlotTaken_specifically(self, shop_setup, wednesday):
        """CLAUDE.md §4's sentence, reproduced exactly: "*both* pass an
        application-level `if slot_is_free` check".

        The barrier sits **between** the availability check and the insert, not
        before both. That is deliberate and it is the only way to pin this
        outcome. With the barrier at the top of `create_appointment`, whichever
        thread re-derives second usually sees the winner's committed row and
        raises `SlotUnavailable` — a correct and better result, but a different
        one, and which of the two happens depends on query timing. So this test
        drives the same two steps `create_appointment` drives, in the same
        order, and forces the interleaving that leaves only the constraint to
        arbitrate.

        `SlotUnavailable` would be the wrong answer here: the slot *was*
        available when this request checked. Losing a 200ms race and being
        offered something that was never real are different events, and
        collapsing them into one makes both unmeasurable.
        """
        when = eat(wednesday, 11)
        duration = shop_setup.braids.duration_minutes
        barrier = threading.Barrier(2)
        errors = []

        def confirm():
            staff = Staff.all_objects.get(pk=shop_setup.wanjiku.pk)
            facts = facts_for_staff_day(staff, wednesday, use_cache=False)
            assert is_bookable_start(
                facts,
                starts_at=when,
                duration_minutes=duration,
                policy=Policy.for_staff(),
                now=when - timedelta(hours=2),
            ), "both threads must pass the application-level check"

            barrier.wait()  # ... and only now does either of them write
            try:
                with slot_taken_on_conflict(starts_at=when, staff=staff):
                    with transaction.atomic():
                        Appointment(
                            shop=staff.shop,
                            staff=staff,
                            service=shop_setup.braids,
                            time_range=(when, when + timedelta(minutes=duration)),
                            status=AppointmentStatus.CONFIRMED,
                            source=BookingSource.STAFF,
                            price_snapshot=3500,
                            deposit_snapshot=875,
                            duration_snapshot=duration,
                        ).save()
            except Exception as exc:  # noqa: BLE001 — the type is the assertion
                errors.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=confirm) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert len(errors) == 1, errors
        assert isinstance(errors[0], SlotTaken), f"got {type(errors[0]).__name__}: {errors[0]}"
        assert not isinstance(errors[0], SlotUnavailable)
        assert Appointment.all_objects.filter(staff=shop_setup.wanjiku).count() == 1

    def test_ten_threads_still_produce_one_appointment(self, shop_setup, wednesday):
        """Two threads can pass by luck of scheduling. Ten cannot."""
        when = eat(wednesday, 12)
        barrier = threading.Barrier(10)
        outcomes = []

        def confirm():
            barrier.wait()
            try:
                book(shop_setup.wanjiku, shop_setup.braids, when)
                outcomes.append("ok")
            except (SlotTaken, SlotUnavailable) as exc:
                outcomes.append(type(exc).__name__)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=confirm) for _ in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert outcomes.count("ok") == 1, outcomes
        assert Appointment.all_objects.filter(staff=shop_setup.wanjiku).count() == 1
        # Everyone else lost cleanly — no unhandled exception type got through.
        assert set(outcomes) <= {"ok", "SlotTaken", "SlotUnavailable"}

    def test_two_staff_at_the_same_time_do_not_collide(self, shop_setup, wednesday):
        """The constraint is scoped to one staff member. A shop with two chairs
        must be able to run both at once."""
        when = eat(wednesday, 13)
        barrier = threading.Barrier(2)
        outcomes = []

        def confirm(staff):
            barrier.wait()
            try:
                book(staff, shop_setup.braids, when)
                outcomes.append("ok")
            except Exception as exc:  # noqa: BLE001
                outcomes.append(exc)
            finally:
                connections.close_all()

        threads = [
            threading.Thread(target=confirm, args=(shop_setup.wanjiku,)),
            threading.Thread(target=confirm, args=(shop_setup.grace,)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert outcomes == ["ok", "ok"], outcomes


class TestTheConstraintItself:
    """Below the service function: the database refuses the overlap on its own,
    with no application code involved."""

    def make(self, shop_setup, start_hour, end_hour, status=AppointmentStatus.CONFIRMED):
        return Appointment.objects.create(
            shop=shop_setup.shop,
            staff=shop_setup.wanjiku,
            service=shop_setup.braids,
            time_range=(eat(self.day, start_hour), eat(self.day, end_hour)),
            status=status,
            source=BookingSource.STAFF,
            price_snapshot=3500,
            deposit_snapshot=875,
            duration_snapshot=(end_hour - start_hour) * 60,
        )

    @pytest.fixture(autouse=True)
    def _day(self, wednesday):
        self.day = wednesday

    def test_a_straddling_overlap_is_refused(self, shop_setup):
        self.make(shop_setup, 10, 12)

        from django.db.utils import IntegrityError

        with pytest.raises(IntegrityError):
            self.make(shop_setup, 11, 13)

    def test_a_contained_overlap_is_refused(self, shop_setup):
        self.make(shop_setup, 10, 14)

        from django.db.utils import IntegrityError

        with pytest.raises(IntegrityError):
            self.make(shop_setup, 11, 12)

    def test_touching_ranges_are_allowed(self, shop_setup):
        """`[)` bounds. Back-to-back appointments are the normal case."""
        self.make(shop_setup, 10, 11)
        self.make(shop_setup, 11, 12)

        assert Appointment.all_objects.count() == 2

    def test_a_cancelled_appointment_frees_its_slot(self, shop_setup):
        """Immediately, and at the database — which is what makes the reschedule
        in slice 7 a single write rather than a two-phase dance."""
        first = self.make(shop_setup, 10, 12)
        first.status = AppointmentStatus.CANCELLED
        first.save(update_fields=["status"])

        self.make(shop_setup, 10, 12)  # must not raise

        assert Appointment.all_objects.filter(status=AppointmentStatus.CONFIRMED).count() == 1

    def test_a_no_show_frees_its_slot(self, shop_setup):
        """The chair is empty. A walk-in should be able to take it."""
        first = self.make(shop_setup, 14, 16)
        first.status = AppointmentStatus.NO_SHOW
        first.save(update_fields=["status"])

        self.make(shop_setup, 14, 16)  # must not raise

    def test_a_pending_payment_hold_blocks_the_slot(self, shop_setup):
        """The whole point of the hold. Slice 6 releases it on TTL expiry."""
        self.make(shop_setup, 10, 12, status=AppointmentStatus.PENDING_PAYMENT)

        from django.db.utils import IntegrityError

        with pytest.raises(IntegrityError):
            self.make(shop_setup, 10, 12)

    def test_the_constraint_exists_in_the_database(self, shop_setup):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT conname FROM pg_constraint WHERE conname = %s", [NO_OVERLAP_CONSTRAINT]
            )
            assert cursor.fetchone(), (
                f"{NO_OVERLAP_CONSTRAINT} is missing. CLAUDE.md §4: the constraint stays "
                "regardless of what else is added."
            )

    def test_the_constraints_status_set_still_matches_the_shared_constant(self):
        """The migration freezes the status literals, so this asserts the frozen
        copy still agrees with `scheduling/statuses.py`. Without it, adding a
        status to ACTIVE_STATUSES would silently leave the database enforcing
        the old set."""
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = %s",
                [NO_OVERLAP_CONSTRAINT],
            )
            definition = cursor.fetchone()[0]

        for status in ACTIVE_STATUSES:
            assert f"'{status}'" in definition, f"{status} is in ACTIVE_STATUSES but not the DB"
        for status in (AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW):
            assert f"'{status}'" not in definition


class TestOnlyOverlapsBecomeSlotTaken:
    """The wrapper matches one constraint by name.

    Rendering every IntegrityError as "slot just taken" would make a null
    violation, a broken foreign key and a bad snapshot all invisible — reported
    to the client as bad luck and to us as nothing at all.
    """

    def test_an_unrelated_integrity_error_is_not_swallowed(self, shop_setup, wednesday):
        from django.db.utils import IntegrityError

        from scheduling.booking import slot_taken_on_conflict

        with pytest.raises(IntegrityError):
            with slot_taken_on_conflict():
                Appointment.objects.create(
                    shop=shop_setup.shop,
                    staff=shop_setup.wanjiku,
                    service=shop_setup.braids,
                    time_range=(eat(wednesday, 10), eat(wednesday, 11)),
                    status=AppointmentStatus.CONFIRMED,
                    source=BookingSource.STAFF,
                    price_snapshot=100,
                    deposit_snapshot=500,  # violates appointment_deposit_within_price
                    duration_snapshot=60,
                )

    def test_an_overlap_does_become_SlotTaken(self, shop_setup, wednesday):
        from scheduling.booking import slot_taken_on_conflict

        common = {
            "shop": shop_setup.shop,
            "staff": shop_setup.wanjiku,
            "service": shop_setup.braids,
            "status": AppointmentStatus.CONFIRMED,
            "source": BookingSource.STAFF,
            "price_snapshot": 3500,
            "deposit_snapshot": 875,
            "duration_snapshot": 60,
        }
        Appointment.objects.create(time_range=(eat(wednesday, 10), eat(wednesday, 11)), **common)

        with pytest.raises(SlotTaken):
            with slot_taken_on_conflict():
                Appointment.objects.create(
                    time_range=(eat(wednesday, 10), eat(wednesday, 11)), **common
                )
