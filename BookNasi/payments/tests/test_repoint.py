"""The `slotLost` remedy, end to end. CLAUDE.md §12's second open question.

The client paid, the callback was slow, and somebody else took the slot. Slice 6
named the state and made the remedy a phone call — honestly, because nothing
automatic existed. Slice 7 makes it the client's own: they pick another time and
the succeeded payment is re-pointed at it, with no second push.

The §5 carve-out this depends on is written in §5 itself, not here: a succeeded
payment *is* the phone verification the deposit rule exists to provide, so a
booking backed by one is not the unverified-number case the rule forbids.

`payments/tests/test_orphan_messaging.py` covers which orphans get told what.
This covers what happens when one is put right.
"""

from datetime import timedelta

import pytest
from django.urls import reverse

from notifications.models import Message
from notifications.templates import Template
from payments.repoint import RepointRefused, is_repointable, repoint
from payments.states import OrphanReason, PaymentState
from payments.tests.conftest import expire_the_hold, hold_at, push_for, stk_callback
from scheduling.statuses import AppointmentStatus

pytestmark = pytest.mark.django_db

S = AppointmentStatus


def deliver(body):
    from payments.callbacks import handle_callback

    return handle_callback(body)


# 14:00 on Grace, not Wanjiku: the `held` fixture books Wanjiku 10:00-14:00 for
# braids, and its trailing buffer runs past 14:00, so there is no free braids
# start left on her day. The stylist is incidental to every test here — what
# matters is that the target is a live hold at the same shop.
@pytest.fixture
def lost(held, shop_setup):
    """A payment that succeeded into a slot somebody else had already taken.

    Built through the real machinery — a real push, a real expiry, a real
    competing hold, a real late callback — because the whole point of the state
    is that it is produced by a race, and a hand-written ORPHANED row would not
    prove the remedy works on the thing the race produces.
    """
    payment = push_for(held)
    expire_the_hold(held)
    hold_at(shop_setup, 10, phone="0722000000")  # somebody else takes it
    deliver(stk_callback(payment.checkout_request_id))
    payment.refresh_from_db()
    return payment


class TestTheFixtureIsTheRealThing:
    def test_the_payment_really_is_orphaned_as_slot_lost(self, lost):
        assert lost.state == PaymentState.ORPHANED
        assert lost.orphan_reason == OrphanReason.SLOT_LOST
        assert is_repointable(lost)

    def test_the_client_was_told(self, lost, held):
        assert (
            Message.objects.unscoped()
            .filter(appointment=held, template=Template.SLOT_LOST)
            .exists()
        )


class TestRepointing:
    def test_it_confirms_the_new_booking_with_no_second_push(self, lost, shop_setup, fake_daraja):
        """The whole point. The client already paid; asking again would be
        charging twice for one haircut."""
        pushes_before = len(fake_daraja.pushes)
        target = hold_at(shop_setup, 14, phone="0712345678", staff=shop_setup.grace)

        repoint(lost, to_appointment=target)

        target.refresh_from_db()
        lost.refresh_from_db()
        assert target.status == S.CONFIRMED
        assert lost.state == PaymentState.SUCCEEDED
        assert lost.orphan_reason == ""
        assert lost.appointment_id == target.pk
        # Not "one fewer than usual" — *none*. Re-pointing settles the target
        # outright, so no prompt is ever sent for it.
        assert len(fake_daraja.pushes) == pushes_before

    def test_it_records_the_move(self, lost, shop_setup):
        """`PaymentMove` keeps the pair even though `Payment.appointment` has
        already moved — the pair is the whole point of the row."""
        from payments.models import PaymentMove

        origin = lost.appointment_id
        target = hold_at(shop_setup, 14, phone="0712345678", staff=shop_setup.grace)

        repoint(lost, to_appointment=target)

        move = PaymentMove.objects.unscoped().get()
        assert move.payment_id == lost.pk
        assert move.from_appointment_id == origin
        assert move.to_appointment_id == target.pk
        assert move.reason == "slot_lost_remedy"

    def test_the_client_gets_an_ordinary_confirmation(self, lost, shop_setup):
        """Not a special "your re-pointed payment has been applied" message.
        From the client's side this is a confirmed booking with a paid deposit,
        and explaining our own plumbing to somebody who wanted a haircut is not
        a feature."""
        from payments.repoint import notify_repointed

        target = hold_at(shop_setup, 14, phone="0712345678", staff=shop_setup.grace)
        repoint(lost, to_appointment=target)
        lost.refresh_from_db()
        notify_repointed(target, lost)

        assert (
            Message.objects.unscoped()
            .filter(appointment=target, template=Template.BOOKING_CONFIRMED)
            .exists()
        )


