"""Cancel, reschedule, and the one-way latch between them.

CLAUDE.md §12's refund policy and §8's "one booking, one move, no knock-on".

The boundary tests are exact on purpose. A client cancelling at 24 hours and one
minute gets their money back; one cancelling at 23 hours and 59 minutes gets
credit. That is a real difference to a real person, it is decided by an
inequality, and an off-by-one there is the kind of thing nobody notices until a
shop is arguing with a client about it.
"""

from datetime import timedelta

import pytest

from payments.credit import Credit, CreditState
from payments.states import PaymentState
from scheduling.holds import create_hold
from scheduling.lifecycle import (
    MAX_RESCHEDULES,
    NotManageable,
    Outcome,
    RescheduleRefused,
    cancel,
    is_forfeited,
    outcome_for,
    reschedule,
)
from scheduling.statuses import AppointmentStatus
from scheduling.tests.conftest import WEDNESDAY, eat

pytestmark = pytest.mark.django_db

S = AppointmentStatus


def booking_at(shop_setup, hour, *, now, phone="0712345678", staff=None):
    return create_hold(
        shop=shop_setup.shop,
        service=shop_setup.braids,
        staff=staff or shop_setup.wanjiku,
        starts_at=eat(WEDNESDAY, hour),
        phone=phone,
        now=now,
    )


def pay(appointment, *, now=None):
    """Take the deposit for real, through the callback the shop would get."""
    from payments.callbacks import handle_callback
    from payments.stk import initiate_push
    from payments.tests.conftest import stk_callback

    payment = initiate_push(appointment, now=now)
    handle_callback(stk_callback(payment.checkout_request_id), now=now)
    appointment.refresh_from_db()
    payment.refresh_from_db()
    return payment


@pytest.fixture
def paid(shop_setup):
    """A confirmed, paid booking at 10:00 on the fixed Wednesday."""
    appointment = booking_at(shop_setup, 10, now=eat(WEDNESDAY, 10) - timedelta(days=3))
    pay(appointment, now=eat(WEDNESDAY, 10) - timedelta(days=3))
    appointment.refresh_from_db()
    return appointment


# ------------------------------------------------------------ the boundary


class TestTheRefundBoundary:
    """24 hours, ± a minute. `refund_window_hours` defaults to 24."""

    def test_a_minute_outside_the_window_is_a_refund(self, paid):
        one_minute_early = paid.starts_at - timedelta(hours=24, minutes=1)

        outcome, amount = outcome_for(paid, now=one_minute_early)

        assert outcome == Outcome.REFUND
        assert amount == 875

    def test_a_minute_inside_the_window_is_credit(self, paid):
        one_minute_late = paid.starts_at - timedelta(hours=23, minutes=59)

        outcome, amount = outcome_for(paid, now=one_minute_late)

        assert outcome == Outcome.CREDIT
        assert amount == 875

    def test_exactly_on_the_boundary_is_credit(self, paid):
        """`<=` not `<`. Somebody has to own the exact instant, and giving it to
        the shop's side of the line means the client who was told "more than 24
        hours" gets what they were told."""
        exactly = paid.starts_at - timedelta(hours=24)

        outcome, _ = outcome_for(paid, now=exactly)

        assert outcome == Outcome.CREDIT

    def test_a_shop_cancellation_refunds_whenever_it_happens(self, paid):
        """Unconditional and not shop-configurable — §12. A client cannot lose a
        deposit to a cancellation they did not make."""
        five_minutes_before = paid.starts_at - timedelta(minutes=5)

        outcome, amount = outcome_for(paid, now=five_minutes_before, shop_cancelled=True)

        assert outcome == Outcome.REFUND
        assert amount == 875

    def test_an_unpaid_hold_owes_nothing(self, shop_setup):
        held = booking_at(shop_setup, 14, now=eat(WEDNESDAY, 10))

        outcome, amount = outcome_for(held, now=eat(WEDNESDAY, 10))

        assert outcome == Outcome.NOTHING
        assert amount == 0


