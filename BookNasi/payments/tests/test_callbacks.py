"""LOAD-BEARING. The five named cases, and the endpoint that receives them.

CLAUDE.md §5: "Callbacks must be idempotent. Safaricom retries. Unique
constraint on the checkout request ID; process exactly once. Duplicate
processing means double-charging or double-booking."

The five cases named at slice 6 planning, each as its own test:

1. Late callback after the hold expired, **before** the slot was retaken —
   must still confirm.
2. Late callback after the slot **was** retaken — `slotLost`.
3. The callback never arrives — see `test_reconciliation.py`, which is where
   the mechanism lives; the case is named here too so the set is visible in
   one place.
4. Duplicate callback — identical, and the harder one, conflicting.
5. Callback for an appointment that was cancelled deliberately.

The distinction between 1/2 and 5 is `hold_released_at`, and it is the whole of
the logic: a hold that ran **out** may be re-confirmed by late money, a booking
somebody **killed** may not.
"""

import pytest
from django.urls import reverse

from payments.callbacks import handle_callback
from payments.models import MpesaCallback, Payment
from payments.states import CallbackOutcome, OrphanReason, PaymentState
from payments.tests.conftest import (
    RECEIPT,
    cancel_deliberately,
    expire_the_hold,
    push_for,
    stk_callback,
)
from scheduling.booking import create_appointment
from scheduling.statuses import AppointmentStatus, BookingSource

pytestmark = [pytest.mark.django_db, pytest.mark.loadbearing]

S = AppointmentStatus


class TestTheOrdinaryPath:
    def test_a_paid_callback_confirms_the_booking(self, held):
        payment = push_for(held)

        outcome = handle_callback(stk_callback(payment.checkout_request_id))

        assert outcome == CallbackOutcome.APPLIED
        payment.refresh_from_db()
        held.refresh_from_db()
        assert payment.state == PaymentState.SUCCEEDED
        assert payment.mpesa_receipt == RECEIPT
        assert held.status == S.CONFIRMED

    def test_the_receipt_and_the_paid_at_are_stored(self, held):
        """Screen 6 puts the receipt above everything else — it is the client's
        proof at the door — so it has to survive the round trip."""
        payment = push_for(held)

        handle_callback(stk_callback(payment.checkout_request_id))

        payment.refresh_from_db()
        assert payment.mpesa_receipt == RECEIPT
        assert payment.paid_at is not None
        assert payment.resolved_at is not None


class TestCaseOneLateCallbackBeforeTheSlotWasRetaken:
    """The hold ran out, the money arrived anyway, and nobody else took the
    slot. This must confirm: the client paid for a time that is still free."""

    def test_a_late_callback_reconfirms_an_expired_hold(self, held):
        payment = push_for(held)
        expire_the_hold(held)
        assert held.status == S.CANCELLED
        assert held.hold_released_at is not None

        handle_callback(stk_callback(payment.checkout_request_id))

        held.refresh_from_db()
        payment.refresh_from_db()
        assert held.status == S.CONFIRMED
        assert payment.state == PaymentState.SUCCEEDED
        assert payment.orphan_reason == ""

    def test_the_client_is_not_punished_by_the_abandonment_cooldown(self, held):
        """`hold_released_at` is what `scheduling/abuse.py` counts. A client who
        paid — late, but paid — must not be treated as one who walked away, or
        their next booking is refused for having succeeded at this one."""
        payment = push_for(held)
        expire_the_hold(held)

        handle_callback(stk_callback(payment.checkout_request_id))

        held.refresh_from_db()
        assert held.hold_released_at is None


