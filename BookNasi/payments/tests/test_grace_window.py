"""LOAD-BEARING. T_grace: the mechanism that shrinks the slotLost population.

The decision on record is that this slice ships the *mechanism* and slice 7
ships the remedy. The mechanism is one sentence: **a hold whose STK push is
still outstanding is not released the instant its TTL runs out.**

Safaricom is often a few seconds late and sometimes a minute late. Releasing at
exactly `hold_expires_at` manufactures the worst state this product has — the
client's money left, the slot went to somebody else, and nobody did anything
wrong. The grace window costs the next client up to two minutes of a slot that
was probably about to be paid for anyway. The alternative costs somebody their
money and their booking.

It is bounded in the strongest available way. `grace_ceiling` is
`hold_expires_at + HOLD_GRACE_MINUTES`, derived and never stored, so it extends
exactly once and no code path can push it out — there is no column to push.

Expiry is simulated the way the slice 5 hold tests do it: by moving
`hold_expires_at` backwards, never by waiting and never by patching the clock.
The Celery tasks read the real clock and compare it to that column, so moving
the column is what actually exercises them.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from payments.callbacks import handle_callback
from payments.states import OrphanReason, PaymentState
from payments.tests.conftest import push_for, stk_callback
from scheduling import tasks
from scheduling.holds import grace_ceiling, hold_is_releasable
from scheduling.models import Appointment
from scheduling.statuses import AppointmentStatus

pytestmark = [pytest.mark.django_db, pytest.mark.loadbearing]

S = AppointmentStatus


def expired_ago(appointment, seconds):
    """Move the hold's expiry into the past. Returns the reloaded appointment."""
    Appointment.all_objects.filter(pk=appointment.pk).update(
        hold_expires_at=timezone.now() - timedelta(seconds=seconds)
    )
    appointment.refresh_from_db()
    return appointment


def past_the_ceiling(appointment, settings):
    return expired_ago(appointment, settings.HOLD_GRACE_MINUTES * 60 + 5)


class TestTheWindowOnlyOpensForAnOutstandingPush:
    def test_a_hold_with_no_push_releases_the_moment_it_expires(self, held):
        """The grace window is for money in flight, not for holds in general.
        A client who never got as far as a prompt gets no extra time."""
        expired_ago(held, 1)

        assert hold_is_releasable(held) is True

    def test_a_hold_with_a_live_push_waits(self, held):
        push_for(held)
        expired_ago(held, 30)

        assert hold_is_releasable(held) is False

    def test_a_hold_whose_push_already_failed_does_not_wait(self, held):
        """`result_code` is set, so there is nothing still to hear about. The
        client is on screen 7 with whatever countdown they have left."""
        payment = push_for(held)
        handle_callback(stk_callback(payment.checkout_request_id, result_code=1032))
        expired_ago(held, 1)

        assert hold_is_releasable(held) is True

    def test_the_window_closes_at_the_ceiling_however_slow_safaricom_is(self, held, settings):
        push_for(held)
        past_the_ceiling(held, settings)

        assert hold_is_releasable(held) is True

    def test_the_ceiling_is_exactly_hold_grace_minutes_past_the_expiry(self, held, settings):
        expected = held.hold_expires_at + timedelta(minutes=settings.HOLD_GRACE_MINUTES)

        assert grace_ceiling(held) == expected


class TestTheSweepRespectsIt:
    def test_the_scheduled_release_declines_while_a_push_is_live(self, held):
        push_for(held)
        expired_ago(held, 30)

        result = tasks.release_expired_hold(str(held.pk))

        held.refresh_from_db()
        assert result == "not-yet"
        assert held.status == S.PENDING_PAYMENT

    def test_the_sweep_leaves_a_waiting_hold_alone(self, held):
        push_for(held)
        expired_ago(held, 30)

        assert tasks.sweep_expired_holds() == 0

        held.refresh_from_db()
        assert held.status == S.PENDING_PAYMENT

    def test_past_the_ceiling_the_sweep_takes_the_slot_back(self, held, settings):
        push_for(held)
        past_the_ceiling(held, settings)

        assert tasks.sweep_expired_holds() == 1

        held.refresh_from_db()
        assert held.status == S.CANCELLED
        assert held.hold_released_at is not None

    def test_the_window_cannot_be_held_open_by_pressing_resend(self, held, settings):
        """A resend supersedes the first push, and a superseded push still
        counts as outstanding — which would be a way to hold a slot forever if
        the ceiling were anything other than derived."""
        settings.STK_RESEND_MIN_INTERVAL_SECONDS = 0
        from payments.stk import resend_push

        push_for(held)
        resend_push(held)
        past_the_ceiling(held, settings)

        assert tasks.sweep_expired_holds() == 1


class TestACallbackArrivingMidGraceWindow:
    """The user's named case, and the one the whole mechanism is for.

    The TTL has run out, the sweep has already looked and declined, and *then*
    the money lands. Nothing has been released, so this is an ordinary
    confirmation — not a late callback, not a race, not a support call.
    """

    def test_it_confirms_without_ever_becoming_a_slot_lost(self, held):
        payment = push_for(held)
        expired_ago(held, 30)
        # The sweep runs first, exactly as Beat would, and leaves it alone.
        tasks.sweep_expired_holds()
        held.refresh_from_db()
        assert held.status == S.PENDING_PAYMENT

        handle_callback(stk_callback(payment.checkout_request_id))

        held.refresh_from_db()
        payment.refresh_from_db()
        assert held.status == S.CONFIRMED
        assert payment.state == PaymentState.SUCCEEDED
        assert payment.orphan_reason == ""

    def test_the_client_never_sees_the_hold_released_message(self, held):
        """Which is the point. Without the window they would get "your hold ran
        out" and then a confirmation, seconds apart, in that order."""
        from notifications.models import Message
        from notifications.templates import Template

        payment = push_for(held)
        expired_ago(held, 30)
        tasks.sweep_expired_holds()

        handle_callback(stk_callback(payment.checkout_request_id))

        sent = set(Message.objects.unscoped().values_list("template", flat=True))
        assert Template.HOLD_RELEASED not in sent
        assert Template.BOOKING_CONFIRMED in sent

    def test_a_callback_after_the_ceiling_is_the_late_case_instead(self, held, settings):
        """The window is a shrinker, not a fix. Past the ceiling the slot is
        genuinely back on offer and the late-callback path takes over — which
        still confirms, as long as nobody took it."""
        payment = push_for(held)
        past_the_ceiling(held, settings)
        tasks.sweep_expired_holds()
        held.refresh_from_db()
        assert held.status == S.CANCELLED

        handle_callback(stk_callback(payment.checkout_request_id))

        held.refresh_from_db()
        assert held.status == S.CONFIRMED

    def test_and_if_somebody_took_it_in_between_that_is_slot_lost(self, shop_setup, held, settings):
        from scheduling.booking import create_appointment
        from scheduling.statuses import BookingSource

        payment = push_for(held)
        past_the_ceiling(held, settings)
        tasks.sweep_expired_holds()
        create_appointment(
            staff=shop_setup.wanjiku,
            service=shop_setup.braids,
            starts_at=held.starts_at,
            source=BookingSource.WALK_IN,
            status=S.CONFIRMED,
            now=held.starts_at,
        )

        handle_callback(stk_callback(payment.checkout_request_id))

        payment.refresh_from_db()
        assert payment.state == PaymentState.ORPHANED
        assert payment.orphan_reason == OrphanReason.SLOT_LOST
