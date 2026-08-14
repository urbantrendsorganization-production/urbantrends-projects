"""What a client can do to their own booking after they have paid for it.

Three actions and no more: see it, move it, cancel it. CLAUDE.md §8 as amended —
"One booking, one move, no knock-on" — and §12's refund policy, settled
14 August 2026.

No re-service and no staff swap. A different service is a different price, a
different duration and a different deposit, which is a new booking wearing the
old one's clothes. A staff swap falls out of reschedule only where the client
picked "anyone available" in the first place, and even then only because the
availability engine offers whoever is free; it is never a thing the client
chooses here.

## The refund decision, and the latch

`outcome_for` is the whole policy in one function, so that the cancel screen and
the cancel endpoint cannot disagree about what a client is owed. The screen calls
it to show a figure *before* the client confirms — §5 requires the terms to be
readable before money moves, and "you will be refunded KES 875" is a term in a
way that "cancellations more than 24 hours ahead are refundable" is not.

The one-way latch is the part that is not obvious. `entered_refund_window_at` is
stamped the first time a booking is seen inside its shop's window and is never
cleared, and refundability reads the stamp rather than the clock. Without it:

    sit inside the window, where cancelling yields credit
      -> reschedule six weeks out, now outside the window
      -> cancel for a full refund

which turns the reschedule button into a refund button. With it, refundability
is decided by whether this booking has *ever* been late, not by where it happens
to sit at the moment somebody presses cancel. Moving *into* the window is
allowed and stamps immediately — a client who takes a slot three hours away has
knowingly taken a tight one.

## Why cancel does not simply refund

Nothing here moves money out of M-Pesa. We are not the merchant: the deposit
went to the shop's paybill, and a refund is the shop's transfer to make. What
this module produces is the *record* of what is owed — `Payment.refund_due_at`,
which puts the row in front of a human on the exception queue, or a `Credit` row
the client can spend without anyone touching a bank. Credit is the case that
resolves itself, which is most of why §12 chose it for late cancellations.
"""

from datetime import timedelta

from django.db import transaction
from django.db.backends.postgresql.psycopg_any import DateTimeTZRange
from django.utils import timezone

from scheduling.models import RANGE_BOUNDS
from scheduling.statuses import AppointmentStatus, BookingSource
from scheduling.transitions import apply_transition

S = AppointmentStatus

#: §12's cap, chosen at slice 7 planning. Every move invalidates a stylist's
#: planning for a day; three is generous for genuine changes and stops a booking
#: being walked around the calendar. A refusal still offers cancel, which now
#: yields credit rather than nothing, so the client is never trapped.
MAX_RESCHEDULES = 3


class Outcome:
    """What cancelling right now would produce. Copy lives on the client."""

    REFUND = "refund"
    CREDIT = "credit"
    NOTHING = "nothing"


class RescheduleRefused(Exception):
    """Not a slot problem — a rule problem. `reason` is machine-readable."""

    def __init__(self, message, *, reason=""):
        self.reason = reason
        super().__init__(message)


class NotManageable(Exception):
    """The booking is in a state with no client-facing actions left."""


# ------------------------------------------------------------- the policy


def is_inside_window(appointment, *, now=None):
    """Is this booking within its shop's refund window right now?"""
    now = now or timezone.now()
    window = timedelta(hours=appointment.shop.refund_window_hours)
    return appointment.starts_at - now <= window


def stamp_window(appointment, *, now=None, save=True):
    """Latch the booking as having been late. Idempotent, never cleared.

    Called wherever a booking is *observed* — the manage page load, a cancel, a
    reschedule — rather than on a schedule. A sweep would have to run often
    enough to catch every booking crossing its own boundary, and getting that
    wrong silently hands out refunds; observing is exact and costs nothing,
    because a client who never opens the link never cancels either.
    """
    now = now or timezone.now()
    if appointment.entered_refund_window_at is None and is_inside_window(appointment, now=now):
        appointment.entered_refund_window_at = now
        if save:
            appointment.save(update_fields=["entered_refund_window_at", "updated_at"])
        return True
    return False


