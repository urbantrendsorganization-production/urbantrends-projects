"""Asking Safaricom what happened, instead of waiting to be told.

This is the answer to case 3 — the callback that never arrives — and it is the
part of the design that idempotency cannot supply.

Without a query, "no callback" and "no payment" are the same observation. The
hold sweep would release a slot that somebody had already paid for, the money
would sit in the paybill against a cancelled booking, and nothing anywhere would
notice: no error, no log line, no queue. The client finds out at the door.

So the rule is: **we do not wait to be told, we go and ask.** The reconciliation
query is a separate mechanism from the hold sweep — a different task, a
different schedule, a different failure mode — because they answer different
questions. The sweep decides whether a *slot* goes back on offer. The query
decides what happened to *money*. Conflating them would mean a slow M-Pesa held
the calendar hostage, or a busy calendar skipped a payment.

A result found this way settles exactly as a callback does, through
`payments/settlement.confirm_from_result`. There is one path from "the money is
real" to "the booking is confirmed", and it does not care how we found out.
"""

import logging

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from payments.daraja import DarajaRejected, DarajaUnavailable, get_client
from payments.machine import apply_payment_transition
from payments.models import Payment
from payments.settlement import confirm_from_result
from payments.states import AWAITING_RESULT_STATES, OrphanReason, PaymentState

logger = logging.getLogger(__name__)


def unresolved_payments(*, now=None):
    """The working set: pushed, no verdict, and old enough to be worth asking.

    `.unscoped()` — a worker has no request and therefore no organization, and
    a reconciliation that had to be told which tenant to look at is one nobody
    runs for a new tenant.
    """
    now = now or timezone.now()
    return (
        Payment.objects.unscoped()
        .filter(
            state__in=AWAITING_RESULT_STATES,
            result_code__isnull=True,
            checkout_request_id__isnull=False,
            pushed_at__lte=now - settings.PAYMENT_QUERY_AFTER,
            query_attempts__lt=settings.PAYMENT_QUERY_MAX_ATTEMPTS,
        )
        .select_related("appointment", "appointment__shop", "appointment__client")
        .order_by("pushed_at")
    )


def reconcile(payment, *, now=None):
    """Ask about one payment and act on the answer. Returns a short verb."""
    now = now or timezone.now()

    if payment.has_result:
        return "already-resolved"

    payment.query_attempts += 1
    payment.last_queried_at = now
    payment.save(update_fields=["query_attempts", "last_queried_at", "updated_at"])

    try:
        result = get_client().query(payment.checkout_request_id)
    except (DarajaUnavailable, DarajaRejected) as exc:
        logger.warning(
            "reconciliation query failed for %s: %s", payment.support_code, type(exc).__name__
        )
        _mark_unknown(payment, now=now)
        return "query-failed"

    if result.result_code is None:
        # Safaricom answered and said "still processing". A real answer, and
        # not a failure: it means ask again, which the sweep will.
        _mark_unknown(payment, now=now)
        return "still-processing"

    facts = {"result_code": result.result_code, "result_desc": result.result_desc[:255]}
    if result.result_code == 0:
        # A query never returns the receipt number. The row records that the
        # money is real and where we learned it; the receipt arrives if the
        # callback ever turns up, and the support code is what the client and
        # the shop actually quote at each other.
        facts["mpesa_receipt"] = f"(via query {payment.support_code})"
        facts["paid_at"] = now
        logger.warning(
            "payment %s settled by reconciliation, not by callback", payment.support_code
        )

    # Locked, and `has_result` re-read under the lock — the same reasoning as
    # `callbacks._process`, which this path deliberately shares a settlement
    # function with. Without it: a callback commits FAILED while the query above
    # is in flight, this function still holds the stale in-memory row that says
    # PUSHED, and `settle_succeeded` overwrites a real verdict with a racing one.
    # The query is outside the lock; only the decision is inside it.
    with transaction.atomic():
        # `of=("self",)` for the reason `callbacks._process` documents: the
        # appointment's client is nullable, so `select_related` reaches it
        # through a LEFT JOIN and Postgres refuses to lock the nullable side.
        locked = (
            Payment.objects.unscoped()
            .select_for_update(of=("self",))
            .select_related("appointment", "appointment__shop", "appointment__client")
            .get(pk=payment.pk)
        )
        if locked.has_result:
            return "already-resolved"
        settled = confirm_from_result(
            locked, succeeded=result.result_code == 0, facts=facts, now=now
        )

    _notify(locked, settled)
    return settled


def _mark_unknown(payment, *, now):
    if payment.state in (PaymentState.PUSHED, PaymentState.INITIATED):
        apply_payment_transition(payment, PaymentState.UNKNOWN, now=now)


def _notify(payment, settled):
    """Same three messages as the callback path. After commit, by a worker."""
    from notifications.service import queue_message
    from notifications.templates import Template

    if settled == "confirmed":
        queue_message(payment.appointment, Template.BOOKING_CONFIRMED, payment=payment)
    elif settled == "orphaned" and payment.orphan_reason == OrphanReason.SLOT_LOST:
        # Only the lost race. See the same branch in `payments/callbacks.py`.
        queue_message(payment.appointment, Template.SLOT_LOST, payment=payment)


def stale_payments(*, now=None):
    """Past `PAYMENT_ESCALATE_AFTER` with no verdict. A human's problem now.

    Not silently dropped, and not retried forever either. Four queries over a
    few minutes have already failed; the twentieth will not be the one that
    works, and a row that keeps being retried is a row nobody looks at.
    """
    now = now or timezone.now()
    cutoff = now - settings.PAYMENT_ESCALATE_AFTER
    # `pushed_at` OR `created_at`, because the worst case has no `pushed_at`.
    # A socket timeout on `initiate_push` raises `DarajaUnavailable` and moves
    # the row INITIATED -> UNKNOWN, and only the PUSHED transition ever stamps
    # `pushed_at`. Filtering on `pushed_at` alone excludes NULL, so the exact
    # case UNKNOWN exists for — the prompt may be on the client's phone right
    # now and we have no CheckoutRequestID to ask about — was never queried
    # (unavoidable) and never escalated to a human either (not unavoidable).
    # The row also stays non-terminal forever, holding
    # `one_open_payment_per_appointment` against that booking for good.
    return Payment.objects.unscoped().filter(
        Q(pushed_at__lte=cutoff) | Q(pushed_at__isnull=True, created_at__lte=cutoff),
        state=PaymentState.UNKNOWN,
        result_code__isnull=True,
    )