class TestCaseTwoLateCallbackAfterTheSlotWasRetaken:
    """`slotLost`. The one branch in this module that generates a phone call."""

    def _retake(self, shop_setup, held):
        """Somebody else books the same staff and time, for real."""
        return create_appointment(
            staff=shop_setup.wanjiku,
            service=shop_setup.braids,
            starts_at=held.starts_at,
            source=BookingSource.WALK_IN,
            status=S.CONFIRMED,
            now=held.starts_at,
        )

    def test_the_payment_is_orphaned_as_slot_lost(self, shop_setup, held):
        payment = push_for(held)
        expire_the_hold(held)
        self._retake(shop_setup, held)

        handle_callback(stk_callback(payment.checkout_request_id))

        payment.refresh_from_db()
        held.refresh_from_db()
        assert payment.state == PaymentState.ORPHANED
        assert payment.orphan_reason == OrphanReason.SLOT_LOST
        # The booking stays cancelled. It is the money that has no home, not the
        # slot — and resurrecting it here would double-book the person in the chair.
        assert held.status == S.CANCELLED

    def test_the_money_is_still_recorded_as_received(self, shop_setup, held):
        """Orphaning does not un-pay anything. The shop has the deposit and the
        exception queue is how they find out they owe somebody a phone call."""
        payment = push_for(held)
        expire_the_hold(held)
        self._retake(shop_setup, held)

        handle_callback(stk_callback(payment.checkout_request_id))

        payment.refresh_from_db()
        assert payment.result_code == 0
        assert payment.mpesa_receipt == RECEIPT
        assert payment.support_code

    def test_the_client_is_told_and_given_the_support_code(
        self, shop_setup, held, console_messages
    ):
        """This slice's remedy for slotLost is the shop phoning the client, so
        the message that starts the phone call is part of the remedy."""
        from notifications.models import Message
        from notifications.templates import Template

        payment = push_for(held)
        expire_the_hold(held)
        self._retake(shop_setup, held)

        handle_callback(stk_callback(payment.checkout_request_id))

        message = Message.objects.for_org(held.organization_id).get(template=Template.SLOT_LOST)
        assert message.variables["support_code"] == payment.support_code
        assert message.variables["shop_phone"]


class TestCaseFourDuplicateCallback:
    def test_an_identical_duplicate_is_recorded_and_not_reapplied(self, held):
        payment = push_for(held)
        body = stk_callback(payment.checkout_request_id)
        handle_callback(body)
        payment.refresh_from_db()
        first_resolved = payment.resolved_at

        outcome = handle_callback(body)

        assert outcome == CallbackOutcome.DUPLICATE
        payment.refresh_from_db()
        assert payment.state == PaymentState.SUCCEEDED
        # Not re-stamped. A retry three minutes later must not move the moment
        # the money arrived.
        assert payment.resolved_at == first_resolved
        assert payment.discrepancy_count == 0
        assert MpesaCallback.objects.filter(payment=payment).count() == 2

    def test_a_conflicting_duplicate_is_a_discrepancy_and_the_original_stands(self, held):
        """The one the user named. Safaricom does sometimes send two different
        verdicts for one CheckoutRequestID. Applying the later one turns a
        confirmed booking — one the client has already been sent an SMS about —
        back into an unconfirmed one."""
        payment = push_for(held)
        handle_callback(stk_callback(payment.checkout_request_id, result_code=0))
        payment.refresh_from_db()
        assert payment.state == PaymentState.SUCCEEDED

        outcome = handle_callback(
            stk_callback(
                payment.checkout_request_id,
                result_code=1032,
                result_desc="Request cancelled by user",
            )
        )

        assert outcome == CallbackOutcome.DISCREPANCY
        payment.refresh_from_db()
        held.refresh_from_db()
        # Untouched, all of it.
        assert payment.state == PaymentState.SUCCEEDED
        assert payment.result_code == 0
        assert payment.mpesa_receipt == RECEIPT
        assert held.status == S.CONFIRMED
        # And surfaced.
        assert payment.discrepancy_count == 1

    def test_the_conflicting_body_is_kept_next_to_what_we_already_held(self, held):
        payment = push_for(held)
        handle_callback(stk_callback(payment.checkout_request_id, result_code=0))

        handle_callback(stk_callback(payment.checkout_request_id, result_code=1))

        row = MpesaCallback.objects.get(outcome=CallbackOutcome.DISCREPANCY)
        assert row.result_code == 1
        assert row.previous_result_code == 0

    def test_a_conflicting_duplicate_does_not_send_a_second_sms(self, held):
        """The client has already been told the booking is confirmed. A second
        message, or a contradicting one, is worse than silence."""
        from notifications.models import Message

        payment = push_for(held)
        handle_callback(stk_callback(payment.checkout_request_id, result_code=0))
        before = Message.objects.unscoped().count()

        handle_callback(stk_callback(payment.checkout_request_id, result_code=1032))

        assert Message.objects.unscoped().count() == before