def outcome_for(appointment, *, now=None, shop_cancelled=False):
    """What cancelling produces, and how much. `(outcome, amount_kes)`.

    The single source of the refund policy. §12:

        cancel earlier than the window -> refunded
        cancel later than it           -> credit, `deposit_credit_days`
        no-show                        -> forfeited
        the shop cancels               -> refunded, regardless
    """
    now = now or timezone.now()
    paid = paid_deposit_for(appointment)

    if paid < 1:
        # Nothing was ever taken, so there is nothing to return. A hold that
        # never completed its push is the ordinary case here.
        return Outcome.NOTHING, 0

    if shop_cancelled:
        # Unconditional and not shop-configurable — §12. A client cannot lose a
        # deposit to a cancellation they did not make, whenever it happens.
        return Outcome.REFUND, paid

    if appointment.status == S.NO_SHOW:
        return Outcome.NOTHING, paid

    late = appointment.entered_refund_window_at is not None or is_inside_window(
        appointment, now=now
    )
    return (Outcome.CREDIT, paid) if late else (Outcome.REFUND, paid)


def paid_deposit_for(appointment):
    """What actually arrived for this booking, in whole shillings.

    Reads succeeded payments rather than `deposit_snapshot`: the snapshot is
    what was *asked* for, and a booking whose push failed owes nothing back.
    Credit already applied counts too — it was money once.
    """
    from payments.models import Payment
    from payments.states import PaymentState

    rows = Payment.objects.unscoped().filter(appointment=appointment, state=PaymentState.SUCCEEDED)
    paid = sum(row.amount for row in rows)
    redeemed = sum(r.amount_kes for r in appointment.credit_redemptions.all())
    return paid + redeemed


def is_forfeited(appointment):
    """The forfeit, still derived. No state, per the slice 6 machine.

    Narrowed by credit's arrival: a late cancellation now *issues* credit, so it
    is no longer a forfeit and must not be counted as one. Without the credit
    check this would read every late cancel as forfeited and slice 9's no-show
    reporting would be wrong in the shop's favour, which is the direction nobody
    would notice.
    """
    return (
        appointment.status == S.NO_SHOW
        and paid_deposit_for(appointment) > 0
        and not appointment.credits_issued.exists()
    )


# -------------------------------------------------------------- the actions


@transaction.atomic
def cancel(appointment, *, now=None, shop_cancelled=False):
    """The client cancels. Returns `(outcome, amount, credit_or_none)`.

    Applies §12 and records what is owed. Nothing here moves money: a refund is
    the shop's transfer to make from its own paybill, so a REFUND outcome lands
    on the exception queue for a human, and a CREDIT outcome resolves itself.
    """
    from payments import credit as credit_module
    from payments.models import Payment
    from payments.states import PaymentState

    now = now or timezone.now()
    if appointment.status in (S.COMPLETED, S.IN_PROGRESS):
        raise NotManageable("That booking has already started.")

    stamp_window(appointment, now=now)
    outcome, amount = outcome_for(appointment, now=now, shop_cancelled=shop_cancelled)

    apply_transition(appointment, S.CANCELLED, now=now)

    issued = None
    if outcome == Outcome.REFUND and amount > 0:
        # Recorded, not sent. The money is in the shop's paybill and only they
        # can move it, so this puts the row on the exception queue with a
        # timestamp rather than promising the client something we cannot do.
        Payment.objects.unscoped().filter(
            appointment=appointment, state=PaymentState.SUCCEEDED, refund_due_at__isnull=True
        ).update(refund_due_at=now)
    if outcome == Outcome.CREDIT and amount > 0:
        payment = (
            Payment.objects.unscoped()
            .filter(appointment=appointment, state=PaymentState.SUCCEEDED)
            .order_by("created_at")
            .first()
        )
        issued = credit_module.issue(
            appointment=appointment, payment=payment, amount_kes=amount, now=now
        )

    # Every outstanding link dies with the booking. See `manage_tokens.revoke`.
    from scheduling import manage_tokens

    manage_tokens.revoke(appointment)

    _tell_them(appointment, outcome, amount, issued)
    return outcome, amount, issued


