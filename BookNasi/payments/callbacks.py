"""Processing one M-Pesa callback. Exactly once, whatever Safaricom does.

CLAUDE.md §5: "Callbacks must be idempotent. Safaricom retries. Unique
constraint on the checkout request ID; process exactly once."

The unique constraint is the floor. On top of it:

**Every body is recorded before anything is decided.** `MpesaCallback` is
append-only and takes the raw payload with the payer's number redacted, whether
we go on to apply it, ignore it or find no payment for it. Idempotency dedupes
*processing*; evidence is a separate job, and the duplicate we correctly refused
to re-apply is exactly the row somebody needs when a client says they were
charged twice.

**The payment row is locked, not merely read.** Two retries arriving in the same
second both pass a `payment.has_result` check made outside a lock. `SELECT …
FOR UPDATE` inside the transaction is what makes "exactly once" true rather than
usually true — the same reasoning as the exclusion constraint in §4, applied to
money instead of chairs.

**First result wins, and a conflicting second is recorded, never applied.**
Safaricom does sometimes send two different verdicts for one CheckoutRequestID.
Silently applying the later one turns a confirmed booking — one the client has
already been told about by SMS — into an unconfirmed one. So the original stands,
`discrepancy_count` goes up, and both bodies are on file.

**Nothing escapes.** An exception leaving this function is a non-200, and a
non-200 is a Safaricom retry, which turns one malformed body into a retry storm
and one bug into an outage. Every path returns an outcome.

**No payload at INFO.** Ids, result codes and outcomes only.
"""

import logging

from django.db import transaction
from django.utils import timezone

from payments.machine import record_discrepancy
from payments.messages import client_message
from payments.models import MpesaCallback, Payment
from payments.parsing import MalformedCallback, parse_callback, redact
from payments.settlement import confirm_from_result
from payments.states import CallbackOutcome, OrphanReason

logger = logging.getLogger(__name__)


def handle_callback(body, *, now=None):
    """Process one callback body. Returns a `CallbackOutcome`. Never raises."""
    now = now or timezone.now()
    safe_body = redact(body)

    try:
        parsed = parse_callback(body)
    except MalformedCallback as exc:
        MpesaCallback.objects.create(
            payload=safe_body,
            outcome=CallbackOutcome.MALFORMED,
            result_desc=str(exc)[:255],
        )
        logger.warning("malformed m-pesa callback: %s", exc)
        return CallbackOutcome.MALFORMED

    try:
        return _process(parsed, safe_body, now=now)
    except Exception:  # noqa: BLE001 — see the module docstring on non-200s
        # Recorded rather than swallowed: the body is already on file above in
        # every other branch, and this one must leave a trace too.
        logger.exception("m-pesa callback %s failed to process", parsed.checkout_request_id)
        MpesaCallback.objects.create(
            checkout_request_id=parsed.checkout_request_id,
            merchant_request_id=parsed.merchant_request_id,
            result_code=parsed.result_code,
            result_desc=parsed.result_desc,
            payload=safe_body,
            outcome=CallbackOutcome.MALFORMED,
        )
        return CallbackOutcome.MALFORMED