class TestCancelling:
    def test_an_early_cancel_records_a_refund_due(self, paid):
        early = paid.starts_at - timedelta(days=2)

        outcome, amount, credit = cancel(paid, now=early)

        paid.refresh_from_db()
        assert outcome == Outcome.REFUND
        assert credit is None
        assert paid.status == S.CANCELLED
        # Recorded, not sent: the deposit is in the shop's paybill and only they
        # can move it. This puts the row in front of a human.
        payment = paid.payments.filter(state=PaymentState.SUCCEEDED).first()
        assert payment.refund_due_at is not None
        assert amount == 875

    def test_a_late_cancel_issues_credit_and_no_refund_due(self, paid):
        late = paid.starts_at - timedelta(hours=2)

        outcome, amount, credit = cancel(paid, now=late)

        assert outcome == Outcome.CREDIT
        assert credit is not None
        assert credit.amount_kes == amount == 875
        assert credit.remaining_kes == 875
        assert credit.shop_id == paid.shop_id
        assert credit.client_id == paid.client_id
        payment = paid.payments.filter(state=PaymentState.SUCCEEDED).first()
        assert payment.refund_due_at is None, "credit resolves itself; nothing is owed back"

    def test_the_credit_expires_on_the_shops_own_window(self, paid, shop_setup):
        shop_setup.shop.deposit_credit_days = 90
        shop_setup.shop.save(update_fields=["deposit_credit_days"])
        paid.refresh_from_db()
        late = paid.starts_at - timedelta(hours=2)

        _, _, credit = cancel(paid, now=late)

        assert (credit.expires_at - late).days == 90

    def test_a_started_booking_cannot_be_cancelled(self, paid):
        from scheduling.transitions import apply_transition

        apply_transition(paid, S.IN_PROGRESS, now=paid.starts_at)

        with pytest.raises(NotManageable):
            cancel(paid, now=paid.starts_at)


# ------------------------------------------------------------- the latch


class TestTheOneWayLatch:
    """The reschedule-to-dodge-a-forfeit hole, and its plug."""

    def test_moving_out_of_the_window_does_not_restore_a_refund(self, paid, shop_setup):
        """The dodge, closed. Inside the window a cancel yields credit; moving
        the booking six weeks out must not turn that back into cash."""
        inside = paid.starts_at - timedelta(hours=2)

        # Move it far out — legitimately allowed.
        reschedule(paid, starts_at=eat(WEDNESDAY, 12) + timedelta(days=28), now=inside)
        paid.refresh_from_db()

        assert paid.entered_refund_window_at is not None
        outcome, amount = outcome_for(paid, now=inside)
        assert outcome == Outcome.CREDIT
        assert amount == 875

    def test_moving_into_the_window_latches_immediately(self, paid, shop_setup):
        """A client who takes a slot three hours away has knowingly taken a
        tight one. The move is allowed and refundability goes with it."""
        far_out = booking_at(
            shop_setup,
            10,
            now=eat(WEDNESDAY, 10) - timedelta(days=10),
            phone="0722000000",
            staff=shop_setup.grace,
        )
        pay(far_out, now=eat(WEDNESDAY, 10) - timedelta(days=10))
        far_out.refresh_from_db()
        well_before = far_out.starts_at - timedelta(days=5)
        assert outcome_for(far_out, now=well_before)[0] == Outcome.REFUND

        # Now move it to three hours from "now".
        three_hours_out = eat(WEDNESDAY, 12)
        reschedule(
            far_out,
            starts_at=three_hours_out,
            staff=shop_setup.grace,
            now=three_hours_out - timedelta(hours=3),
        )
        far_out.refresh_from_db()

        assert far_out.entered_refund_window_at is not None
        assert outcome_for(far_out, now=three_hours_out - timedelta(hours=3))[0] == Outcome.CREDIT

    def test_a_booking_that_was_never_late_still_refunds(self, paid):
        """The latch must not fire on bookings that never entered the window."""
        well_before = paid.starts_at - timedelta(days=2)

        reschedule(paid, starts_at=eat(WEDNESDAY, 12), now=well_before)
        paid.refresh_from_db()

        assert paid.entered_refund_window_at is None
        assert outcome_for(paid, now=well_before)[0] == Outcome.REFUND

    def test_the_stamp_is_never_cleared(self, paid):
        inside = paid.starts_at - timedelta(hours=2)
        reschedule(paid, starts_at=eat(WEDNESDAY, 12) + timedelta(days=28), now=inside)
        paid.refresh_from_db()
        first = paid.entered_refund_window_at

        # A second move, well outside the window this time.
        reschedule(paid, starts_at=eat(WEDNESDAY, 12) + timedelta(days=30), now=inside)
        paid.refresh_from_db()

        assert paid.entered_refund_window_at == first


