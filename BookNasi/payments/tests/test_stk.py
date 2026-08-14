"""LOAD-BEARING. Sending the prompt, and sending it again.

Three things are tested here that are cheap to get wrong and expensive to
discover:

**The row is written before the call.** A push that reaches Safaricom while our
HTTP response is lost still has a payment row for the reconciliation query to
attach the result to. Written afterwards, the money moves against a booking with
no record of having asked for it.

**A timeout is not a rejection.** `DarajaUnavailable` means we cannot tell;
`DarajaRejected` means no money will move. Collapsing the two loses a deposit
quietly, so they land in different states.

**Resend is bounded three ways and one of them is structural.** The grace
ceiling is derived from `hold_expires_at`, a column nothing moves, so there is
no code path that could extend it — which is stronger than a check that a later
slice might forget.
"""

from datetime import timedelta

import pytest

from payments.daraja import DarajaRejected, DarajaUnavailable
from payments.machine import open_payment_for
from payments.models import Payment
from payments.states import NON_TERMINAL_STATES, PaymentState
from payments.stk import PushRefused, initiate_push, outstanding_push, resend_push
from payments.tests.conftest import expire_the_hold, push_for, stk_callback
from scheduling.holds import grace_ceiling
from scheduling.statuses import AppointmentStatus

pytestmark = [pytest.mark.django_db, pytest.mark.loadbearing]


class TestThePush:
    def test_it_writes_the_row_before_it_calls_safaricom(self, held, fake_daraja):
        """Asserted through the seam: by the time `push` is entered there is
        already exactly one payment row for this appointment."""
        seen = []
        original = fake_daraja.push

        def watching(**kwargs):
            seen.append(Payment.objects.unscoped().filter(appointment=held).count())
            return original(**kwargs)

        fake_daraja.push = watching
        initiate_push(held)

        assert seen == [1]

    def test_an_accepted_push_records_the_checkout_id(self, held):
        payment = push_for(held)

        assert payment.state == PaymentState.PUSHED
        assert payment.checkout_request_id
        assert payment.pushed_at is not None

    def test_the_amount_is_the_snapshot_not_the_service_price(self, held, fake_daraja):
        """The service's deposit rule may change between the push and the
        callback. What was quoted on the confirm card is what gets charged."""
        push_for(held)

        assert fake_daraja.pushes[0]["amount"] == held.deposit_snapshot

    def test_the_reference_is_the_support_code(self, held, fake_daraja):
        """It is the only reference in this product a human can read out loud,
        and it is what appears on the client's M-Pesa statement."""
        payment = push_for(held)

        assert fake_daraja.pushes[0]["reference"] == payment.support_code

    def test_a_rejection_means_no_money_will_move(self, held, fake_daraja):
        fake_daraja.push_error = DarajaRejected("Invalid MSISDN", code="400.002.02")

        payment = initiate_push(held)

        assert payment.state == PaymentState.PUSH_FAILED
        assert payment.checkout_request_id is None

    def test_a_timeout_means_we_cannot_tell(self, held, fake_daraja):
        """The prompt may be on the phone right now. `UNKNOWN`, and the
        reconciliation query goes and asks."""
        fake_daraja.push_error = DarajaUnavailable("timed out")

        payment = initiate_push(held)

        assert payment.state == PaymentState.UNKNOWN
        assert payment.state in NON_TERMINAL_STATES

    def test_a_second_push_for_one_booking_is_refused(self, held):
        push_for(held)

        with pytest.raises(PushRefused) as refused:
            initiate_push(held)

        assert refused.value.reason == "push_in_flight"

    def test_only_one_non_terminal_payment_can_exist_at_the_database(self, held):
        """The application check above is the polite version. This is the one
        that survives two confirms in the same second."""
        from django.db import IntegrityError, transaction

        push_for(held)

        with pytest.raises(IntegrityError), transaction.atomic():
            Payment.objects.unscoped().create(
                appointment=held,
                amount=100,
                phone="+254712345678",
                state=PaymentState.PUSHED,
                checkout_request_id="ws_CO_racer",
                support_code="BK-RACER",
            )

    def test_a_booking_that_is_not_holding_is_refused(self, held):
        expire_the_hold(held)

        with pytest.raises(PushRefused) as refused:
            initiate_push(held)

        assert refused.value.reason == "not_holding"

    def test_a_settled_payment_frees_the_slot_for_another_row(self, held):
        """`SUCCEEDED` is outside `NON_TERMINAL_STATES`, so the constraint is a
        ceiling on *live* pushes rather than on the history."""
        payment = push_for(held)
        from payments.callbacks import handle_callback

        handle_callback(stk_callback(payment.checkout_request_id))

        assert open_payment_for(held) is None