def _tell_them(appointment, outcome, amount, issued):
    """One SMS, after commit, saying which of the four outcomes happened.

    A cancellation confirmation that does not name the money is the support
    ticket §12 was trying to prevent — the client knows they cancelled; what
    they do not know is whether they lost KES 875.
    """
    from notifications.service import queue_message
    from notifications.templates import Template

    if appointment.source != BookingSource.ONLINE:
        return
    template = {
        Outcome.REFUND: Template.CANCELLED_REFUND,
        Outcome.CREDIT: Template.CANCELLED_CREDIT,
        Outcome.NOTHING: Template.CANCELLED_PLAIN,
    }[outcome]
    queue_message(appointment, template, credit=issued)


@transaction.atomic
def reschedule(appointment, *, starts_at, staff=None, now=None):
    """Move one booking to another free slot. One move, no cascade.

    §8: "One booking, one move, no knock-on." Nothing here displaces another
    booking, negotiates between two clients, or ripples a staff change across a
    day. The new slot is either free — the exclusion constraint decides, not a
    Python check — or the move is refused and the client picks again.

    The deposit comes with it, because it is the same row: `time_range` is
    updated in place, so `Payment.appointment` still points where it pointed and
    no money is re-pointed, re-pushed or re-verified.
    """
    from scheduling.availability import Policy, is_bookable_start, local_date
    from scheduling.booking import slot_taken_on_conflict
    from scheduling.cache import facts_for_staff_day

    now = now or timezone.now()

    if appointment.status not in (S.CONFIRMED, S.PENDING_PAYMENT):
        raise RescheduleRefused("That booking cannot be moved.", reason="not_movable")
    if appointment.reschedule_count >= MAX_RESCHEDULES:
        raise RescheduleRefused(
            "This booking has been moved as many times as it can be online. "
            "Call the shop to move it again.",
            reason="too_many_moves",
        )
    if starts_at <= now:
        raise RescheduleRefused("Pick a time in the future.", reason="in_the_past")

    # Latch *before* the move. A booking sitting inside its window right now is
    # late, and moving it out must not undo that — see the module docstring.
    stamp_window(appointment, now=now)

    target_staff = staff or appointment.staff
    duration = appointment.duration_snapshot
    ends_at = starts_at + timedelta(minutes=duration)

    # Re-derived server-side, never trusted from the client — CLAUDE.md §4. The
    # client's slot list was already stale when it rendered. The exclusion
    # constraint below is what actually decides; this is the readable refusal
    # that stops most collisions from reaching it.
    #
    # `Policy.for_public` because this is the client acting on their own
    # booking: the same lead time and horizon that governed the original
    # booking governs the move, so a client cannot reschedule into a slot they
    # could never have booked in the first place.
    facts = facts_for_staff_day(target_staff, local_date(starts_at))
    if not is_bookable_start(
        facts,
        starts_at=starts_at,
        duration_minutes=duration,
        policy=Policy.for_public(appointment.shop),
        now=now,
        # `str`, because `Busy.appointment_id` is a string — a UUID here
        # compares unequal to every one of them and the booking silently
        # blocks its own move.
        exclude_appointment_id=str(appointment.pk),
    ):
        raise RescheduleRefused("That time is no longer free.", reason="slot_taken")

    previous_staff_id = appointment.staff_id
    previous_start = appointment.starts_at
    previous_end = appointment.ends_at

    # A real range, not a tuple. Django accepts a tuple on the way *into* the
    # database, but `Appointment.starts_at` reads `time_range.lower`, so a tuple
    # left on the instance breaks every reader between here and the save —
    # including `manage_tokens.issue` two lines down.
    appointment.time_range = DateTimeTZRange(starts_at, ends_at, RANGE_BOUNDS)
    appointment.staff = target_staff
    appointment.reschedule_count += 1

    from scheduling import manage_tokens

    # The same token, a new expiry. The link follows the booking so a client's
    # existing SMS keeps working — see `manage_tokens`.
    manage_tokens.issue(appointment, now=now, save=False)

    # The constraint decides. A walk-in recorded into this slot a moment ago is
    # exactly the race this exists for, and the `is_bookable_start` check above
    # cannot close it — only the database can.
    with slot_taken_on_conflict(starts_at=starts_at, staff=target_staff):
        appointment.save(
            update_fields=[
                "time_range",
                "staff",
                "reschedule_count",
                "manage_token",
                "manage_expires_at",
                "updated_at",
            ]
        )

    # Latch again against the *new* start: a move into the window is late from
    # the moment it lands, and a client who moves to three hours from now has
    # knowingly taken a tight slot.
    stamp_window(appointment, now=now)

    # The `post_save` signal invalidates the day the booking now sits on, but it
    # reads the saved row and therefore cannot know where it *was*. A move out
    # of Monday into Tuesday would leave Monday's cache still showing the slot
    # as busy — a slot nobody can book, on the busiest read in the flow. This is
    # the one place that knows both, so it drops the old staff-day explicitly.
    _invalidate_vacated(previous_staff_id, previous_start, previous_end)

    # Slice 8. A move does not change `status`, so the transition hook that
    # normally syncs reminders never fires — and a booking moved from Friday to
    # Tuesday would otherwise keep Friday's reminders. §6 calls that exact thing
    # a trust bug. `ensure_scheduled` moves the existing rows rather than adding
    # new ones, and clears `sent_at` so the new date gets its own 24-hour notice
    # even when the old one already went.
    from notifications import reminders

    try:
        reminders.ensure_scheduled(appointment, now=now)
    except Exception:  # noqa: BLE001 — a messaging failure must not undo a move
        import logging

        logging.getLogger(__name__).exception("could not re-arm reminders for %s", appointment.pk)

    _tell_them_it_moved(appointment)
    return appointment


