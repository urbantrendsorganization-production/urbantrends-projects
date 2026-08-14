"""Only the lost race earns the "your slot was taken" SMS.

`settle_succeeded` orphans a payment for four different reasons, and three of
them describe a booking that is completely fine:

- `SLOT_LOST` — the money arrived and somebody else had taken the slot. Screen 8,
  a phone call, and the one case the message is written for.
- `ALREADY_PAID` — a resend where the client answered both prompts. The booking
  is confirmed and paid for.
- `BOOKING_CANCELLED` — a payment against a booking the client had already
  killed.
- `BOOKING_MOVED_ON` — a payment against a booking that has already run.

Both settlement paths — the callback and the reconciliation query — used to
branch on "orphaned" alone, so all four sent `SLOT_LOST`. Telling a client "we
received your KES 875, but 10:00 with Wanjiku was taken while the payment was
going through" about a booking that is intact is a worse support call than the
one screen 8 exists for, and the `ONE_SHOT` constraint does not catch it because
the confirmation and the slot-lost notice are different templates.

The shop still hears about every orphan: `_orphan` logs a WARNING and the row
sits in the exception queue. What changes is what the *client* is told.
"""

from datetime import timedelta

import pytest

from notifications.models import Message
from notifications.templates import Template
from payments.states import OrphanReason, PaymentState
from payments.tests.conftest import cancel_deliberately, push_for, stk_callback

pytestmark = pytest.mark.django_db


def messages_for(appointment, template=None):
    rows = Message.objects.unscoped().filter(appointment=appointment)
    if template is not None:
        rows = rows.filter(template=template)
    return list(rows)


def deliver(body):
    from payments.callbacks import handle_callback

    return handle_callback(body)


class TestOnlyTheLostRaceIsToldTheSlotWentAway:
    def test_a_genuinely_lost_slot_still_sends_it(self, held, shop_setup):
        """The case the message exists for. Guards against fixing the false
        positives by removing the message altogether."""
        from payments.tests.conftest import expire_the_hold, hold_at

        payment = push_for(held)
        expire_the_hold(held)
        # Somebody else takes the slot while the money is in flight.
        hold_at(shop_setup, 10, phone="0722000000")

        deliver(stk_callback(payment.checkout_request_id))

        payment.refresh_from_db()
        assert payment.state == PaymentState.ORPHANED
        assert payment.orphan_reason == OrphanReason.SLOT_LOST
        assert messages_for(held, Template.SLOT_LOST)

    def test_a_second_payment_on_a_confirmed_booking_says_nothing(self, held):
        """The resend case, exactly as it happens.

        The client asks for another prompt. The first push is superseded but
        Safaricom's prompt is still sitting on the phone, and they answer both.
        The resent payment confirms the booking; the superseded one settles
        afterwards and orphans as ALREADY_PAID — a real second deposit against
        a booking that is confirmed and intact. Nothing was taken from them by
        anybody, so `SLOT_LOST` would be a lie.
        """
        from payments.stk import resend_push

        first = push_for(held)
        second = resend_push(held, now=first.pushed_at + timedelta(minutes=2))

        # The resent prompt is answered first and confirms the booking.
        deliver(stk_callback(second.checkout_request_id))
        # Then the superseded one is answered too.
        deliver(stk_callback(first.checkout_request_id))

        first.refresh_from_db()
        held.refresh_from_db()
        assert first.state == PaymentState.ORPHANED
        assert first.orphan_reason == OrphanReason.ALREADY_PAID
        assert not messages_for(held, Template.SLOT_LOST)
        # And the message they *should* have is still there and still true.
        assert messages_for(held, Template.BOOKING_CONFIRMED)

    def test_a_payment_against_a_deliberately_cancelled_booking_says_nothing(self, held):
        """They pressed cancel, then answered the prompt anyway. A refund case
        for the shop, not a slot-lost notice for the client — nothing was taken
        from them by anyone else."""
        payment = push_for(held)
        cancel_deliberately(held)

        deliver(stk_callback(payment.checkout_request_id))

        payment.refresh_from_db()
        assert payment.state == PaymentState.ORPHANED
        assert payment.orphan_reason == OrphanReason.BOOKING_CANCELLED
        assert not messages_for(held, Template.SLOT_LOST)


class TestTheReconciliationPathAgrees:
    """The query path shares `settle_succeeded` and had the same bug in its own
    `_notify`. One fix in two places, so one test in two places."""

    def test_an_already_paid_orphan_found_by_query_says_nothing(self, held, fake_daraja):
        """Same shape as above, except the superseded payment's verdict is
        discovered by asking Safaricom rather than by being told."""
        from payments.daraja import QueryResult
        from payments.reconcile import reconcile
        from payments.stk import resend_push

        first = push_for(held)
        second = resend_push(held, now=first.pushed_at + timedelta(minutes=2))
        deliver(stk_callback(second.checkout_request_id))

        fake_daraja.next_query_result = QueryResult(result_code=0, result_desc="ok")
        first.refresh_from_db()
        reconcile(first, now=first.pushed_at + timedelta(minutes=5))

        first.refresh_from_db()
        held.refresh_from_db()
        assert first.state == PaymentState.ORPHANED
        assert first.orphan_reason == OrphanReason.ALREADY_PAID
        assert not messages_for(held, Template.SLOT_LOST)
