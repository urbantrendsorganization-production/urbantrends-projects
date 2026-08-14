"""The payment worker jobs. Three, and one of them is a backstop.

The same split slice 5 established for holds, applied to money:

- `reconcile_payment` is scheduled per payment with an `eta`, for
  **timeliness**. It fires roughly ninety seconds after the push, which is
  about when a callback that was coming should have come.
- `sweep_unresolved_payments` runs from Beat, for **correctness**. It catches
  every payment the `eta` task lost — a restarted broker, a redeployed worker,
  a row whose task id nobody kept.
- `escalate_stale_payments` is the end of the line: past twenty-four hours with
  no verdict, a human is told rather than the row being retried forever.

**This is a separate mechanism from `scheduling.sweep_expired_holds`**, on its
own schedule, and that is deliberate. The hold sweep decides whether a slot goes
back on offer; this decides what happened to money. A single job doing both
would mean a slow M-Pesa holding the calendar hostage, or a busy calendar
skipping a payment.

Both sweeps obey the same rule as slice 5's: **safe to lose, safe to run
twice.** Every task re-reads its row, and `apply_payment_transition` is
idempotent on the state it is already in.

Never log a phone number here — CLAUDE.md §5. The support code is the trace.
"""

import logging

from celery import shared_task
from django.conf import settings

from payments.models import Payment
from payments.reconcile import reconcile, stale_payments, unresolved_payments

logger = logging.getLogger(__name__)


@shared_task(name="payments.reconcile_payment")
def reconcile_payment(payment_id):
    """Ask Safaricom about one payment, if it still needs asking about."""
    payment = (
        Payment.objects.unscoped()
        .select_related("appointment", "appointment__shop", "appointment__client")
        .filter(pk=payment_id)
        .first()
    )
    if payment is None:
        return "gone"
    if payment.has_result:
        # The callback beat us to it. The ordinary case, not the exception.
        return "already-resolved"
    if payment.query_attempts >= settings.PAYMENT_QUERY_MAX_ATTEMPTS:
        return "exhausted"
    return reconcile(payment)


@shared_task(name="payments.sweep_unresolved_payments")
def sweep_unresolved_payments():
    """The backstop. Every two minutes, from Beat.

    Deliberately dumb, like the hold sweep: one indexed query, then the same
    `reconcile` the scheduled task uses. The working set is "pushes older than
    ninety seconds with no verdict", which on a real shop is a handful of rows
    and usually none.
    """
    results = {}
    for payment in unresolved_payments()[: settings.PAYMENT_SWEEP_BATCH]:
        verb = reconcile(payment)
        results[verb] = results.get(verb, 0) + 1
    if results:
        logger.info("payment reconciliation sweep: %s", results)
    return results


@shared_task(name="payments.escalate_stale_payments")
def escalate_stale_payments():
    """Say out loud that a payment has been unresolved for a day.

    Does not change any state. A payment nobody can resolve automatically is a
    phone call, and the point of this task is that the phone call is prompted
    by us rather than by the client turning up at the shop.
    """
    stale = list(stale_payments())
    for payment in stale:
        logger.error(
            "payment %s has been unresolved for over %s — needs a human",
            payment.support_code,
            settings.PAYMENT_ESCALATE_AFTER,
        )
    return len(stale)