# --------------------------------------------------------- rescheduling


class TestRescheduling:
    def test_the_deposit_comes_with_it(self, paid):
        """The same row, so `Payment.appointment` still points where it did. No
        money is re-pointed, re-pushed or re-verified."""
        payment = paid.payments.filter(state=PaymentState.SUCCEEDED).first()
        before = paid.starts_at

        reschedule(paid, starts_at=eat(WEDNESDAY, 12), now=before - timedelta(days=2))
        paid.refresh_from_db()
        payment.refresh_from_db()

        assert paid.starts_at == eat(WEDNESDAY, 12)
        assert payment.appointment_id == paid.pk
        assert paid.status == S.CONFIRMED

    def test_the_move_counter_bounds_it(self, paid):
        """§8, as amended at slice 7. Every move invalidates a stylist's day."""
        when = paid.starts_at - timedelta(days=2)
        hours = [12, 13, 9]
        for hour in hours[:MAX_RESCHEDULES]:
            reschedule(paid, starts_at=eat(WEDNESDAY, hour), now=when)
            paid.refresh_from_db()

        assert paid.reschedule_count == MAX_RESCHEDULES
        with pytest.raises(RescheduleRefused) as exc:
            reschedule(paid, starts_at=eat(WEDNESDAY, 14), now=when)
        assert exc.value.reason == "too_many_moves"

    def test_a_capped_booking_can_still_be_cancelled(self, paid):
        """Refusing the move must never trap somebody. Cancel still works, and
        now yields credit rather than nothing."""
        when = paid.starts_at - timedelta(days=2)
        for hour in [12, 13, 9][:MAX_RESCHEDULES]:
            reschedule(paid, starts_at=eat(WEDNESDAY, hour), now=when)
            paid.refresh_from_db()

        outcome, amount, _ = cancel(paid, now=when)

        assert outcome == Outcome.REFUND
        assert amount == 875

    def test_a_move_into_the_past_is_refused(self, paid):
        with pytest.raises(RescheduleRefused) as exc:
            reschedule(paid, starts_at=eat(WEDNESDAY, 9), now=eat(WEDNESDAY, 16))
        assert exc.value.reason == "in_the_past"

    def test_a_cancelled_booking_cannot_be_moved(self, paid):
        when = paid.starts_at - timedelta(days=2)
        cancel(paid, now=when)
        paid.refresh_from_db()

        with pytest.raises(RescheduleRefused) as exc:
            reschedule(paid, starts_at=eat(WEDNESDAY, 12), now=when)
        assert exc.value.reason == "not_movable"

    def test_it_does_not_block_itself(self, paid):
        """The booking being moved is excluded from the availability check.
        Without it a client moving 10:00 to 11:00 on the same day is blocked by
        the very booking that is about to vacate 10:00."""
        when = paid.starts_at - timedelta(days=2)

        reschedule(paid, starts_at=eat(WEDNESDAY, 12), now=when)
        paid.refresh_from_db()

        assert paid.starts_at == eat(WEDNESDAY, 12)


