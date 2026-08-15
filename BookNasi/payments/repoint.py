"""The `slotLost` remedy: carry a paid deposit to a different appointment.

The client paid, the callback was slow, and somebody else took the slot. Slice 6
named the state, wrote the screen, and made the remedy a phone call — honestly,
because nothing automatic existed and a screen that promised one would have been
lying. This is the automatic one.

**Option B, chosen at slice 7 planning: re-point the succeeded payment at a new
appointment.** The alternatives were a refund (slow, manual, and leaves the
client with no booking) and a credit (better, but still asks somebody who has
already paid to come back later). Re-pointing is the only one where the client
ends the interaction with the thing they wanted.

The shape landed in slice 6 on purpose: `Payment.appointment` is an ordinary
mutable FK, `PaymentMove` exists to record the pair, and `OrphanReason.SLOT_LOST`
already distinguishes this from the three orphan cases that are not remedies.
So this module is the operation and its guards, not a migration.

## The CLAUDE.md §5 carve-out this depends on

§5: "A service with no deposit is not publicly bookable... the STK push *is* the
phone verification, so a deposit-free public booking is an unverified number
holding a slot for free."

A re-pointed booking has no push of its own. It is **not** a deposit-free
booking, and the difference is the whole argument: this deposit was pushed to
this number and Safaricom confirmed it. A succeeded payment is precisely the
phone verification the rule exists to provide, so satisfying the rule's purpose
by carrying that payment forward is not a loophole in it.

That is written into §5 itself, not left in this docstring, because a carve-out
only discoverable by reading the module that benefits from it is how the next
person re-derives it wrongly. The same carve-out covers a credit-covered
deposit — see `payments/credit.py`, which has the same property for the same
reason.

## What this refuses

- A payment that did not succeed. There is nothing to carry.
- A payment already sitting against a live booking. Re-pointing that would take
  a slot away from a booking that is fine.
- A target whose deposit exceeds what was paid. The client would be short, and
  silently under-charging is how a shop discovers the shortfall at the chair.
- A target belonging to a different shop. Money moved to one shop's paybill
  cannot become another's booking.
"""

import logging

from django.db import transaction
from django.utils import timezone

from payments.models import PaymentMove
from payments.states import OrphanReason, PaymentState
from scheduling.statuses import AppointmentStatus
from scheduling.transitions import Actor, apply_transition

logger = logging.getLogger(__name__)

S = AppointmentStatus


class RepointRefused(Exception):
    def __init__(self, message, *, reason=""):
        self.reason = reason
        super().__init__(message)


def is_repointable(payment):
    """Only a succeeded payment that lost its slot. Read by the screen, too."""
    return (
        payment.state == PaymentState.ORPHANED and payment.orphan_reason == OrphanReason.SLOT_LOST
    )


@transaction.atomic
def repoint(payment, *, to_appointment, now=None, moved_by=None, reason="slot_lost_remedy"):
    """Move a paid deposit onto `to_appointment` and confirm it.

    Returns the appointment, confirmed. Raises `RepointRefused`, or `SlotTaken`
    if the target went while this was in flight — the exclusion constraint
    decides, exactly as it does everywhere else.
    """
    now = now or timezone.now()

    locked = payment.__class__.objects.unscoped().select_for_update(of=("self",)).get(pk=payment.pk)
    if not is_repointable(locked):
        raise RepointRefused("That payment is not waiting for a booking.", reason="not_repointable")
    if to_appointment.shop_id != locked.appointment.shop_id:
        raise RepointRefused("That booking belongs to another shop.", reason="wrong_shop")
    if to_appointment.status != S.PENDING_PAYMENT:
        raise RepointRefused("That slot is not waiting for a payment.", reason="not_holding")
    if to_appointment.deposit_snapshot > locked.amount:
        raise RepointRefused(
            "That service needs a larger deposit than you paid.", reason="deposit_short"
        )

    from_appointment = locked.appointment

    locked.appointment = to_appointment
    locked.state = PaymentState.SUCCEEDED
    locked.orphan_reason = ""
    locked.save(update_fields=["appointment", "state", "orphan_reason", "updated_at"])

    PaymentMove.objects.create(
        payment=locked,
        from_appointment=from_appointment,
        to_appointment=to_appointment,
        reason=reason,
        moved_by=moved_by,
    )

    # SYSTEM, not STAFF: this is the same edge the late callback uses, and for
    # the same reason — the money is real and the database decides whether the
    # slot survived. `scheduling/transitions.py` is still the only writer of
    # `Appointment.status`.
    apply_transition(to_appointment, S.CONFIRMED, now=now, actor=Actor.SYSTEM)

    logger.info(
        "payment %s re-pointed from %s to %s",
        locked.support_code,
        from_appointment.pk,
        to_appointment.pk,
    )
    return to_appointment


def notify_repointed(appointment, payment):
    """The confirmation the client gets for the booking they just rescued.

    The ordinary `booking_confirmed`, deliberately: from the client's side this
    *is* a confirmed booking with a paid deposit, and a special "your re-pointed
    payment has been applied" message would be us explaining our own plumbing to
    somebody who only ever wanted a haircut.
    """
    from notifications.service import queue_message
    from notifications.templates import Template

    queue_message(appointment, Template.BOOKING_CONFIRMED, payment=payment)
