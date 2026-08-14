"""The payment row, the raw callback log, and the audit trail for a move.

Three tables, and the split between them is the design:

- `Payment` is what we believe about one STK push. Mutable, state-machined,
  written only through `payments/machine.py`.
- `MpesaCallback` is what Safaricom actually sent. Append-only, never updated,
  phone number redacted. Idempotency dedupes *processing*; this records
  *everything*, because a dispute six weeks later is answered by evidence and
  not by our opinion of what happened.
- `PaymentMove` is the audit row for re-pointing a payment at a different
  appointment. Slice 7 does the moving; the shape ships now so that slice needs
  no migration.

CLAUDE.md §5: never log full M-Pesa payloads with phone numbers. That applies to
this file too — `MpesaCallback.payload` is redacted on the way in, not on the
way out.
"""

from django.db import models
from django.db.models import Q

from core.models import OrgDerivedModel, TimeStampedModel
from payments.states import (
    NON_TERMINAL_STATES,
    CallbackOutcome,
    OrphanReason,
    PaymentState,
)

#: Matched by name where a duplicate CheckoutRequestID has to be told apart
#: from any other integrity failure — same reasoning as `booking.py`'s
#: constraint matching. A bare IntegrityError says nothing.
CHECKOUT_ID_CONSTRAINT = "one_payment_per_checkout_request"
OPEN_PAYMENT_CONSTRAINT = "one_open_payment_per_appointment"


