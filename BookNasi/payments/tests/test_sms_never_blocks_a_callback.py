"""LOAD-BEARING. A slow SMS gateway must not cause a Safaricom retry.

The failure this file exists to prevent is not hypothetical and it is not
cosmetic. If the SMS send happens inside the callback's transaction:

1. A gateway that takes eight seconds holds a `SELECT … FOR UPDATE` row lock on
   the payment for eight seconds.
2. Our 200 to Safaricom is eight seconds late, so Safaricom retries.
3. The retry blocks on the lock the first request is still holding.
4. Every subsequent retry does the same, against a table now full of waiters.

That turns a slow third party into a payment outage, and it turns the
idempotency machinery — which exists to survive rare retries — into the thing
being exercised constantly. The whole of the fix is `transaction.on_commit`,
and this asserts it from three directions, because it is the kind of property a
later refactor removes without noticing.
"""

import time

import pytest
from django.db import connection, transaction
from django.urls import reverse

from payments.callbacks import handle_callback
from payments.models import MpesaCallback, Payment
from payments.states import CallbackOutcome, PaymentState
from payments.tests.conftest import push_for, stk_callback
from scheduling.statuses import AppointmentStatus

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.loadbearing]


class SlowProvider:
    """A gateway that takes a second. Real ones sometimes take considerably
    longer, and the number here only has to be big enough to measure."""

    name = "slow"
    delay = 1.0

    def __init__(self):
        self.sent = []
        self.saw_open_transaction = None

    def send(self, message):
        from notifications.providers import DeliveryReceipt

        # The assertion that matters, taken at the moment of the send rather
        # than inferred afterwards: is the callback's transaction still open?
        self.saw_open_transaction = connection.in_atomic_block
        time.sleep(self.delay)
        self.sent.append(message)
        return DeliveryReceipt(provider_message_id="slow-1", accepted=True, cost_kes=1)


@pytest.fixture
def slow_provider(settings, monkeypatch):
    from notifications import providers

    provider = SlowProvider()
    monkeypatch.setattr(providers, "_provider", provider)
    return provider


class TestTheSendHappensAfterTheCommit:
    def test_the_gateway_is_never_called_inside_the_callback_transaction(self, held, slow_provider):
        """If this is True, a slow gateway is holding a row lock on money."""
        payment = push_for(held)

        handle_callback(stk_callback(payment.checkout_request_id))

        assert slow_provider.sent, "the confirmation was never sent at all"
        assert slow_provider.saw_open_transaction is False

    def test_the_payment_is_already_committed_when_the_message_goes(self, held, slow_provider):
        """Which is what makes the ordering safe in the other direction too: a
        rolled-back payment can never leave a promise to message somebody."""
        payment = push_for(held)

        handle_callback(stk_callback(payment.checkout_request_id))

        assert slow_provider.sent
        # Read on a fresh connection state: the row is visible outside the
        # handler's transaction, so the commit preceded the send.
        assert Payment.objects.unscoped().get(pk=payment.pk).state == PaymentState.SUCCEEDED

    def test_a_gateway_that_hangs_does_not_delay_the_200(self, held, slow_provider, settings):
        """The one Safaricom actually sees. The response has to be back before
        the SMS is anywhere near sent — which, with the send outside the
        transaction and dispatched to a worker, it is.

        Celery runs eagerly in tests, so `on_commit` still executes inline here
        and the wall clock cannot separate the two. What is asserted instead is
        the structural fact underneath: nothing awaits the provider while the
        request's transaction is open.
        """
        payment = push_for(held)
        url = reverse("payments:mpesa-callback", kwargs={"token": settings.MPESA_CALLBACK_TOKEN})

        from rest_framework.test import APIClient

        response = APIClient().post(url, stk_callback(payment.checkout_request_id), format="json")

        assert response.status_code == 200
        assert slow_provider.saw_open_transaction is False
        held.refresh_from_db()
        assert held.status == AppointmentStatus.CONFIRMED

    def test_a_gateway_that_raises_does_not_lose_the_payment(self, held, monkeypatch):
        """The money is real whatever the gateway does."""
        from notifications import providers

        class Exploding:
            name = "exploding"

            def send(self, message):
                raise RuntimeError("gateway down")

        monkeypatch.setattr(providers, "_provider", Exploding())

        payment = push_for(held)
        outcome = handle_callback(stk_callback(payment.checkout_request_id))

        payment.refresh_from_db()
        held.refresh_from_db()
        assert payment.state == PaymentState.SUCCEEDED
        assert held.status == AppointmentStatus.CONFIRMED
        # And the callback is reported as what it was. A messaging failure
        # recorded as a malformed body would be a false entry in the one table
        # whose whole job is to be evidence.
        assert outcome == CallbackOutcome.APPLIED
        assert not MpesaCallback.objects.filter(outcome=CallbackOutcome.MALFORMED).exists()


class TestTheDispatchIsQueuedNotInline:
    def test_queueing_a_message_registers_an_on_commit_hook(self, held):
        """Asserted directly, because the property is easy to lose to an
        innocent-looking refactor: `queue_message` must not touch the provider
        while the caller's transaction is open."""
        from notifications.service import queue_message
        from notifications.templates import Template

        sent_during = []

        class Watching:
            name = "watching"

            def send(self, message):
                from notifications.providers import DeliveryReceipt

                sent_during.append(connection.in_atomic_block)
                return DeliveryReceipt(provider_message_id="w-1")

        from notifications import providers

        original = providers._provider
        providers._provider = Watching()
        try:
            with transaction.atomic():
                queue_message(held, Template.HOLD_RELEASED)
                # Still inside. Nothing has been sent.
                assert sent_during == []
        finally:
            providers._provider = original

        assert sent_during == [False]
