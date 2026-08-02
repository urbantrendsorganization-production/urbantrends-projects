"""LOAD-BEARING. Status transitions, and the undo that is not guaranteed.

Two things here protect decisions rather than implementations, which is why the
file is named explicitly in CI.

1. **Every staff transition is reversible.** No-show feeds the metric that sells
   this product to the next shop (CLAUDE.md §7). A one-tap destructive action
   that needs an owner to undo is a one-tap action nobody uses, and the
   no-show rate stops being a fact about the shop.
2. **Re-entering an active status re-enters the exclusion constraint.** Marking
   a no-show genuinely frees the chair. Undoing it two minutes later can be
   refused by the database, and that refusal must arrive as `SlotTaken` with
   the appointment that took the slot — not as a 500, and never as a silent
   no-op that leaves the staff member believing the client is back on the list.
"""

from datetime import timedelta

import pytest

from scheduling.booking import SlotTaken, create_appointment
from scheduling.models import Appointment
from scheduling.statuses import ACTIVE_STATUSES, AppointmentStatus, BookingSource
from scheduling.tests.conftest import eat
from scheduling.transitions import (
    STAFF_TRANSITIONS,
    TransitionRefused,
    apply_transition,
    blocking_appointment_for,
    undo_target,
)

pytestmark = [pytest.mark.django_db, pytest.mark.loadbearing]

S = AppointmentStatus


@pytest.fixture
def booking(shop_setup, wednesday):
    """A four-hour braid at 10:00, confirmed."""
    return create_appointment(
        staff=shop_setup.wanjiku,
        service=shop_setup.braids,
        starts_at=eat(wednesday, 10),
        source=BookingSource.STAFF,
        now=eat(wednesday, 8),
    )


class TestTheDayRunsForward:
    def test_start_stamps_the_time_and_leaves_the_range_alone(self, booking, wednesday):
        apply_transition(booking, S.IN_PROGRESS, now=eat(wednesday, 10, 4))

        assert booking.status == S.IN_PROGRESS
        assert booking.started_at == eat(wednesday, 10, 4)
        assert booking.ends_at == eat(wednesday, 14)

    def test_finishing_early_frees_the_chair(self, booking, wednesday):
        """The reason the range is trimmed rather than left at what was booked.

        A client who leaves at 11:00 from a booking that ran to 14:00 has given
        the chair back, and a walk-in should be able to have it. Leaving the
        range alone would block three hours that are physically empty.
        """
        apply_transition(booking, S.IN_PROGRESS, now=eat(wednesday, 10))
        apply_transition(booking, S.COMPLETED, now=eat(wednesday, 11))

        assert booking.ends_at == eat(wednesday, 11)
        assert booking.finished_at == eat(wednesday, 11)
        # And what was *booked* survives, because reports read the snapshot.
        assert booking.duration_snapshot == 240
        assert booking.booked_ends_at == eat(wednesday, 14)

    def test_finishing_late_does_not_lengthen_it(self, booking, wednesday):
        """Overrunning must not rewrite the record over the next client's time.
        `finished_at` still tells the truth."""
        apply_transition(booking, S.IN_PROGRESS, now=eat(wednesday, 10))
        apply_transition(booking, S.COMPLETED, now=eat(wednesday, 15))

        assert booking.ends_at == eat(wednesday, 14)
        assert booking.finished_at == eat(wednesday, 15)

    def test_a_freed_chair_can_be_walked_into(self, shop_setup, booking, wednesday):
        apply_transition(booking, S.IN_PROGRESS, now=eat(wednesday, 10))
        apply_transition(booking, S.COMPLETED, now=eat(wednesday, 11))

        walk_in = create_appointment(
            staff=shop_setup.wanjiku,
            service=shop_setup.shave,
            starts_at=eat(wednesday, 11),
            source=BookingSource.WALK_IN,
            now=eat(wednesday, 11),
        )

        assert walk_in.pk

    def test_finishing_in_the_same_second_keeps_a_non_empty_range(self, booking, wednesday):
        """`appointment_range_not_empty` would refuse a zero-length range, and a
        mis-tapped Start followed straight by Finish is an ordinary accident."""
        apply_transition(booking, S.IN_PROGRESS, now=eat(wednesday, 10))
        apply_transition(booking, S.COMPLETED, now=eat(wednesday, 10))

        assert booking.ends_at > booking.starts_at


