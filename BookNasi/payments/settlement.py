"""What happens to the booking when the money is real.

The one place "the deposit arrived" becomes "the appointment is confirmed". It
is deliberately not inside `callbacks.py`, because the same decision has to be
reachable from the reconciliation query — a payment discovered by *asking*
Safaricom must settle exactly as one discovered by being told.

## The five cases, in one function

`settle_succeeded` is the whole of §B's hard part. Which branch runs is decided
by two facts already on the appointment, and neither of them is new:

1. `status` — where the booking is now.
2. `hold_released_at` — set when a hold ran **out**, cleared when a client or a
   staff member cancelled **on purpose**. Slice 5 added it for the abandonment
   cooldown in `scheduling/abuse.py`; it turns out to be exactly the
   discriminator the late-callback case needs, so no column was added here.

    pending_payment                  -> confirm. The ordinary path.
    cancelled, hold_released_at set  -> the late callback. Try to re-enter the
                                        exclusion constraint:
                                          it holds  -> confirm (case 1)
                                          SlotTaken -> orphan, slot_lost (case 2)
    cancelled, hold_released_at null -> somebody cancelled deliberately.
                                        Orphan; do **not** resurrect a booking
                                        the client killed.
    confirmed / in_progress / …      -> already settled by another payment, or
                                        the booking has already run. Orphan.

Orphaning does not un-pay anything. It records that the money has no booking to
sit against and puts the row in the exception queue, which is the shop's cue to
phone the client. Slice 7 adds the client-side remedy — pick another time and
carry the deposit — which is why `Payment.appointment` is reassignable and
`PaymentMove` exists already.
"""

import logging

from django.db import transaction
from django.utils import timezone

from payments.machine import PaymentTransitionRefused, apply_payment_transition
from payments.states import OrphanReason, PaymentState
from scheduling.booking import SlotTaken
from scheduling.statuses import AppointmentStatus
from scheduling.transitions import Actor, apply_transition

logger = logging.getLogger(__name__)

S = AppointmentStatus


def settle_succeeded(payment, callback_facts, *, now=None):
    """Apply a paid result. Returns the appointment status it produced.

    `callback_facts` is a dict of `mpesa_receipt`, `paid_at`, `result_code`,
    `result_desc` — the same shape whether it came from a callback body or from
    a `stkpushquery` response, which is what lets both paths share this.

    Never raises for an ordinary outcome. `SlotTaken` is caught here and turned
    into an orphan, because from the *payment's* point of view losing the race
    is a result, not an error.
    """
    now = now or timezone.now()
    appointment = payment.appointment

    apply_payment_transition(payment, PaymentState.SUCCEEDED, now=now, **callback_facts)

    if appointment.status == S.PENDING_PAYMENT:
        # The ordinary path, and the only one that runs in the happy case.
        apply_transition(appointment, S.CONFIRMED, now=now, actor=Actor.SYSTEM)
        return "confirmed"

    if appointment.status == S.CANCELLED:
        if appointment.hold_released_at is None:
            # The client pressed cancel, or the shop did. A payment landing
            # afterwards is a refund case. Re-confirming here would resurrect a
            # booking somebody deliberately killed — the worst possible way to
            # be helpful.
            return _orphan(payment, OrphanReason.BOOKING_CANCELLED, now=now)
        try:
            # Case 1. The hold expired, the money arrived late, and the handoff
            # is explicit that this must still confirm. Re-entering
            # ACTIVE_STATUSES puts the row back under the exclusion constraint,
            # so the database decides whether the slot is still there.
            apply_transition(appointment, S.CONFIRMED, now=now, actor=Actor.SYSTEM)
        except SlotTaken:
            # Case 2. Somebody took it while the payment was in flight. This is
            # `slotLost`, and it is the only branch here that generates a phone
            # call.
            return _orphan(payment, OrphanReason.SLOT_LOST, now=now)
        return "confirmed"

    if appointment.status in (S.CONFIRMED, S.IN_PROGRESS):
        # Another payment already settled this booking — a resend where both
        # prompts were answered. Two deposits for one haircut.
        return _orphan(payment, OrphanReason.ALREADY_PAID, now=now)

    # completed, no_show. Money for a booking that has already run.
    return _orphan(payment, OrphanReason.BOOKING_MOVED_ON, now=now)


def settle_failed(payment, callback_facts, *, now=None):
    """Apply a non-paid result. The hold is left alone.

    Deliberately no appointment side effect. The design's screen 7 keeps the
    countdown alive through a failure — the client retries inside whatever is
    left of the TTL — so a failed payment must not release the slot. The hold
    expires on its own schedule if nothing else pays for it, which is what the
    sweep is for.
    """
    now = now or timezone.now()
    state = (
        PaymentState.CANCELLED_BY_USER
        if callback_facts.get("result_code") == 1032
        else PaymentState.FAILED
    )
    return apply_payment_transition(payment, state, now=now, **callback_facts)


def _orphan(payment, reason, *, now):
    apply_payment_transition(payment, PaymentState.ORPHANED, now=now, orphan_reason=reason)
    # WARNING, not INFO, and no phone number: this is money sitting with the
    # shop against no booking, and somebody has to ring somebody.
    logger.warning(
        "payment %s orphaned (%s) — appointment %s",
        payment.support_code,
        reason,
        payment.appointment_id,
    )
    return "orphaned"


def confirm_from_result(payment, *, succeeded, facts, now=None):
    """The single entry point both the callback and the query use.

    Wrapped in one transaction so that a payment row and the appointment it
    settles can never land separately. The SMS is dispatched by the caller,
    **after** this commits — see `payments/callbacks.py`.
    """
    now = now or timezone.now()
    with transaction.atomic():
        if succeeded:
            return settle_succeeded(payment, facts, now=now)
        settle_failed(payment, facts, now=now)
        return "failed"


def supersede(payment, *, now=None):
    """Stop waiting on a push because the client asked for another one.

    Terminal for our bookkeeping and not for Safaricom's: a result arriving on
    a superseded push is still applied, because if the client entered their PIN
    the money genuinely moved. See `payments/states.py`.
    """
    now = now or timezone.now()
    try:
        return apply_payment_transition(payment, PaymentState.SUPERSEDED, now=now)
    except PaymentTransitionRefused:  # pragma: no cover — a guard, not a path
        return payment
