"""Starting a push, and resending one.

## The row comes first

`Payment` is written in state `INITIATED` **before** the Daraja call, not after
it. The window this closes is small and expensive: our request reaches
Safaricom, the prompt lands on the client's phone, and our socket times out
before the response comes back. With the row written first, the reconciliation
query has a payment to attach that result to. With it written after, the money
moves against a booking that has no record of ever having asked for it.

That is also why a socket timeout becomes `UNKNOWN` rather than `PUSH_FAILED`.
The two mean opposite things — "no money will move" and "we cannot tell" — and
collapsing them loses a client's deposit quietly.

## Resend

The design draws "Resend the prompt" on screen 5 and "try again" on screen 7,
and both are a second push against one booking. Three things bound it:

1. **Rate.** `STK_RESEND_MAX` per appointment, `STK_RESEND_MIN_INTERVAL_SECONDS`
   apart. Safaricom's own prompt lives about a minute; a resend faster than that
   just puts two prompts on one phone.
2. **The grace ceiling.** A resend is refused once `hold_expires_at +
   HOLD_GRACE_MINUTES` has passed. It cannot extend the hold, because the
   ceiling is derived from a timestamp nothing writes — see
   `scheduling/holds.grace_ceiling`. The button is not a way to hold a slot for
   free.
3. **One open payment.** The previous push is superseded first, so the database
   constraint `one_open_payment_per_appointment` is satisfied by exactly one
   row. The superseded one can still be answered — the client's phone still has
   the first prompt on it — and if both are paid, the second lands in the
   exception queue as `already_paid`.
"""

import logging

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from payments import tills
from payments.daraja import (
    DarajaMisconfigured,
    DarajaRejected,
    DarajaUnavailable,
)
from payments.machine import apply_payment_transition, awaiting_result_for, open_payment_for
from payments.models import OPEN_PAYMENT_CONSTRAINT, Payment
from payments.settlement import supersede
from payments.states import PaymentState
from payments.support_codes import new_support_code
from scheduling.holds import grace_ceiling
from scheduling.statuses import AppointmentStatus

logger = logging.getLogger(__name__)


class PushRefused(Exception):
    """We will not send this prompt. The client is told why, and what to do.

    Distinct from `DarajaRejected` — that is Safaricom saying no, this is us.
    """

    def __init__(self, message, *, reason="", retry_after=None):
        self.reason = reason
        self.retry_after = retry_after
        super().__init__(message)


def _new_payment(appointment, phone, *, now):
    """The row, before the call. See the module docstring."""
    payment = Payment(
        appointment=appointment,
        amount=appointment.deposit_snapshot,
        phone=phone,
        state=PaymentState.INITIATED,
        support_code=new_support_code(),
    )
    try:
        with transaction.atomic():
            payment.save()
    except IntegrityError as exc:
        if OPEN_PAYMENT_CONSTRAINT in str(exc):
            # Two confirms in flight for one hold. The constraint decided; the
            # loser must not send a second prompt to the same phone.
            raise PushRefused(
                "An M-Pesa request is already on its way to that phone.",
                reason="push_in_flight",
            ) from exc
        raise
    return payment


def initiate_push(appointment, *, phone=None, now=None):
    """Send the deposit prompt for a held slot. Returns the `Payment`.

    Never raises for an ordinary failure: a Safaricom rejection and a Safaricom
    outage both come back as a payment row in a state that says so, because the
    client is looking at a screen and needs a sentence rather than a 500.
    """
    now = now or timezone.now()

    if appointment.status != AppointmentStatus.PENDING_PAYMENT:
        raise PushRefused("That booking is not waiting for a payment.", reason="not_holding")
    if appointment.deposit_snapshot < 1:
        # CLAUDE.md §5, at one more layer. A deposit-free service is not
        # publicly bookable, so a zero here means something upstream let one
        # through — and pushing KES 0 to Safaricom is a rejection anyway.
        raise PushRefused("That service has no deposit to pay.", reason="no_deposit")

    open_now = open_payment_for(appointment)
    if open_now is not None:
        raise PushRefused(
            "An M-Pesa request is already on its way to that phone.",
            reason="push_in_flight",
        )

    payment = _new_payment(appointment, phone or _payer(appointment), now=now)
    return _send(payment, appointment, now=now)


def _payer(appointment):
    if appointment.client is None:  # pragma: no cover — holds always have one
        raise PushRefused("No number to send the prompt to.", reason="no_number")
    return appointment.client.phone