class TestWhatItRefuses:
    def test_a_payment_that_never_succeeded(self, held, shop_setup):
        payment = push_for(held)
        target = hold_at(shop_setup, 14, phone="0712345678", staff=shop_setup.grace)

        with pytest.raises(RepointRefused) as exc:
            repoint(payment, to_appointment=target)
        assert exc.value.reason == "not_repointable"

    def test_an_orphan_that_is_not_a_lost_slot(self, held, shop_setup):
        """`ALREADY_PAID` is a second deposit on an intact booking. Re-pointing
        it would move money off a booking that is fine."""
        from payments.stk import resend_push

        first = push_for(held)
        second = resend_push(held, now=first.pushed_at + timedelta(minutes=2))
        deliver(stk_callback(second.checkout_request_id))
        deliver(stk_callback(first.checkout_request_id))
        first.refresh_from_db()

        assert first.orphan_reason == OrphanReason.ALREADY_PAID
        assert not is_repointable(first)
        with pytest.raises(RepointRefused):
            repoint(
                first,
                to_appointment=hold_at(shop_setup, 14, phone="0700111222", staff=shop_setup.grace),
            )

    def test_a_target_that_is_not_holding(self, lost, shop_setup):
        target = hold_at(shop_setup, 14, phone="0712345678", staff=shop_setup.grace)
        deliver(stk_callback(push_for(target).checkout_request_id))
        target.refresh_from_db()

        with pytest.raises(RepointRefused) as exc:
            repoint(lost, to_appointment=target)
        assert exc.value.reason == "not_holding"

    def test_a_target_needing_a_bigger_deposit(self, lost, shop_setup):
        """Silently under-charging is how a shop finds out at the chair."""
        target = hold_at(shop_setup, 14, phone="0712345678", staff=shop_setup.grace)
        target.deposit_snapshot = lost.amount + 1
        target.save(update_fields=["deposit_snapshot"])

        with pytest.raises(RepointRefused) as exc:
            repoint(lost, to_appointment=target)
        assert exc.value.reason == "deposit_short"


class TestTheEndpoint:
    def test_the_client_can_do_it_themselves(self, lost, shop_setup, api_client):
        target = hold_at(shop_setup, 14, phone="0712345678", staff=shop_setup.grace)

        response = api_client.post(
            reverse("public_api:payment-repoint", args=[lost.support_code]),
            {"hold": str(target.pk)},
            format="json",
        )

        assert response.status_code == 200
        target.refresh_from_db()
        assert target.status == S.CONFIRMED

    def test_an_unknown_support_code_is_the_same_404_as_a_bad_one(
        self, lost, shop_setup, api_client
    ):
        """No existence oracle here either — the support code is a credential."""
        target = hold_at(shop_setup, 14, phone="0712345678", staff=shop_setup.grace)
        body = {"hold": str(target.pk)}

        unknown = api_client.post(
            reverse("public_api:payment-repoint", args=["BK-NOPE00"]), body, format="json"
        )
        # A real code that is not repointable must look identical.
        repoint(lost, to_appointment=target)
        used = api_client.post(
            reverse("public_api:payment-repoint", args=[lost.support_code]), body, format="json"
        )

        assert unknown.status_code == used.status_code == 404
        assert unknown.content == used.content

    def test_it_does_not_leak_the_code_in_a_referer(self, lost, shop_setup, api_client):
        target = hold_at(shop_setup, 14, phone="0712345678", staff=shop_setup.grace)

        response = api_client.post(
            reverse("public_api:payment-repoint", args=[lost.support_code]),
            {"hold": str(target.pk)},
            format="json",
        )

        assert response["Referrer-Policy"] == "no-referrer"


class TestTheClientDeclinesEverySlot:
    """The case the remedy must not make worse.

    A client who opens screen 8, looks at every remaining time and wants none of
    them is left exactly where slice 6 left them: money recorded against no
    booking, the row on the exception queue, the support code in their hand and
    the shop's number on the screen. Nothing is silently consumed by an offer
    they turned down.
    """

    def test_declining_leaves_the_payment_repointable(self, lost):
        assert is_repointable(lost)
        # They looked, and left. No endpoint was called.
        lost.refresh_from_db()
        assert lost.state == PaymentState.ORPHANED
        assert lost.orphan_reason == OrphanReason.SLOT_LOST

    def test_it_stays_on_the_exception_queue_for_a_human(self, lost):
        """The phone call is still there. A remedy that removed the fallback
        would be worse than the one it replaced."""
        from payments.models import Payment

        queue = Payment.objects.unscoped().filter(
            state=PaymentState.ORPHANED, queue_resolved_at__isnull=True
        )

        assert lost in list(queue)

    def test_a_failed_repoint_does_not_consume_the_payment(self, lost, shop_setup):
        """They picked a slot, it had gone too, and they are back where they
        started rather than out of options *and* out of money."""
        target = hold_at(shop_setup, 14, phone="0712345678", staff=shop_setup.grace)
        target.deposit_snapshot = lost.amount + 1
        target.save(update_fields=["deposit_snapshot"])

        with pytest.raises(RepointRefused):
            repoint(lost, to_appointment=target)

        lost.refresh_from_db()
        assert lost.state == PaymentState.ORPHANED
        assert is_repointable(lost), "still available for another attempt"