class Payment(OrgDerivedModel):
    """One STK push and everything that happened to it.

    ## Why the appointment link is reassignable

    `appointment` is an ordinary mutable FK rather than a one-shot. Slice 7's
    remedy for `slotLost` is to re-point a succeeded payment at a different
    booking — the client's money is already verified, so no second push is
    needed — and every move writes a `PaymentMove` row. Building the column
    fixed and migrating it later would mean migrating live money records.

    It is **not** nullable. A payment always originates from a hold, so there is
    always an appointment it came from; "no booking to apply this to" is the
    `ORPHANED` state plus an `orphan_reason`, which keeps the history intact
    instead of cutting the link and losing where the money came from.
    """

    org_source = "appointment"

    appointment = models.ForeignKey(
        "scheduling.Appointment",
        on_delete=models.PROTECT,
        related_name="payments",
        help_text="Reassignable. Every change writes a PaymentMove.",
    )

    state = models.CharField(
        max_length=20,
        choices=PaymentState.choices,
        default=PaymentState.INITIATED,
        db_index=True,
    )

    #: Whole shillings, as everywhere. See shops/money.py. Snapshotted from the
    #: appointment's `deposit_snapshot` at push time, because the service's
    #: deposit rule may change between the push and the callback.
    amount = models.PositiveIntegerField()
    #: The number the prompt went to. Not necessarily the client's stored
    #: number: the design's screen 7 offers "different number" as a retry, and
    #: somebody paying for their sister is an ordinary Saturday.
    phone = models.CharField(max_length=16)

    #: Safaricom's two ids. `checkout_request_id` is the idempotency key and is
    #: unique where present; it is absent between the row being written and the
    #: push being accepted, which is a window that exists on purpose.
    merchant_request_id = models.CharField(max_length=64, blank=True)
    #: Uniqueness is the named partial constraint below, not `unique=True` on
    #: the field: the name is what `callbacks.py` matches on, for the same
    #: reason `booking.py` matches `no_overlapping_appointments` by name rather
    #: than catching a bare IntegrityError.
    checkout_request_id = models.CharField(  # noqa: DJ001 — NULL means "not pushed yet"
        max_length=64, null=True, blank=True
    )

    #: The verdict. `result_code IS NULL` is the test for "Safaricom has not
    #: told us anything yet" — see `payments/states.py` on why that is a
    #: different line from `NON_TERMINAL_STATES`.
    result_code = models.IntegerField(null=True, blank=True)
    #: Safaricom's own words. The design's screen 7 quotes the reason verbatim
    #: ("insufficient funds"), so it is stored verbatim — and rendered through
    #: `payments/messages.py`, because not every ResultDesc is safe to show a
    #: client ("Merchant does not exist" is our problem, not theirs).
    result_desc = models.CharField(max_length=255, blank=True)

    mpesa_receipt = models.CharField(max_length=32, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    pushed_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    #: Reconciliation bookkeeping. The query is a separate mechanism from the
    #: hold sweep — see `payments/tasks.py`.
    query_attempts = models.PositiveSmallIntegerField(default=0)
    last_queried_at = models.DateTimeField(null=True, blank=True)

    #: How many conflicting duplicates arrived for this CheckoutRequestID.
    #: Never zero-and-forgotten: a non-zero value here means Safaricom told us
    #: two different things and somebody should look.
    discrepancy_count = models.PositiveSmallIntegerField(default=0)

    orphan_reason = models.CharField(max_length=24, choices=OrphanReason.choices, blank=True)

    #: What the client reads off screen 8 and says down the phone. Unique,
    #: minted by `payments/support_codes.py`.
    support_code = models.CharField(max_length=16, unique=True)

    # ------------------------------------------- slice 7: working the queue
    #
    # The exception queue was readable in slice 6 and could not be *worked*:
    # a shop could see "paid, no booking" and had nowhere to record that they
    # had rung the client and sorted it. So the same row kept appearing, and a
    # queue that never empties is a queue nobody reads.
    #
    # Resolution is a stamp and a note rather than a state, deliberately. The
    # payment's own state machine describes what happened to the *money*, and
    # "somebody dealt with this" is not a money fact — collapsing the two would
    # mean an admin could move a payment's state by writing a note.
    #
    # `queue_` prefixed because `resolved_at` above is already taken and means
    # something else entirely: that one is stamped when the *payment* reaches a
    # terminal state, this one when a *person* has finished with the row. Two
    # fields called `resolved_at` on one model is how somebody later reports on
    # the wrong one.
    #: Stamped when a cancellation leaves this shop owing the client money back.
    #: We are not the merchant — the deposit went to the shop's paybill and the
    #: refund is theirs to send — so all this side can do is *record* it, put it
    #: in front of a human, and stop pretending otherwise. §12's REFUND outcome
    #: is the only thing that sets it; a CREDIT outcome resolves itself and
    #: never appears here.
    refund_due_at = models.DateTimeField(null=True, blank=True)
    queue_resolved_at = models.DateTimeField(null=True, blank=True)
    queue_resolved_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    queue_note = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "payments"
        ordering = ["-created_at"]
        indexes = [
            # The exception queue: "paid, no appointment", per shop.
            models.Index(fields=["state", "created_at"], name="pay_state_created_idx"),
            # The reconciliation sweep's working set.
            models.Index(fields=["state", "pushed_at"], name="pay_state_pushed_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["checkout_request_id"],
                condition=Q(checkout_request_id__isnull=False),
                name=CHECKOUT_ID_CONSTRAINT,
            ),
            # **At most one non-terminal payment per appointment**, in the
            # database rather than in a view. Two live pushes for one booking is
            # how a client pays twice, and an application-level check loses the
            # same race the exclusion constraint exists to win.
            models.UniqueConstraint(
                fields=["appointment"],
                condition=Q(state__in=NON_TERMINAL_STATES),
                name=OPEN_PAYMENT_CONSTRAINT,
            ),
            # A succeeded payment has a receipt; an orphaned one has a reason.
            # Both are things the shop reads off a screen while a client waits.
            models.CheckConstraint(
                condition=~Q(state=PaymentState.SUCCEEDED) | ~Q(mpesa_receipt=""),
                name="succeeded_payment_has_a_receipt",
            ),
            models.CheckConstraint(
                condition=~Q(state=PaymentState.ORPHANED) | ~Q(orphan_reason=""),
                name="orphaned_payment_has_a_reason",
            ),
            models.CheckConstraint(condition=Q(amount__gte=1), name="payment_amount_positive"),
        ]

    def __str__(self):
        return f"{self.support_code} · {self.get_state_display()} · KES {self.amount}"

    @property
    def is_open(self):
        """Still ours to wait on. Blocks a second push for this appointment."""
        return self.state in NON_TERMINAL_STATES

    @property
    def has_result(self):
        """Safaricom has given a verdict. The dedupe test, and deliberately not
        the same question as `is_open` — see `payments/states.py`."""
        return self.result_code is not None


class MpesaCallback(TimeStampedModel):
    """Every callback body Safaricom sent us. Append-only, phone redacted.

    Idempotency on the checkout request id decides what gets *processed*. This
    table decides what gets *kept*, and the two are different jobs: a duplicate
    that we correctly refused to re-apply is exactly the row somebody needs to
    see when a client says they were charged twice.

    Not org-scoped, deliberately. An unmatched callback belongs to no tenant —
    that is what makes it unmatched — and a nullable organization column on a
    guarded model is a hole in the guard rather than a feature.
    """

    checkout_request_id = models.CharField(max_length=64, db_index=True, blank=True)
    merchant_request_id = models.CharField(max_length=64, blank=True)
    result_code = models.IntegerField(null=True, blank=True)
    result_desc = models.CharField(max_length=255, blank=True)

    #: The body as received, with the payer's number replaced. CLAUDE.md §5.
    #: Redaction happens on the way in — a payload that reaches this column
    #: still carrying a phone number has already been written to disk.
    payload = models.JSONField(default=dict)

    outcome = models.CharField(max_length=16, choices=CallbackOutcome.choices)
    payment = models.ForeignKey(
        "payments.Payment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="callbacks",
    )
    #: Set when `outcome` is DISCREPANCY: what we already held, so the two
    #: claims sit side by side without one overwriting the other.
    previous_result_code = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "mpesa_callbacks"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.checkout_request_id or '(none)'} · {self.get_outcome_display()}"

    def save(self, *args, **kwargs):
        """Append-only, enforced rather than documented.

        A table whose value is being evidence must not have an edit path. The
        check is on `_state.adding` rather than on `pk`, because UUID primary
        keys are populated before the insert and a `pk is not None` test would
        refuse every create.
        """
        if not self._state.adding:
            raise ValueError(
                "MpesaCallback rows are append-only. Record a new row instead of editing one."
            )
        return super().save(*args, **kwargs)