def _send(payment, appointment, *, now):
    # The shop, not the process. Before slice 13 every push on a deployment went
    # to one shortcode read from the environment; a salon's deposits now reach
    # the salon (CLAUDE.md §1). `client_for` raises `ShopCannotCollect`, which is
    # a `DarajaMisconfigured` and so is caught below with the rest of "our
    # configuration is wrong, nothing moved, do not retry on a schedule".
    try:
        client = tills.client_for(appointment.shop)
    except DarajaMisconfigured as exc:
        logger.error("no m-pesa account for %s: %s", payment.support_code, exc)
        return apply_payment_transition(
            payment,
            PaymentState.PUSH_FAILED,
            now=now,
            result_desc=str(exc)[:255],
        )

    try:
        accepted = client.push(
            amount=payment.amount,
            phone=payment.phone,
            # What the client sees on their M-Pesa statement. The support code
            # rather than the appointment UUID: it is the only reference in this
            # product a human can read out loud.
            reference=payment.support_code,
            description=f"Deposit · {appointment.shop.name}",
        )
    except DarajaMisconfigured as exc:
        # Our problem, not Safaricom's. No prompt was sent, and — unlike
        # `DarajaUnavailable` — none should be retried, because the retry would
        # be wrong in the same way. `PUSH_FAILED` rather than `UNKNOWN` keeps it
        # out of the reconciliation sweep, which exists for money that may have
        # moved; nothing moved here.
        #
        # ERROR, not WARNING: a till deployment missing its till number would
        # otherwise fail one booking at a time, quietly, and the shop would find
        # out from a client who never got a prompt.
        logger.error("stk push misconfigured for %s: %s", payment.support_code, exc)
        return apply_payment_transition(
            payment,
            PaymentState.PUSH_FAILED,
            now=now,
            result_desc=str(exc)[:255],
        )
    except DarajaRejected as exc:
        # An answer. No prompt was sent and no money will move.
        logger.warning("stk push rejected for %s: %s", payment.support_code, exc.code)
        return apply_payment_transition(
            payment,
            PaymentState.PUSH_FAILED,
            now=now,
            result_desc=str(exc)[:255],
        )
    except DarajaUnavailable as exc:
        # Not an answer. The prompt may be on the phone right now. This is what
        # `UNKNOWN` and the reconciliation query exist for.
        logger.warning("stk push unresolved for %s: %s", payment.support_code, type(exc).__name__)
        return apply_payment_transition(
            payment,
            PaymentState.UNKNOWN,
            now=now,
            result_desc="No answer from M-Pesa when sending the prompt.",
        )

    payment = apply_payment_transition(
        payment,
        PaymentState.PUSHED,
        now=now,
        checkout_request_id=accepted.checkout_request_id,
        merchant_request_id=accepted.merchant_request_id,
    )
    _schedule_reconciliation(payment)
    return payment


def _schedule_reconciliation(payment):
    """Queue the query that closes the never-arrives case.

    Same shape as slice 5's hold release, and for the same reason: this `eta`
    task is for **timeliness** and `sweep_unresolved_payments` is for
    **correctness**. Losing the broker costs a couple of minutes, not a
    payment nobody ever asks about.
    """
    from payments.tasks import reconcile_payment

    eta = timezone.now() + settings.PAYMENT_QUERY_AFTER
    transaction.on_commit(lambda: reconcile_payment.apply_async(args=[str(payment.pk)], eta=eta))


def resend_push(appointment, *, phone=None, now=None):
    """A second prompt for the same booking. Bounded three ways — see the
    module docstring."""
    now = now or timezone.now()

    if appointment.status != AppointmentStatus.PENDING_PAYMENT:
        raise PushRefused("That booking is not waiting for a payment.", reason="not_holding")

    ceiling = grace_ceiling(appointment)
    if ceiling is not None and now >= ceiling:
        # The hold is over. Resending would put a prompt on a phone for a slot
        # that is already back in the list — the client pays for nothing.
        raise PushRefused("That hold has run out. Pick a time again.", reason="hold_over")

    attempts = Payment.objects.for_org(appointment.organization_id).filter(appointment=appointment)
    sent = attempts.count()
    if sent > settings.STK_RESEND_MAX:
        raise PushRefused(
            "We've sent that prompt a few times already. "
            f"Dial {settings.USSD_FALLBACK} on the phone, or call the shop.",
            reason="resend_limit",
        )

    latest = attempts.order_by("-created_at").first()
    if latest is not None and latest.created_at is not None:
        elapsed = (now - latest.created_at).total_seconds()
        wait = settings.STK_RESEND_MIN_INTERVAL_SECONDS - elapsed
        if wait > 0:
            # Two prompts inside a minute is two prompts on one phone, and the
            # client answers the wrong one.
            raise PushRefused(
                f"Give it {int(wait) + 1} more seconds — the first prompt may still arrive.",
                reason="too_soon",
                retry_after=int(wait) + 1,
            )

    # Stop waiting on whatever is open, so the one-open-payment constraint is
    # satisfied. `awaiting_result_for` is deliberately not touched beyond this:
    # a superseded push can still be answered, and if it is, the money is real.
    open_now = open_payment_for(appointment)
    if open_now is not None:
        supersede(open_now, now=now)

    payment = _new_payment(appointment, phone or _payer(appointment), now=now)
    return _send(payment, appointment, now=now)


def outstanding_push(appointment):
    """Is a prompt in flight? Read by the public hold endpoint.

    The countdown screen has to be able to say "still checking with M-Pesa"
    instead of "expired" — CLAUDE.md §10, invariant 3, applied to the grace
    window. A timer that reaches zero while the server is still holding the
    slot is exactly the unexplained failure the invariant exists to prevent.
    """
    return awaiting_result_for(appointment).exists()