class TestResendIsBounded:
    def test_a_resend_supersedes_the_first_push(self, held, settings):
        settings.STK_RESEND_MIN_INTERVAL_SECONDS = 0
        first = push_for(held)

        second = resend_push(held)

        first.refresh_from_db()
        assert first.state == PaymentState.SUPERSEDED
        assert second.state == PaymentState.PUSHED
        assert open_payment_for(held).pk == second.pk

    def test_two_prompts_inside_the_interval_are_refused(self, held, settings):
        settings.STK_RESEND_MIN_INTERVAL_SECONDS = 45
        push_for(held)

        with pytest.raises(PushRefused) as refused:
            resend_push(held)

        assert refused.value.reason == "too_soon"
        assert refused.value.retry_after > 0

    def test_the_count_is_capped_and_the_ussd_fallback_is_offered(self, held, settings):
        """CLAUDE.md §10, invariant 4: when the push does not arrive, `*334#` is
        the difference between a completed deposit and an abandoned booking."""
        settings.STK_RESEND_MIN_INTERVAL_SECONDS = 0
        settings.STK_RESEND_MAX = 1
        push_for(held)
        resend_push(held)

        with pytest.raises(PushRefused) as refused:
            resend_push(held)

        assert refused.value.reason == "resend_limit"
        assert "*334#" in str(refused.value)

    def test_a_resend_cannot_be_sent_past_the_grace_ceiling(self, held, settings):
        """The button is not a way to hold a slot for free."""
        settings.STK_RESEND_MIN_INTERVAL_SECONDS = 0
        push_for(held)
        past_the_ceiling = grace_ceiling(held) + timedelta(seconds=1)

        with pytest.raises(PushRefused) as refused:
            resend_push(held, now=past_the_ceiling)

        assert refused.value.reason == "hold_over"

    def test_the_ceiling_is_a_fixed_distance_from_a_column_nothing_moves(self, held, settings):
        """Structural, not checked: `grace_ceiling` is derived from
        `hold_expires_at`, so there is no field a resend could lengthen."""
        settings.STK_RESEND_MIN_INTERVAL_SECONDS = 0
        before = grace_ceiling(held)

        push_for(held)
        resend_push(held)
        held.refresh_from_db()

        assert grace_ceiling(held) == before