class PaymentMove(OrgDerivedModel):
    """A payment was re-pointed at a different appointment.

    Written by slice 7's remedy, which lets a client whose slot was lost pick
    another time and carry their deposit to it. The table ships now, empty, so
    that slice adds an endpoint rather than a migration against live money.

    `from_appointment` is kept even though `Payment.appointment` already moved,
    because the whole point of the row is the pair.
    """

    org_source = "payment"

    payment = models.ForeignKey("payments.Payment", on_delete=models.PROTECT, related_name="moves")
    from_appointment = models.ForeignKey(
        "scheduling.Appointment", on_delete=models.PROTECT, related_name="payments_moved_out"
    )
    to_appointment = models.ForeignKey(
        "scheduling.Appointment", on_delete=models.PROTECT, related_name="payments_moved_in"
    )
    reason = models.CharField(max_length=32)
    #: Null when the system did it. A staff member re-pointing a payment from
    #: the exception queue is named; the client self-serving from the slotLost
    #: screen is not, because there is no login — CLAUDE.md §12.
    moved_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "payment_moves"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.payment.support_code} → {self.to_appointment_id}"


# Slice 7's credit models live in `payments/credit.py`, next to the redemption
# logic that is the only reason they have the shape they do. Imported here so
# the app registry finds them: Django discovers models through `app.models`, and
# a model in a sibling module is invisible until something pulls it in.
from payments.credit import (  # noqa: E402,F401 — see above
    Credit,
    CreditRedemption,
    CreditSource,
    CreditState,
)
