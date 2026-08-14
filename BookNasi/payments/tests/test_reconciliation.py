"""LOAD-BEARING. Case 3: the callback that never arrives.

This is the case idempotency cannot answer, and the reason `query` exists
alongside `push`. Without it, "no callback" and "no payment" are the same
observation: the hold sweep releases a slot somebody has already paid for, the
money sits in the paybill against a cancelled booking, and nothing anywhere
notices — no error, no log line, no queue. The client finds out at the door.

So we do not wait to be told. We go and ask.

The reconciliation query is a **separate mechanism from the hold sweep**, and
that separation is asserted here rather than assumed: different task, different
schedule, different failure mode. The sweep decides whether a *slot* goes back
on offer; the query decides what happened to *money*. Conflating them means
either a slow M-Pesa holds the calendar hostage or a busy calendar skips a
payment.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from payments import tasks
from payments.daraja import DarajaUnavailable, QueryResult
from payments.models import Payment
from payments.reconcile import reconcile, stale_payments, unresolved_payments
from payments.states import PaymentState
from payments.tests.conftest import push_for
from scheduling.statuses import AppointmentStatus

pytestmark = [pytest.mark.django_db, pytest.mark.loadbearing]


def pushed_ago(payment, seconds):
    Payment.objects.unscoped().filter(pk=payment.pk).update(
        pushed_at=timezone.now() - timedelta(seconds=seconds)
    )
    payment.refresh_from_db()
    return payment


class TestTheWorkingSet:
    def test_a_fresh_push_is_not_asked_about_yet(self, held, settings):
        """Asking a second after the prompt goes out only ever gets "still
        processing" — and a query costs a round trip and a rate limit."""
        push_for(held)

        assert unresolved_payments().count() == 0

    def test_an_unanswered_push_past_the_delay_is_picked_up(self, held, settings):
        payment = push_for(held)
        pushed_ago(payment, settings.PAYMENT_QUERY_AFTER.total_seconds() + 10)

        assert list(unresolved_payments()) == [payment]

    def test_a_payment_with_a_verdict_is_never_asked_about(self, held, settings):
        from payments.callbacks import handle_callback
        from payments.tests.conftest import stk_callback

        payment = push_for(held)
        handle_callback(stk_callback(payment.checkout_request_id))
        pushed_ago(payment, settings.PAYMENT_QUERY_AFTER.total_seconds() + 10)

        assert unresolved_payments().count() == 0

    def test_a_superseded_push_is_still_asked_about(self, held, settings):
        """It may still be answered — the client's phone still has the prompt.
        This is exactly the row that a `NON_TERMINAL_STATES` filter would drop."""
        settings.STK_RESEND_MIN_INTERVAL_SECONDS = 0
        from payments.stk import resend_push

        first = push_for(held)
        resend_push(held)
        pushed_ago(first, settings.PAYMENT_QUERY_AFTER.total_seconds() + 10)
        first.refresh_from_db()
        assert first.state == PaymentState.SUPERSEDED

        assert first in list(unresolved_payments())

    def test_asking_stops_after_the_attempt_ceiling(self, held, settings):
        """A row that keeps being retried is a row nobody looks at."""
        payment = push_for(held)
        pushed_ago(payment, settings.PAYMENT_QUERY_AFTER.total_seconds() + 10)
        Payment.objects.unscoped().filter(pk=payment.pk).update(
            query_attempts=settings.PAYMENT_QUERY_MAX_ATTEMPTS
        )

        assert unresolved_payments().count() == 0