class TestCaseFiveCallbackForACancelledAppointment:
    def test_a_deliberate_cancel_is_never_resurrected(self, held):
        """`hold_released_at` is null because somebody pressed cancel. Money
        landing afterwards is a refund case, not a booking."""
        payment = push_for(held)
        cancel_deliberately(held)
        assert held.hold_released_at is None

        handle_callback(stk_callback(payment.checkout_request_id))

        held.refresh_from_db()
        payment.refresh_from_db()
        assert held.status == S.CANCELLED
        assert payment.state == PaymentState.ORPHANED
        assert payment.orphan_reason == OrphanReason.BOOKING_CANCELLED

    def test_a_payment_for_an_already_confirmed_booking_is_orphaned(self, held):
        """Two prompts, both answered. Two deposits for one haircut, and the
        second one is the shop's to return."""
        first = push_for(held)
        handle_callback(stk_callback(first.checkout_request_id))
        held.refresh_from_db()
        assert held.status == S.CONFIRMED

        second = Payment.objects.unscoped().create(
            appointment=held,
            amount=held.deposit_snapshot,
            phone="+254712345678",
            state=PaymentState.PUSHED,
            checkout_request_id="ws_CO_second",
            support_code="BK-SECOND",
        )
        handle_callback(stk_callback("ws_CO_second"))

        second.refresh_from_db()
        assert second.state == PaymentState.ORPHANED
        assert second.orphan_reason == OrphanReason.ALREADY_PAID


class TestSandboxShapedFailures:
    """The bodies the sandbox actually returns, not invented ones.

    1032 is the client pressing cancel on the PIN prompt and is by far the most
    common non-zero code. 1 and 1037 are the two that follow it: no money on the
    line, and no response from the phone at all.
    """

    @pytest.mark.parametrize(
        ("code", "desc"),
        [
            (1032, "Request cancelled by user"),
            (1, "The balance is insufficient for the transaction"),
            (1037, "DS timeout user cannot be reached"),
            (2001, "The initiator information is invalid."),
        ],
    )
    def test_a_failure_body_carries_no_metadata_and_still_parses(self, held, code, desc):
        payment = push_for(held)

        outcome = handle_callback(
            stk_callback(payment.checkout_request_id, result_code=code, result_desc=desc)
        )

        assert outcome == CallbackOutcome.APPLIED
        payment.refresh_from_db()
        assert payment.result_code == code
        assert payment.result_desc == desc
        assert payment.mpesa_receipt == ""

    def test_1032_is_its_own_state_because_the_advice_differs(self, held):
        """Telling somebody who pressed cancel to "try a different number" is
        the wrong advice, so the state is split rather than the copy branched."""
        payment = push_for(held)

        handle_callback(
            stk_callback(
                payment.checkout_request_id,
                result_code=1032,
                result_desc="Request cancelled by user",
            )
        )

        payment.refresh_from_db()
        assert payment.state == PaymentState.CANCELLED_BY_USER

    def test_an_ordinary_failure_is_failed_not_cancelled(self, held):
        payment = push_for(held)

        handle_callback(stk_callback(payment.checkout_request_id, result_code=1))

        payment.refresh_from_db()
        assert payment.state == PaymentState.FAILED

    def test_a_failed_payment_does_not_release_the_hold(self, held):
        """The design's screen 7 keeps the countdown alive through a failure —
        the client retries inside whatever is left of the TTL. Releasing here
        would take the slot away from somebody who is mid-retry."""
        payment = push_for(held)

        handle_callback(stk_callback(payment.checkout_request_id, result_code=1))

        held.refresh_from_db()
        assert held.status == S.PENDING_PAYMENT
        assert held.hold_expires_at is not None

    def test_a_failed_payment_sends_no_sms(self, held):
        """The client is watching it happen. An SMS to somebody about to retry
        is noise the shop pays for — CLAUDE.md §6 on messaging cost."""
        from notifications.models import Message

        payment = push_for(held)

        handle_callback(stk_callback(payment.checkout_request_id, result_code=1032))

        assert Message.objects.unscoped().count() == 0


class TestNothingEscapes:
    """Every path returns an outcome, because an exception is a non-200 and a
    non-200 is a Safaricom retry."""

    def test_a_malformed_body_is_recorded_not_raised(self):
        outcome = handle_callback({"nonsense": True})

        assert outcome == CallbackOutcome.MALFORMED
        assert MpesaCallback.objects.filter(outcome=CallbackOutcome.MALFORMED).count() == 1

    def test_a_body_that_is_not_even_an_object_is_survived(self):
        assert handle_callback("<html>gateway error</html>") == CallbackOutcome.MALFORMED

    def test_a_callback_with_no_checkout_id_is_malformed(self):
        body = stk_callback("x")
        del body["Body"]["stkCallback"]["CheckoutRequestID"]

        assert handle_callback(body) == CallbackOutcome.MALFORMED

    def test_an_unknown_checkout_id_is_kept_not_dropped(self):
        """Either a push we lost the row for, or somebody probing. Both worth
        being able to see later."""
        outcome = handle_callback(stk_callback("ws_CO_never_seen"))

        assert outcome == CallbackOutcome.UNMATCHED
        assert MpesaCallback.objects.filter(outcome=CallbackOutcome.UNMATCHED).count() == 1


