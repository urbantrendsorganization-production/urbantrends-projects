"""The only function that writes `Payment.state`.

Same rule as `scheduling/transitions.py`, for the same reason: two places
writing one column is how a state ends up with the side effects of the other
path missing. On an appointment that costs a mis-drawn day view. On a payment it
costs money.

## The table

    initiated  -> pushed | push_failed | unknown | superseded
    pushed     -> succeeded | failed | cancelled_by_user | unknown | superseded
    unknown    -> succeeded | failed | cancelled_by_user | superseded
    superseded -> succeeded | failed | cancelled_by_user
    succeeded  -> orphaned

`initiated -> unknown` is the socket timeout on the Daraja call: the request
may or may not have reached Safaricom, and pretending we know is the mistake
that loses a client's money. It is why the row is written before the call.

`superseded -> succeeded` is the resend case. We stopped waiting; the client's
phone did not. See `payments/states.py`.

`succeeded -> orphaned` is the only edge out of a paid state, and it does not
un-pay anything — it records that there is no booking for the money to sit
against. Nothing transitions *out* of `orphaned` in this slice; slice 7's
re-point is what will.

## What this function does not do

It does not touch the appointment. `payments/settlement.py` owns that, and calls
this. Keeping them apart means the payment machine can be tested without a
calendar, and means there is exactly one place where "the money arrived" turns
into "the booking is confirmed".
"""

from django.db import transaction
from django.utils import timezone

from payments.models import Payment
from payments.states import AWAITING_RESULT_STATES, PaymentState

P = PaymentState

PAYMENT_TRANSITIONS = {
    P.INITIATED: frozenset({P.PUSHED, P.PUSH_FAILED, P.UNKNOWN, P.SUPERSEDED}),
    P.PUSHED: frozenset({P.SUCCEEDED, P.FAILED, P.CANCELLED_BY_USER, P.UNKNOWN, P.SUPERSEDED}),
    P.UNKNOWN: frozenset({P.SUCCEEDED, P.FAILED, P.CANCELLED_BY_USER, P.SUPERSEDED}),
    P.SUPERSEDED: frozenset({P.SUCCEEDED, P.FAILED, P.CANCELLED_BY_USER}),
    P.SUCCEEDED: frozenset({P.ORPHANED}),
    P.FAILED: frozenset(),
    P.CANCELLED_BY_USER: frozenset(),
    P.PUSH_FAILED: frozenset(),
    P.ORPHANED: frozenset(),
}

#: Reaching one of these means Safaricom has spoken. `resolved_at` is stamped.
RESULT_STATES = frozenset({P.SUCCEEDED, P.FAILED, P.CANCELLED_BY_USER})


class PaymentTransitionRefused(Exception):
    """Not a move this payment can make from where it is.

    A programming error, never a busy line. Distinct from a *failed payment*,
    which is an ordinary outcome with its own state.
    """

    def __init__(self, payment, to_state):
        self.payment = payment
        self.to_state = to_state
        super().__init__(
            f"A payment that is {payment.get_state_display().lower()} "
            f"cannot become {P(to_state).label.lower()}."
        )


def apply_payment_transition(payment, to_state, *, now=None, **fields):
    """Move one payment, with its bookkeeping. Returns it.

    `fields` are written alongside the state — `checkout_request_id`,
    `result_code`, `mpesa_receipt` and so on — in the same `update_fields`, so
    a state and the evidence for it can never land in two separate writes with
    a crash in between.

    Idempotent on the state it is already in, so a reconciliation query and a
    callback that arrive within the same second do not fight.
    """
    now = now or timezone.now()
    to_state = P(to_state)

    if payment.state == to_state:
        # The query said "paid" a beat before the callback did, or Safaricom
        # retried into a gap. Not an error, and the second one must not
        # re-stamp `resolved_at` to a later time.
        return payment

    if to_state not in PAYMENT_TRANSITIONS.get(payment.state, frozenset()):
        raise PaymentTransitionRefused(payment, to_state)

    update = ["state", "updated_at"]
    payment.state = to_state
    for name, value in fields.items():
        setattr(payment, name, value)
        update.append(name)

    if to_state == P.PUSHED and payment.pushed_at is None:
        payment.pushed_at = now
        update.append("pushed_at")

    if to_state in RESULT_STATES and payment.resolved_at is None:
        payment.resolved_at = now
        update.append("resolved_at")

    with transaction.atomic():
        payment.save(update_fields=list(dict.fromkeys(update)))
    return payment


def record_discrepancy(payment):
    """A second, *conflicting* result for the same CheckoutRequestID.

    The original is never touched. Safaricom does sometimes send two different
    verdicts for one request, and silently applying the later one is how a
    confirmed booking becomes unconfirmed after the client has already been
    told it was fine. This bumps a counter so the row surfaces, and
    `MpesaCallback` keeps both bodies.
    """
    payment.discrepancy_count += 1
    payment.save(update_fields=["discrepancy_count", "updated_at"])
    return payment


def open_payment_for(appointment):
    """The push we are currently waiting on for this appointment, if any."""
    from payments.states import NON_TERMINAL_STATES

    return (
        Payment.objects.for_org(appointment.organization_id)
        .filter(appointment=appointment, state__in=NON_TERMINAL_STATES)
        .first()
    )


def awaiting_result_for(appointment):
    """Every push against this appointment that could still be answered.

    Wider than `open_payment_for`: it includes superseded pushes, which are
    exactly the ones that make a resend dangerous and a late callback possible.
    """
    return Payment.objects.for_org(appointment.organization_id).filter(
        appointment=appointment, state__in=AWAITING_RESULT_STATES, result_code__isnull=True
    )