class TestAskingSafaricomDirectly:
    def test_a_paid_answer_confirms_the_booking(self, held, fake_daraja):
        payment = push_for(held)
        fake_daraja.next_query_result = QueryResult(result_code=0, result_desc="paid")

        assert reconcile(payment) == "confirmed"

        payment.refresh_from_db()
        held.refresh_from_db()
        assert payment.state == PaymentState.SUCCEEDED
        assert held.status == AppointmentStatus.CONFIRMED

    def test_a_query_settled_payment_records_where_we_learned_it(self, held, fake_daraja):
        """A query never returns the receipt number. Rather than leave the
        column empty — which the check constraint forbids and a shop reading it
        off a screen would find useless — it records the provenance and the
        support code, which is what the client and the shop actually quote."""
        payment = push_for(held)
        fake_daraja.next_query_result = QueryResult(result_code=0, result_desc="paid")

        reconcile(payment)

        payment.refresh_from_db()
        assert payment.support_code in payment.mpesa_receipt
        assert "query" in payment.mpesa_receipt

    def test_a_failed_answer_settles_without_touching_the_hold(self, held, fake_daraja):
        payment = push_for(held)
        fake_daraja.next_query_result = QueryResult(result_code=1032, result_desc="cancelled")

        reconcile(payment)

        payment.refresh_from_db()
        held.refresh_from_db()
        assert payment.state == PaymentState.CANCELLED_BY_USER
        assert held.status == AppointmentStatus.PENDING_PAYMENT

    def test_still_processing_is_an_answer_and_not_a_failure(self, held, fake_daraja):
        """Daraja's 500.001.1001. It means ask again, not give up."""
        payment = push_for(held)
        fake_daraja.next_query_result = QueryResult(result_code=None, result_desc="still")

        assert reconcile(payment) == "still-processing"

        payment.refresh_from_db()
        assert payment.state == PaymentState.UNKNOWN
        assert payment.result_code is None

    def test_a_query_that_cannot_reach_safaricom_leaves_it_unresolved(self, held, fake_daraja):
        payment = push_for(held)
        fake_daraja.query_error = DarajaUnavailable("connection reset")

        assert reconcile(payment) == "query-failed"

        payment.refresh_from_db()
        assert payment.state == PaymentState.UNKNOWN

    def test_every_attempt_is_counted(self, held, fake_daraja):
        payment = push_for(held)
        fake_daraja.query_error = DarajaUnavailable("reset")
        reconcile(payment)
        fake_daraja.query_error = DarajaUnavailable("reset")
        reconcile(payment)

        payment.refresh_from_db()
        assert payment.query_attempts == 2
        assert payment.last_queried_at is not None

    def test_a_payment_that_already_has_a_verdict_is_not_asked_about(self, held, fake_daraja):
        from payments.callbacks import handle_callback
        from payments.tests.conftest import stk_callback

        payment = push_for(held)
        handle_callback(stk_callback(payment.checkout_request_id))
        # The callback loaded its own row and locked it, so this one is stale.
        # The worker re-reads too — `reconcile_payment` fetches by id — which is
        # what makes the check below a real guard rather than an artefact.
        payment.refresh_from_db()

        assert reconcile(payment) == "already-resolved"
        assert fake_daraja.queries == []

    def test_the_callback_and_the_query_settle_through_the_same_function(self):
        """One path from "the money is real" to "the booking is confirmed", and
        it does not care how we found out. Asserted on the source rather than
        on behaviour, because the duplication this prevents would pass every
        behavioural test right up until the two drifted."""
        import inspect

        from payments import callbacks
        from payments import reconcile as reconcile_module

        assert "confirm_from_result" in inspect.getsource(callbacks)
        assert "confirm_from_result" in inspect.getsource(reconcile_module)


class TestTheTwoSchedules:
    def test_the_eta_task_is_for_timeliness(self, held, fake_daraja):
        """Queued on commit at `PAYMENT_QUERY_AFTER`. Runs eagerly here, so
        what is observable is that it was scheduled and that it is harmless."""
        payment = push_for(held)

        assert tasks.reconcile_payment(str(payment.pk)) in ("still-processing", "query-failed")

    def test_the_sweep_is_for_correctness(self, held, fake_daraja, settings):
        """Safe to lose and safe to run twice — the same rule as the hold
        release. Losing the broker costs a couple of minutes, not a payment
        nobody ever asks about."""
        payment = push_for(held)
        pushed_ago(payment, settings.PAYMENT_QUERY_AFTER.total_seconds() + 10)
        fake_daraja.next_query_result = QueryResult(result_code=0, result_desc="paid")

        assert tasks.sweep_unresolved_payments() == {"confirmed": 1}

        payment.refresh_from_db()
        assert payment.state == PaymentState.SUCCEEDED

    def test_the_reconciliation_sweep_is_not_the_hold_sweep(self):
        """Two mechanisms, deliberately. Named separately, scheduled
        separately, and they answer different questions."""
        from django.conf import settings as django_settings

        schedule = django_settings.CELERY_BEAT_SCHEDULE
        assert schedule["reconcile-unresolved-payments"]["task"] == (
            "payments.sweep_unresolved_payments"
        )
        assert schedule["release-expired-holds"]["task"] == "scheduling.sweep_expired_holds"
        assert (
            schedule["reconcile-unresolved-payments"]["schedule"]
            != schedule["release-expired-holds"]["schedule"]
        )

    def test_a_payment_nobody_can_resolve_is_escalated_not_dropped(self, held, settings):
        payment = push_for(held)
        from payments.machine import apply_payment_transition

        apply_payment_transition(payment, PaymentState.UNKNOWN)
        pushed_ago(payment, settings.PAYMENT_ESCALATE_AFTER.total_seconds() + 60)

        assert list(stale_payments()) == [payment]
        assert tasks.escalate_stale_payments() == 1

    def test_escalation_changes_no_state(self, held, settings):
        """It is a shout, not a decision. Somebody has to look at the money."""
        payment = push_for(held)
        from payments.machine import apply_payment_transition

        apply_payment_transition(payment, PaymentState.UNKNOWN)
        pushed_ago(payment, settings.PAYMENT_ESCALATE_AFTER.total_seconds() + 60)

        tasks.escalate_stale_payments()

        payment.refresh_from_db()
        assert payment.state == PaymentState.UNKNOWN