class TestARescheduleRacingAWalkIn:
    def test_the_walk_in_wins_and_the_client_is_told_to_pick_again(self, paid, shop_setup):
        """The exclusion constraint decides, not the Python check above it.

        A staff member recording a walk-in into the target slot between the
        availability read and the write is exactly the race CLAUDE.md §4 says
        the database must settle — and walk-ins are the majority of Kenyan
        salon traffic, so this is not a rare case.
        """
        from scheduling.booking import SlotTaken, create_appointment
        from scheduling.statuses import BookingSource

        when = paid.starts_at - timedelta(days=2)
        # 14:00, because `paid` itself runs 10:00-14:00 and everything inside
        # that is its own slot rather than a contested one.
        target = eat(WEDNESDAY, 14)

        # The walk-in lands first, on the same stylist, over the target slot.
        # A shave rather than braids: it only has to *occupy* the start.
        create_appointment(
            staff=shop_setup.wanjiku,
            service=shop_setup.shave,
            starts_at=target,
            source=BookingSource.WALK_IN,
            now=target,
        )

        with pytest.raises((RescheduleRefused, SlotTaken)):
            reschedule(paid, starts_at=target, now=when)

        paid.refresh_from_db()
        assert paid.starts_at == eat(WEDNESDAY, 10), "the original booking is untouched"
        assert paid.status == S.CONFIRMED


# ------------------------------------------------------------- the forfeit


class TestTheForfeitDerivation:
    """Still derived, no new state — and narrower now that credit exists."""

    def test_a_no_show_with_a_paid_deposit_is_forfeited(self, paid):
        from scheduling.transitions import apply_transition

        apply_transition(paid, S.NO_SHOW, now=paid.starts_at + timedelta(minutes=20))

        assert is_forfeited(paid)

    def test_a_late_cancellation_is_not_a_forfeit(self, paid):
        """The check that had to change. A late cancel now issues credit, so
        counting it as forfeited would make slice 9's no-show reporting wrong in
        the shop's favour — the direction nobody would notice."""
        cancel(paid, now=paid.starts_at - timedelta(hours=2))
        paid.refresh_from_db()

        assert not is_forfeited(paid)
        assert paid.credits_issued.exists()

    def test_an_unpaid_no_show_forfeits_nothing(self, shop_setup):
        from scheduling.transitions import apply_transition

        held = booking_at(shop_setup, 14, now=eat(WEDNESDAY, 10))
        apply_transition(held, S.CANCELLED, now=eat(WEDNESDAY, 10))

        assert not is_forfeited(held)

    def test_outcome_for_a_no_show_returns_nothing(self, paid):
        from scheduling.transitions import apply_transition

        apply_transition(paid, S.NO_SHOW, now=paid.starts_at + timedelta(minutes=20))

        outcome, amount = outcome_for(paid, now=paid.starts_at + timedelta(minutes=30))

        assert outcome == Outcome.NOTHING
        assert amount == 875, "the figure is still reported; it is simply not coming back"


# ---------------------------------------------------------------- credit