class TestThePayloadIsRedactedBeforeItTouchesDisk:
    """CLAUDE.md §5. A database column is worse than a log line: it is durable
    and it is joined to a name."""

    def test_the_payers_number_is_not_stored(self, held):
        payment = push_for(held)

        handle_callback(stk_callback(payment.checkout_request_id, phone=254712345678))

        row = MpesaCallback.objects.get(outcome=CallbackOutcome.APPLIED)
        assert "254712345678" not in str(row.payload)

    def test_the_rest_of_the_body_survives_redaction(self, held):
        payment = push_for(held)

        handle_callback(stk_callback(payment.checkout_request_id))

        row = MpesaCallback.objects.get(outcome=CallbackOutcome.APPLIED)
        items = row.payload["Body"]["stkCallback"]["CallbackMetadata"]["Item"]
        by_name = {item["Name"]: item["Value"] for item in items}
        assert by_name["MpesaReceiptNumber"] == RECEIPT
        assert by_name["PhoneNumber"] == "[redacted]"

    def test_the_callback_log_cannot_be_edited(self, held):
        payment = push_for(held)
        handle_callback(stk_callback(payment.checkout_request_id))
        row = MpesaCallback.objects.first()

        row.result_desc = "something else"
        with pytest.raises(ValueError, match="append-only"):
            row.save()


class TestTheEndpointAlwaysAnswers200:
    """A 429, a 500 or a 404 on a real callback is a Safaricom retry. The only
    non-200 is a bad path token, which must be loudly broken."""

    def url(self, settings, token=None):
        return reverse(
            "payments:mpesa-callback",
            kwargs={"token": token or settings.MPESA_CALLBACK_TOKEN},
        )

    def test_a_good_callback_is_200(self, api_client, settings, held):
        payment = push_for(held)

        response = api_client.post(
            self.url(settings), stk_callback(payment.checkout_request_id), format="json"
        )

        assert response.status_code == 200
        assert response.data["ResultCode"] == 0

    def test_a_malformed_body_is_still_200(self, api_client, settings):
        response = api_client.post(self.url(settings), {"junk": 1}, format="json")

        assert response.status_code == 200

    def test_an_unknown_checkout_id_is_still_200(self, api_client, settings):
        response = api_client.post(self.url(settings), stk_callback("ws_CO_unknown"), format="json")

        assert response.status_code == 200
        assert response.data["outcome"] == CallbackOutcome.UNMATCHED

    def test_a_conflicting_duplicate_is_still_200(self, api_client, settings, held):
        """A refusal is not an error to Safaricom. We recorded it; they are done."""
        payment = push_for(held)
        api_client.post(
            self.url(settings), stk_callback(payment.checkout_request_id), format="json"
        )

        response = api_client.post(
            self.url(settings),
            stk_callback(payment.checkout_request_id, result_code=1032),
            format="json",
        )

        assert response.status_code == 200
        assert response.data["outcome"] == CallbackOutcome.DISCREPANCY

    def test_a_wrong_path_token_is_404(self, api_client, settings):
        """Safaricom does not sign callbacks and does not offer mTLS. Without
        the token this endpoint is a public POST that confirms bookings."""
        response = api_client.post(
            self.url(settings, token="not-the-token"), stk_callback("ws_CO_1"), format="json"
        )

        assert response.status_code == 404
        assert MpesaCallback.objects.count() == 0

    def test_the_endpoint_is_not_throttled(self, api_client, settings, held):
        """A 429 is a non-200 and therefore a retry. Rate limiting the endpoint
        that tells us money arrived is rate limiting our own revenue."""
        from payments.views import MpesaCallbackView

        assert MpesaCallbackView.throttle_classes == []
        for _ in range(30):
            response = api_client.post(
                self.url(settings), stk_callback("ws_CO_flood"), format="json"
            )
            assert response.status_code == 200