class TestWaitingIsNotASeventhStatus:
    def test_a_waiting_walk_in_is_confirmed_with_no_start(self, shop_setup, wednesday):
        appointment = create_appointment(
            staff=shop_setup.wanjiku,
            service=shop_setup.shave,
            starts_at=eat(wednesday, 11),
            source=BookingSource.WALK_IN,
            status=S.CONFIRMED,
            now=eat(wednesday, 11),
        )

        assert appointment.is_waiting
        assert appointment.started_at is None
        # And it holds the chair, which is the whole point of writing the row.
        assert appointment.status in ACTIVE_STATUSES

    def test_starting_it_stops_it_waiting(self, shop_setup, wednesday):
        appointment = create_appointment(
            staff=shop_setup.wanjiku,
            service=shop_setup.shave,
            starts_at=eat(wednesday, 11),
            source=BookingSource.WALK_IN,
            status=S.CONFIRMED,
            now=eat(wednesday, 11),
        )

        apply_transition(appointment, S.IN_PROGRESS, now=eat(wednesday, 11, 6))

        assert not appointment.is_waiting

    def test_the_status_set_is_still_six(self):
        """The migration-free claim in transitions.py, asserted. A seventh
        status would mean altering the tuple the exclusion constraint filters
        on."""
        assert len(AppointmentStatus.choices) == 6


class TestUndo:
    def test_no_show_is_reversible(self, booking, wednesday):
        apply_transition(booking, S.NO_SHOW, now=eat(wednesday, 11, 5))
        assert undo_target(booking) == S.CONFIRMED

        apply_transition(booking, S.CONFIRMED, now=eat(wednesday, 11, 7))

        assert booking.status == S.CONFIRMED
        assert booking.ends_at == eat(wednesday, 14)

    def test_undoing_a_finish_goes_back_to_in_progress(self, booking, wednesday):
        apply_transition(booking, S.IN_PROGRESS, now=eat(wednesday, 10))
        apply_transition(booking, S.COMPLETED, now=eat(wednesday, 11))

        assert undo_target(booking) == S.IN_PROGRESS
        apply_transition(booking, S.IN_PROGRESS, now=eat(wednesday, 11, 1))

        assert booking.ends_at == eat(wednesday, 14)  # the booked range is back
        assert booking.finished_at is None
        assert booking.started_at == eat(wednesday, 10)  # the client arrived once

    def test_undoing_a_finish_that_was_never_started_goes_to_confirmed(self, booking, wednesday):
        apply_transition(booking, S.COMPLETED, now=eat(wednesday, 11))

        assert undo_target(booking) == S.CONFIRMED

    def test_a_confirmed_booking_has_nothing_to_undo(self, booking):
        assert undo_target(booking) is None

    def test_every_reachable_status_can_be_left_again(self):
        """The rule, asserted over the table rather than case by case: there is
        no state a staff member can tap themselves into and not out of."""
        dead_ends = [
            status
            for status, targets in STAFF_TRANSITIONS.items()
            if not targets and status != S.PENDING_PAYMENT
        ]

        assert not dead_ends, dead_ends