class TestCreditIsSpendable:
    def test_it_comes_off_the_next_deposit(self, paid, shop_setup):
        """Issued on a late cancel, spent on the next booking, automatically."""
        cancel(paid, now=paid.starts_at - timedelta(hours=2))

        again = booking_at(shop_setup, 12, now=eat(WEDNESDAY, 8))
        again.refresh_from_db()

        # The braids deposit is 875 and the credit was 875, so nothing is owed.
        assert again.deposit_snapshot == 0
        assert again.credit_redemptions.count() == 1

    def test_a_credit_covering_the_deposit_confirms_without_a_push(
        self, paid, shop_setup, api_client
    ):
        """CLAUDE.md §5's carve-out. No STK prompt goes out, and the booking is
        still verified — the credit descends from a succeeded payment made from
        this number."""
        from django.urls import reverse

        cancel(paid, now=paid.starts_at - timedelta(hours=2))

        response = api_client.post(
            reverse("public_api:hold-create", args=[shop_setup.shop.slug]),
            {
                "service": str(shop_setup.braids.pk),
                "staff": str(shop_setup.wanjiku.pk),
                "starts_at": eat(WEDNESDAY, 12).isoformat(),
                "phone": "0712345678",
            },
            format="json",
        )

        assert response.status_code == 201
        assert response.data["status"] == S.CONFIRMED
        assert response.data["payment"] is None, "no push was needed"

    def test_a_partial_credit_leaves_the_rest_to_mpesa(self, paid, shop_setup):
        """Credit reduces a deposit; it does not replace the mechanism."""
        cancel(paid, now=paid.starts_at - timedelta(hours=2))
        credit = Credit.objects.unscoped().get()
        credit.remaining_kes = 300
        credit.save(update_fields=["remaining_kes"])

        again = booking_at(shop_setup, 12, now=eat(WEDNESDAY, 8))
        again.refresh_from_db()

        assert again.deposit_snapshot == 875 - 300
        credit.refresh_from_db()
        assert credit.remaining_kes == 0
        assert credit.state == CreditState.SPENT

    def test_an_excess_credit_keeps_its_original_expiry(self, paid, shop_setup):
        """Never extended. Otherwise a 60-day credit becomes a perpetual one for
        anybody willing to make small bookings."""
        cancel(paid, now=paid.starts_at - timedelta(hours=2))
        credit = Credit.objects.unscoped().get()
        credit.amount_kes = credit.remaining_kes = 5000
        credit.save(update_fields=["amount_kes", "remaining_kes"])
        original_expiry = credit.expires_at

        booking_at(shop_setup, 12, now=eat(WEDNESDAY, 8))
        credit.refresh_from_db()

        assert credit.remaining_kes == 5000 - 875
        assert credit.expires_at == original_expiry
        assert credit.state == CreditState.OPEN

    def test_an_expired_credit_is_not_spent(self, paid, shop_setup):
        """The money stays with the shop. §12 promises that and the client was
        told the date on the day it was issued."""
        cancel(paid, now=paid.starts_at - timedelta(hours=2))
        credit = Credit.objects.unscoped().get()
        credit.expires_at = eat(WEDNESDAY, 8) - timedelta(days=1)
        credit.save(update_fields=["expires_at"])

        again = booking_at(shop_setup, 12, now=eat(WEDNESDAY, 8))
        again.refresh_from_db()

        assert again.deposit_snapshot == 875, "the lapsed credit bought nothing"
        assert again.credit_redemptions.count() == 0

    def test_the_sweep_marks_lapsed_credits(self, paid):
        from payments.credit import expire_lapsed

        cancel(paid, now=paid.starts_at - timedelta(hours=2))
        credit = Credit.objects.unscoped().get()
        credit.expires_at = eat(WEDNESDAY, 8) - timedelta(days=1)
        credit.save(update_fields=["expires_at"])

        assert expire_lapsed(now=eat(WEDNESDAY, 8)) == 1
        credit.refresh_from_db()
        assert credit.state == CreditState.EXPIRED

    def test_the_oldest_expiring_credit_is_spent_first(self, paid, shop_setup):
        """Spending the one that dies soonest is what the client would choose;
        anything else quietly forfeits value with a usable balance next to it."""
        cancel(paid, now=paid.starts_at - timedelta(hours=2))
        first = Credit.objects.unscoped().get()
        first.remaining_kes = first.amount_kes = 400
        first.expires_at = eat(WEDNESDAY, 8) + timedelta(days=5)
        first.save(update_fields=["remaining_kes", "amount_kes", "expires_at"])

        second = Credit.objects.create(
            shop=first.shop,
            client=first.client,
            amount_kes=400,
            remaining_kes=400,
            expires_at=eat(WEDNESDAY, 8) + timedelta(days=50),
            reference="CR-SECOND",
        )

        booking_at(shop_setup, 12, now=eat(WEDNESDAY, 8))
        first.refresh_from_db()
        second.refresh_from_db()

        assert first.remaining_kes == 0, "the soonest-expiring credit went first"
        assert second.remaining_kes == 0
