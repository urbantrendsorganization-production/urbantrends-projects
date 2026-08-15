"""Payment state, and the three sets derived from it.

Kept in its own module for the same reason `scheduling/statuses.py` is: the
partial unique index, the transition table, the reconciliation query and the
public serializer all import the *same* objects. Two literal lists that happen
to agree today is how a payment ends up unreconcilable.

## Two machines, not one

The appointment machine already exists (`scheduling/transitions.py`). This is
the payment machine, and the two are deliberately separate. Conflating them is
what makes late callbacks hard to reason about: "the money succeeded" and "the
booking is confirmed" are different facts that arrive at different times and
can disagree, and a design that cannot represent the disagreement has to
pretend one of them did not happen.

One appointment has **many payments over time** — the design's screen 5 draws
"Resend the prompt" and screen 7 draws "try again", and both are a second STK
push against the same booking. At most one of them may be non-terminal at a
time, which the database enforces (`one_open_payment_per_appointment`).

## Terminal in two different senses

`NON_TERMINAL_STATES` is about **us**: while a payment is in one of these, we
are still waiting and no other push may be started for that appointment.

`result_code IS NULL` is about **Safaricom**: no verdict has been applied yet.

These are not the same line, and `SUPERSEDED` is why. When a client asks for a
second prompt, we stop waiting on the first — so it leaves `NON_TERMINAL_STATES`
and the new push is allowed. But the first push may still be sitting on the
client's phone, and if they enter their PIN, real money moves. Superseding is
our bookkeeping decision, not Safaricom's, so a result that arrives afterwards
is still applied. That is why the duplicate rule is "first *result* wins"
rather than "first terminal state wins".
"""

from django.db import models


class PaymentState(models.TextChoices):
    #: Row written **before** the Daraja call. A push that succeeds while our
    #: HTTP response is lost still has a home, and the reconciliation query has
    #: something to find.
    INITIATED = "initiated", "Initiated"
    #: Safaricom accepted the push. We hold the CheckoutRequestID.
    PUSHED = "pushed", "Prompt sent"
    #: Rejected synchronously — bad shortcode, invalid MSISDN, throttled. No
    #: money moved and none will.
    PUSH_FAILED = "push_failed", "Could not send the prompt"
    #: Callback ResultCode 0. Receipt, amount and paid-at are on the row.
    SUCCEEDED = "succeeded", "Paid"
    #: Callback with a non-zero result. Carries Safaricom's ResultDesc verbatim.
    FAILED = "failed", "Failed"
    #: ResultCode 1032. Split from FAILED because the copy differs and "try a
    #: different number" is the wrong advice for somebody who pressed cancel.
    CANCELLED_BY_USER = "cancelled_by_user", "Cancelled on the phone"
    #: No callback, and the query was inconclusive too. Requeued, then escalated.
    UNKNOWN = "unknown", "Unresolved"
    #: We stopped waiting on this push because the client asked for another.
    #: A late result on it is still honoured — see the module docstring.
    SUPERSEDED = "superseded", "Superseded by a new prompt"
    #: Succeeded, but there is no booking to apply it to. The exception queue.
    ORPHANED = "orphaned", "Paid, no booking"


#: While a payment is in one of these, no second push may start for the same
#: appointment. Enforced by a partial unique index, not by a check in Python.
NON_TERMINAL_STATES = (
    PaymentState.INITIATED,
    PaymentState.PUSHED,
    PaymentState.UNKNOWN,
)

#: States a Safaricom verdict can still land on. `SUPERSEDED` is here on
#: purpose: we stopped waiting, the client's phone did not.
AWAITING_RESULT_STATES = (
    PaymentState.PUSHED,
    PaymentState.UNKNOWN,
    PaymentState.SUPERSEDED,
)

#: A verdict arrived and it was "paid". Two of them for one appointment means
#: somebody paid twice.
SETTLED_STATES = (PaymentState.SUCCEEDED, PaymentState.ORPHANED)


class OrphanReason(models.TextChoices):
    """Why a succeeded payment has no booking to sit against.

    Four reasons rather than one flag, because the remedy differs and the shop
    reads this off the exception queue before phoning the client.
    """

    #: The hold expired, the callback was late, and somebody else took the slot
    #: in between. The case the whole of §A was about.
    SLOT_LOST = "slot_lost", "Slot was taken while the payment was in flight"
    #: The client pressed cancel, or staff cancelled it. A payment landing
    #: afterwards is a refund, not a booking — re-confirming would resurrect
    #: something somebody deliberately killed.
    BOOKING_CANCELLED = "booking_cancelled", "Booking was cancelled"
    #: The appointment already had a succeeded payment. A resend where both
    #: prompts were answered.
    ALREADY_PAID = "already_paid", "Deposit was already paid"
    #: The appointment has moved on — completed, no-show, in progress. Money
    #: arriving for a booking that already happened.
    BOOKING_MOVED_ON = "booking_moved_on", "Booking had already run"


class CallbackOutcome(models.TextChoices):
    """What processing did with a raw callback. Recorded on every one."""

    APPLIED = "applied", "Applied"
    #: Same CheckoutRequestID, same result, already processed. Safaricom retries.
    DUPLICATE = "duplicate", "Duplicate, ignored"
    #: Same CheckoutRequestID, **different** result. Recorded, never applied.
    DISCREPANCY = "discrepancy", "Conflicting duplicate, recorded not applied"
    #: No payment with that CheckoutRequestID. Kept anyway — an unmatched
    #: callback is evidence, and throwing it away is how a dispute becomes
    #: unanswerable.
    UNMATCHED = "unmatched", "No matching payment"
    #: The body did not parse as an STK callback.
    MALFORMED = "malformed", "Unparseable"