class TestUndoIsNotGuaranteed:
    def test_the_chair_can_be_gone(self, shop_setup, booking, wednesday):
        """11:05 no-show, 11:07 the client walks in — and in between, somebody
        took the chair. The exclusion constraint refuses the undo, and it must
        arrive as SlotTaken."""
        apply_transition(booking, S.NO_SHOW, now=eat(wednesday, 11, 5))
        create_appointment(
            staff=shop_setup.wanjiku,
            service=shop_setup.shave,
            starts_at=eat(wednesday, 11, 6),
            source=BookingSource.WALK_IN,
            now=eat(wednesday, 11, 6),
        )

        with pytest.raises(SlotTaken):
            apply_transition(booking, S.CONFIRMED, now=eat(wednesday, 11, 7))

    def test_the_refusal_names_what_took_it(self, shop_setup, booking, wednesday):
        """Because the staff member is looking at two real people and has to
        know which one has the chair."""
        apply_transition(booking, S.NO_SHOW, now=eat(wednesday, 11, 5))
        walk_in = create_appointment(
            staff=shop_setup.wanjiku,
            service=shop_setup.shave,
            starts_at=eat(wednesday, 11, 6),
            source=BookingSource.WALK_IN,
            now=eat(wednesday, 11, 6),
        )

        blocker = blocking_appointment_for(booking)

        assert blocker is not None
        assert blocker.id == walk_in.id

    def test_a_failed_undo_leaves_the_row_as_it_was(self, shop_setup, booking, wednesday):
        """No half-applied transition. The row is still a no-show in the
        database, so a refresh shows the truth rather than a status that only
        exists in one process's memory."""
        apply_transition(booking, S.NO_SHOW, now=eat(wednesday, 11, 5))
        create_appointment(
            staff=shop_setup.wanjiku,
            service=shop_setup.shave,
            starts_at=eat(wednesday, 11, 6),
            source=BookingSource.WALK_IN,
            now=eat(wednesday, 11, 6),
        )

        with pytest.raises(SlotTaken):
            apply_transition(booking, S.CONFIRMED, now=eat(wednesday, 11, 7))

        assert Appointment.all_objects.get(pk=booking.pk).status == S.NO_SHOW

    def test_undo_succeeds_when_nothing_took_it(self, booking, wednesday):
        apply_transition(booking, S.NO_SHOW, now=eat(wednesday, 11, 5))
        apply_transition(booking, S.CONFIRMED, now=eat(wednesday, 11, 7))

        assert booking.status == S.CONFIRMED
        assert blocking_appointment_for(booking) is None


class TestTheTableIsTheOnlyAuthority:
    def test_an_illegal_move_is_refused_by_name(self, booking):
        with pytest.raises(TransitionRefused):
            apply_transition(booking, S.PENDING_PAYMENT)

    def test_a_cancelled_booking_cannot_be_finished(self, booking, wednesday):
        apply_transition(booking, S.CANCELLED, now=eat(wednesday, 10))

        with pytest.raises(TransitionRefused):
            apply_transition(booking, S.COMPLETED, now=eat(wednesday, 11))

    def test_staff_cannot_confirm_an_unpaid_hold(self, shop_setup, wednesday):
        """CLAUDE.md §5: without a payment there is no phone verification. A
        staff member confirming a pending_payment row by hand would hand out
        exactly the deposit-free booking the rule exists to prevent."""
        online = create_appointment(
            staff=shop_setup.wanjiku,
            service=shop_setup.braids,
            starts_at=eat(wednesday, 10),
            source=BookingSource.ONLINE,
            now=eat(wednesday, 8),
        )
        assert online.status == S.PENDING_PAYMENT

        with pytest.raises(TransitionRefused):
            apply_transition(online, S.CONFIRMED)

    def test_a_repeated_tap_is_idempotent(self, booking, wednesday):
        """Bad connection, nothing appears to happen, they tap again. The second
        tap must not re-stamp `started_at` to a later time."""
        apply_transition(booking, S.IN_PROGRESS, now=eat(wednesday, 10, 4))
        apply_transition(booking, S.IN_PROGRESS, now=eat(wednesday, 10, 9))

        assert booking.started_at == eat(wednesday, 10, 4)