def _invalidate_vacated(staff_id, starts_at, ends_at):
    """Drop the staff-day(s) the booking just left.

    Both ends of the old range, for the reason `on_appointment_write` gives:
    an overnight appointment is recordable by staff, so a span can touch two
    dates even though an offered slot never does.
    """
    from scheduling.availability import local_date
    from scheduling.invalidation import invalidate_staff_days

    days = sorted({local_date(starts_at), local_date(ends_at)})
    invalidate_staff_days([staff_id], days)


def _tell_them_it_moved(appointment):
    from notifications.service import queue_message
    from notifications.templates import Template

    if appointment.source != BookingSource.ONLINE:
        return
    queue_message(appointment, Template.RESCHEDULED)


# --------------------------------------------------------- what the page shows


def actions_for(appointment, *, now=None):
    """Which actions the manage page offers, and what cancelling would cost.

    Computed here rather than in the renderer so the screen and the endpoint
    cannot disagree — a button the API would refuse is worse than no button.
    """
    now = now or timezone.now()
    outcome, amount = outcome_for(appointment, now=now)
    movable = (
        appointment.status in (S.CONFIRMED, S.PENDING_PAYMENT)
        and appointment.reschedule_count < MAX_RESCHEDULES
        and appointment.starts_at > now
    )
    return {
        "can_cancel": appointment.status in (S.CONFIRMED, S.PENDING_PAYMENT),
        "can_reschedule": movable,
        "moves_left": max(0, MAX_RESCHEDULES - appointment.reschedule_count),
        "cancel_outcome": outcome,
        "cancel_amount_kes": amount,
        "credit_days": appointment.shop.deposit_credit_days,
        "refund_window_hours": appointment.shop.refund_window_hours,
    }