def _process(parsed, safe_body, *, now):
    settled = None
    with transaction.atomic():
        # `.unscoped()` for the reason the public views use it: Safaricom has no
        # organization and neither does this request. The CheckoutRequestID is
        # the scope — it resolves to exactly one payment in one tenant.
        payment = (
            Payment.objects.unscoped()
            # `of=("self",)` locks the payment row and nothing else. Without it
            # Postgres refuses outright — `Appointment.client` is nullable, so
            # `select_related` reaches it through a LEFT JOIN, and "FOR UPDATE
            # cannot be applied to the nullable side of an outer join". The
            # payment is the only row two concurrent retries contend for
            # anyway; locking the appointment as well would put a callback in
            # the way of the staff day view.
            .select_for_update(of=("self",))
            .select_related("appointment", "appointment__shop", "appointment__client")
            .filter(checkout_request_id=parsed.checkout_request_id)
            .first()
        )

        if payment is None:
            # Kept. An unmatched callback is either a push we lost the row for
            # or somebody probing the endpoint, and both are worth being able
            # to see later.
            _record(parsed, safe_body, CallbackOutcome.UNMATCHED, payment=None)
            logger.warning("m-pesa callback for unknown %s", parsed.checkout_request_id)
            return CallbackOutcome.UNMATCHED

        if payment.has_result:
            if payment.result_code == parsed.result_code:
                _record(parsed, safe_body, CallbackOutcome.DUPLICATE, payment=payment)
                return CallbackOutcome.DUPLICATE
            # Two different verdicts for one request. The first stands.
            previous = payment.result_code
            record_discrepancy(payment)
            _record(
                parsed,
                safe_body,
                CallbackOutcome.DISCREPANCY,
                payment=payment,
                previous_result_code=previous,
            )
            logger.error(
                "m-pesa sent a conflicting result for %s: had %s, got %s — not applied",
                payment.support_code,
                previous,
                parsed.result_code,
            )
            return CallbackOutcome.DISCREPANCY

        facts = {
            "result_code": parsed.result_code,
            "result_desc": parsed.result_desc,
        }
        if parsed.succeeded:
            # A success with no `CallbackMetadata` block parses to an empty
            # receipt, which violates `succeeded_payment_has_a_receipt` and
            # unwinds this whole transaction — taking the evidence row written
            # below with it, and recording the body as MALFORMED, an outcome
            # that did not happen. The money is real either way, so the row
            # records where we learned it, exactly as `reconcile` does for the
            # query path, which never returns a receipt at all.
            facts["mpesa_receipt"] = parsed.receipt or f"(no receipt {payment.support_code})"
            facts["paid_at"] = parsed.paid_at or now

        settled = confirm_from_result(payment, succeeded=parsed.succeeded, facts=facts, now=now)
        _record(parsed, safe_body, CallbackOutcome.APPLIED, payment=payment)

    # After the commit, always. A slow SMS gateway inside the transaction would
    # hold a row lock for the length of an HTTP request to a third party, and a
    # slow response to Safaricom is a Safaricom retry — the exact thing the
    # idempotency above exists to survive, made routine instead of rare.
    #
    # Contained, too. A messaging failure is not a callback failure: the money
    # is already committed and the booking already confirmed, so letting it
    # reach the handler above would record this body as MALFORMED — a false
    # entry in the one table whose job is to be evidence — and report an
    # outcome that did not happen.
    try:
        _notify(payment, settled, parsed)
    except Exception:  # noqa: BLE001 — see above
        logger.exception("could not queue the message for %s", payment.support_code)
    logger.info(
        "m-pesa callback applied for %s: result=%s outcome=%s",
        payment.support_code,
        parsed.result_code,
        settled,
    )
    return CallbackOutcome.APPLIED


def _record(parsed, safe_body, outcome, *, payment, previous_result_code=None):
    MpesaCallback.objects.create(
        checkout_request_id=parsed.checkout_request_id,
        merchant_request_id=parsed.merchant_request_id,
        result_code=parsed.result_code,
        result_desc=parsed.result_desc,
        payload=safe_body,
        outcome=outcome,
        payment=payment,
        previous_result_code=previous_result_code,
    )


def _notify(payment, settled, parsed):
    """Queue the SMS this outcome earns. Dispatched on commit, sent by a worker.

    Three messages ship in this slice and no others — see
    `notifications/templates.py` for where the line is drawn and why reminders
    are slice 8.
    """
    from notifications.service import queue_message
    from notifications.templates import Template

    if settled == "confirmed":
        queue_message(payment.appointment, Template.BOOKING_CONFIRMED, payment=payment)
    elif settled == "orphaned":
        # Only the lost race earns this message. `settle_succeeded` orphans for
        # four different reasons and the other three all describe a booking that
        # is fine: ALREADY_PAID is a resend where both prompts were answered,
        # BOOKING_CANCELLED is a payment against a booking the client killed,
        # BOOKING_MOVED_ON is one that has already run. Telling any of those
        # clients "your slot was taken while the payment was going through"
        # about an intact, confirmed booking is a worse support call than the
        # one screen 8 exists for. The shop still gets the WARNING from
        # `_orphan` and the row still sits in the exception queue.
        if payment.orphan_reason == OrphanReason.SLOT_LOST:
            queue_message(payment.appointment, Template.SLOT_LOST, payment=payment)
        else:
            logger.debug(
                "no client message for %s orphaned as %s",
                payment.support_code,
                payment.orphan_reason,
            )
    elif not parsed.succeeded:
        # No SMS for an ordinary failed payment. The client is on the screen
        # watching it happen, the design's screen 7 tells them there and then,
        # and an SMS saying "your payment failed" to somebody who is about to
        # retry is noise they are paying for. See notifications/templates.py.
        logger.debug("no message for failed payment %s", payment.support_code)


def failure_message(payment):
    """What screen 7 shows. Safe copy, not Safaricom's raw ResultDesc."""
    return client_message(payment.result_code)