class TestReleasedStatusesFreeTheSlot:
    @pytest.mark.parametrize("released", [S.NO_SHOW, S.CANCELLED])
    def test_the_chair_is_available_again(self, shop_setup, booking, wednesday, released):
        apply_transition(booking, released, now=eat(wednesday, 10, 5))

        replacement = create_appointment(
            staff=shop_setup.wanjiku,
            service=shop_setup.shave,
            starts_at=eat(wednesday, 10, 30),
            source=BookingSource.WALK_IN,
            now=eat(wednesday, 10, 30),
        )

        assert replacement.pk

    def test_a_completed_appointment_does_not_free_its_worked_time(
        self, shop_setup, booking, wednesday
    ):
        """The other half of the ACTIVE/BLOCKING divergence. The engine will not
        offer worked time even though the database would accept the row."""
        apply_transition(booking, S.IN_PROGRESS, now=eat(wednesday, 10))
        apply_transition(booking, S.COMPLETED, now=eat(wednesday, 14))

        from scheduling.booking import SlotUnavailable

        with pytest.raises(SlotUnavailable):
            create_appointment(
                staff=shop_setup.wanjiku,
                service=shop_setup.shave,
                starts_at=eat(wednesday, 12),
                source=BookingSource.WALK_IN,
                now=eat(wednesday, 12),
            )

    def test_no_show_keeps_the_timestamps_it_had(self, booking, wednesday):
        """A client who started and walked out mid-service is real, and
        `started_at` is the only record that the chair was occupied at all."""
        apply_transition(booking, S.IN_PROGRESS, now=eat(wednesday, 10))
        apply_transition(booking, S.NO_SHOW, now=eat(wednesday, 10, 30))

        assert booking.started_at == eat(wednesday, 10)


class TestInvalidation:
    def test_a_transition_drops_the_cached_day(self, shop_setup, booking, wednesday, clear_cache):
        from django.core.cache import cache

        from scheduling.cache import facts_for_staff_day, key_for

        facts_for_staff_day(shop_setup.wanjiku, wednesday)
        assert cache.get(key_for(shop_setup.wanjiku.id, wednesday)) is not None

        apply_transition(booking, S.NO_SHOW, now=eat(wednesday, 11))

        assert cache.get(key_for(shop_setup.wanjiku.id, wednesday)) is None

    def test_a_trimmed_finish_shows_up_in_the_facts(self, shop_setup, booking, wednesday):
        from scheduling.cache import facts_for_staff_day

        apply_transition(booking, S.IN_PROGRESS, now=eat(wednesday, 10))
        apply_transition(booking, S.COMPLETED, now=eat(wednesday, 11))

        facts = facts_for_staff_day(shop_setup.wanjiku, wednesday)

        assert len(facts.busy) == 1
        assert facts.busy[0].ends_at == eat(wednesday, 11)
        # Completed, so it blocks the offer and not the write.
        assert facts.busy[0].is_active is False


def test_an_appointment_that_crosses_local_midnight_is_busy_on_both_days(shop_setup):
    """Staff writes ignore opening hours, so slice 4 makes an overnight span
    reachable for the first time — see availability.py decision (e). It is not
    *offerable*, but it must be *visible*, or the next morning shows a free
    chair that has somebody in it."""
    from datetime import date

    from scheduling.cache import facts_for_staff_day

    day = date(2026, 9, 9)
    # A four-hour braid begun at 23:30 runs to 03:30 the next EAT day. A
    # twenty-minute shave would not cross, and would have made this pass
    # vacuously.
    late = eat(day, 23, 30)
    create_appointment(
        staff=shop_setup.wanjiku,
        service=shop_setup.braids,
        starts_at=late,
        source=BookingSource.WALK_IN,
        now=late,
    )

    today = facts_for_staff_day(shop_setup.wanjiku, day)
    tomorrow = facts_for_staff_day(shop_setup.wanjiku, day + timedelta(days=1))

    assert len(today.busy) == 1
    assert len(tomorrow.busy) == 1