class TestTheSupersededPushCanStillBeAnswered:
    """The user's named case: resend while the first push is still live, then
    the first one succeeds.

    Superseding is *our* bookkeeping. The client's phone still has the first
    prompt on it, and if they enter their PIN the money genuinely moves — so a
    result on a superseded push is applied, not discarded. This is why the
    duplicate rule is "first **result** wins" and not "first terminal state
    wins".
    """

    def test_the_first_push_still_confirms_the_booking(self, held, settings):
        from payments.callbacks import handle_callback

        settings.STK_RESEND_MIN_INTERVAL_SECONDS = 0
        first = push_for(held)
        resend_push(held)
        first.refresh_from_db()
        assert first.state == PaymentState.SUPERSEDED

        handle_callback(stk_callback(first.checkout_request_id))

        first.refresh_from_db()
        held.refresh_from_db()
        assert first.state == PaymentState.SUCCEEDED
        assert held.status == AppointmentStatus.CONFIRMED

    def test_and_then_the_second_one_lands_in_the_exception_queue(self, held, settings):
        """Both prompts answered. Two deposits, one haircut — the shop owes the
        client one of them back, and `already_paid` is how they find out."""
        from payments.callbacks import handle_callback
        from payments.states import OrphanReason

        settings.STK_RESEND_MIN_INTERVAL_SECONDS = 0
        first = push_for(held)
        second = resend_push(held)

        handle_callback(stk_callback(first.checkout_request_id))
        handle_callback(stk_callback(second.checkout_request_id))

        second.refresh_from_db()
        assert second.state == PaymentState.ORPHANED
        assert second.orphan_reason == OrphanReason.ALREADY_PAID

    def test_a_superseded_push_still_counts_as_outstanding(self, held, settings):
        """Which is what stops the hold sweep releasing the slot underneath it."""
        settings.STK_RESEND_MIN_INTERVAL_SECONDS = 0
        push_for(held)
        resend_push(held)

        assert outstanding_push(held) is True


class TestTheCountdownCanTellTheTruth:
    """CLAUDE.md §10, invariant 3. A timer that reaches zero while the server is
    still holding the slot is the unexplained failure the invariant exists to
    prevent, so the API exposes both the expiry **and** whether a push is
    outstanding."""

    def test_no_push_means_nothing_outstanding(self, held):
        assert outstanding_push(held) is False

    def test_a_live_push_is_outstanding(self, held):
        push_for(held)

        assert outstanding_push(held) is True

    def test_a_resolved_push_is_not(self, held):
        from payments.callbacks import handle_callback

        payment = push_for(held)
        handle_callback(stk_callback(payment.checkout_request_id, result_code=1032))

        assert outstanding_push(held) is False

    def test_the_hold_endpoint_says_so(self, api_client, held):
        from django.urls import reverse

        push_for(held)
        url = reverse("public_api:hold-detail", kwargs={"hold_id": held.pk})

        payment = api_client.get(url).data["payment"]

        assert payment["push_outstanding"] is True
        assert payment["state"] == PaymentState.PUSHED
        assert payment["support_code"]


class TestTheResendEndpoint:
    """The one place the client and the server have to agree about a refusal."""

    def url(self, appointment):
        from django.urls import reverse

        return reverse("public_api:hold-resend", kwargs={"hold_id": appointment.pk})

    def test_a_resend_returns_the_hold_with_the_new_payment_on_it(self, api_client, held, settings):
        settings.STK_RESEND_MIN_INTERVAL_SECONDS = 0
        first = push_for(held)

        body = api_client.post(self.url(held)).data

        assert body["payment"]["state"] == PaymentState.PUSHED
        assert body["payment"]["support_code"] != first.support_code

    def test_a_refusal_carries_the_wait_in_the_body_as_well_as_the_header(
        self, api_client, held, settings
    ):
        """The header is the correct HTTP answer and a third-party integrator
        will read it. The browser client cannot — a cross-origin widget sees
        only allowed headers, and `booking-core`'s transport keeps the parsed
        body — so a countdown it cannot render is a client that retries at once.
        """
        settings.STK_RESEND_MIN_INTERVAL_SECONDS = 45
        push_for(held)

        response = api_client.post(self.url(held))

        assert response.status_code == 429
        assert response["Retry-After"]
        assert response.data["retry_after"] > 0
        assert response.data["reason"] == "too_soon"

    def test_a_refusal_leaves_the_original_push_alone(self, api_client, held, settings):
        """A refusal to send a *second* prompt is not a failure of the first."""
        settings.STK_RESEND_MIN_INTERVAL_SECONDS = 45
        first = push_for(held)

        api_client.post(self.url(held))

        first.refresh_from_db()
        assert first.state == PaymentState.PUSHED
        assert open_payment_for(held).pk == first.pk
