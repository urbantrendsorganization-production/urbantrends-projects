"""The three messages that ship in slice 6, and the line under them.

## What ships here

SMS lands in the payment slice because the M-Pesa reference and the booking's
link both arrive by SMS, and neither is any use sitting on a screen the client
has already closed.

1. **`booking_confirmed`** — the one the slice exists for. The M-Pesa receipt is
   the client's proof at the door (the design puts it *first* on screen 6, above
   everything else, for exactly that reason).
2. **`hold_released`** — the hold ran out and nothing was taken. Without it, a
   client who closed the page never learns their slot went, and turns up.
3. **`slot_lost`** — the money left and the slot did not survive. Carries the
   support code and says plainly that the shop will call. This slice's remedy
   for `slotLost` is a phone call, so the message that starts the phone call is
   part of the remedy rather than an extra.

## What does not, and why the line is there

Reminders are **slice 8**: T-24h, T-2h, the refunded message, the missed
message, and every staff or owner message.

The line is not arbitrary. A confirmation is a *reaction* — a transition fires,
a message goes, and it is done. A reminder is *scheduled*, which means a Celery
task keyed to the appointment that has to be cancelled when the appointment is
cancelled, or clients get reminded about bookings that no longer exist.
CLAUDE.md §6 calls that a trust bug and it is right. That is the same "safe to
lose, safe to run twice" problem the hold release solved, and it deserves its
own slice rather than being smuggled in behind the confirmation.

Nothing in the payment path needs it.

## The rules the copy obeys

From the design's message templates: time and place in the first clause, money
as a plain KES figure, **exactly one link**, no greeting, no sign-off, no emoji.
Sender id `BOOKNASI`, which is provider configuration and not a variable here.

Rendering lives on this side of the provider interface only for the SMS
adapter's benefit. A WhatsApp adapter maps these ids to its own approved
templates and never calls `render` — see `notifications/providers.py`.
"""

from django.db import models


class Template(models.TextChoices):
    BOOKING_CONFIRMED = "booking_confirmed", "Booking confirmed"
    HOLD_RELEASED = "hold_released", "Hold released"
    SLOT_LOST = "slot_lost", "Paid but the slot was taken"
    # Slice 7, the lifecycle. Three cancellations rather than one, because the
    # only thing a client does not already know when they cancel is what
    # happened to their money — see CLAUDE.md §12.
    CANCELLED_REFUND = "cancelled_refund", "Cancelled, deposit refunded"
    CANCELLED_CREDIT = "cancelled_credit", "Cancelled, deposit became credit"
    CANCELLED_PLAIN = "cancelled_plain", "Cancelled, nothing had been taken"
    RESCHEDULED = "rescheduled", "Booking moved"
    # Slice 8, the scheduled half. Two reminders because §6 says two and prices
    # three messages a booking; the T-24h is simply never armed when its moment
    # has already passed, which is most of why §8's "one reminder" reading and
    # §6's disagreed. See `notifications/reminders.py`.
    REMINDER_24H = "reminder_24h", "Reminder, 24 hours before"
    REMINDER_2H = "reminder_2h", "Reminder, 2 hours before"
    #: They did not come, and the deposit was kept. §12 requires the terms to be
    #: visible before payment; a forfeit nobody is told about afterwards is the
    #: support call that policy was written to prevent.
    NO_SHOW = "no_show", "Missed appointment, deposit kept"
    #: Sent when a shop marks a refund done in the exception queue. Without it,
    #: "the shop will refund you" has no closing line and the client's only
    #: recourse is to ring and ask.
    REFUND_SENT = "refund_sent", "Refund sent by the shop"


#: Sent at most once per appointment. Enforced by a unique constraint on
#: `(appointment, template)` — see `notifications/models.py`. A duplicate
#: callback that somehow got past the payment dedupe still cannot double-message
#: a client, which matters because they are charged for neither and trust both.
#:
#: A tuple rather than a set, and that is not a style choice: this list is
#: baked into a migration's constraint condition, and `str` hashing is
#: randomised per process, so a set would serialise in a different order on
#: every run and `makemigrations --check` would report a phantom change.
#:
#: The cancellations are one-shot; `RESCHEDULED` deliberately is not. A booking
#: can be moved up to `MAX_RESCHEDULES` times and each move is a different time
#: the client has to be told about — a once-per-appointment constraint here
#: would silently drop the second one.
ONE_SHOT = (
    Template.BOOKING_CONFIRMED,
    Template.HOLD_RELEASED,
    Template.SLOT_LOST,
    Template.CANCELLED_REFUND,
    Template.CANCELLED_CREDIT,
    Template.CANCELLED_PLAIN,
    # Slice 8. Both fire once per booking and never again: you can only miss an
    # appointment once, and a shop refunding twice is a bug we should not be
    # papering over with a second SMS.
    Template.NO_SHOW,
    Template.REFUND_SENT,
)

#: Deliberately outside `ONE_SHOT`, and the reason the constraint was partial
#: from the start — see `notifications/migrations/0001_initial.py`. A booking
#: rescheduled after its 24-hour reminder has already gone needs a fresh one for
#: its new date, so uniqueness lives on `Reminder` (one per appointment per
#: kind, moved rather than duplicated) instead of on the message log.
SCHEDULED = (Template.REMINDER_24H, Template.REMINDER_2H)


def _confirmed(v):
    return (
        f"Booked: {v['when']} with {v['staff']} at {v['shop']}. "
        f"{v['service']}. Paid KES {v['paid']} deposit"
        + (f", M-Pesa {v['receipt']}" if v.get("receipt") else "")
        + (f". Balance KES {v['balance']} at the shop" if v.get("balance") else "")
        + f". {v['link']}"
    )


def _released(v):
    return (
        f"Your hold on {v['when']} with {v['staff']} at {v['shop']} has run out "
        f"and the time is back in the list. Nothing was taken from your M-Pesa. "
        f"{v['link']}"
    )


def _slot_lost(v):
    return (
        f"We received your KES {v['paid']} but {v['when']} with {v['staff']} was "
        f"taken while the payment was going through. Your money is with "
        f"{v['shop']} and they will call you within the hour. "
        f"Quote {v['support_code']} — {v['shop_phone']}"
    )


def _cancelled_refund(v):
    return (
        f"Cancelled: {v['when']} with {v['staff']} at {v['shop']}. "
        f"Your KES {v['paid']} deposit will be refunded by the shop. "
        f"Any questions, {v['shop_phone']}."
    )


def _cancelled_credit(v):
    # The figure, the expiry date and the reference, because this is the only
    # record the client gets of money they still have. A message that said
    # "your deposit has become credit" without saying how much, until when, or
    # what to quote is the support call §12 was trying to prevent.
    return (
        f"Cancelled: {v['when']} with {v['staff']} at {v['shop']}. "
        f"Your KES {v['paid']} deposit is now credit at {v['shop']}, valid until "
        f"{v['credit_expires']} on any service. Quote {v['credit_reference']}. "
        f"{v['link']}"
    )


def _cancelled_plain(v):
    return (
        f"Cancelled: {v['when']} with {v['staff']} at {v['shop']}. "
        f"Nothing was taken from your M-Pesa."
    )


def _rescheduled(v):
    return (
        f"Moved: your booking at {v['shop']} is now {v['when']} with {v['staff']}. "
        f"{v['service']}. Your deposit moved with it. {v['link']}"
    )


def _reminder_24h(v):
    # Leads with the time, names the money still owed, and carries the manage
    # link — because the most useful thing a 24-hour reminder can produce is a
    # cancellation while the slot is still resellable, not a guilty client.
    return (
        f"Tomorrow: {v['when']} with {v['staff']} at {v['shop']}. {v['service']}."
        + (f" Balance KES {v['balance']} at the shop." if v.get("balance") else "")
        + f" Need to change it? {v['link']}"
    )


def _reminder_2h(v):
    # Shorter. At two hours out the client is deciding whether to set off, and
    # the only things that help are the time and where to ring.
    return (
        f"In 2 hours: {v['when']} with {v['staff']} at {v['shop']}. Running late? {v['shop_phone']}"
    )


def _no_show(v):
    return (
        f"You missed {v['when']} with {v['staff']} at {v['shop']}, and the "
        f"KES {v['paid']} deposit was kept. Book again any time: {v['link']}"
    )


def _refund_sent(v):
    return (
        f"{v['shop']} has sent your KES {v['paid']} refund for {v['when']}. "
        f"It should reach your M-Pesa shortly. Questions: {v['shop_phone']}"
    )


RENDERERS = {
    Template.BOOKING_CONFIRMED: _confirmed,
    Template.REMINDER_24H: _reminder_24h,
    Template.REMINDER_2H: _reminder_2h,
    Template.NO_SHOW: _no_show,
    Template.REFUND_SENT: _refund_sent,
    Template.HOLD_RELEASED: _released,
    Template.SLOT_LOST: _slot_lost,
    Template.CANCELLED_REFUND: _cancelled_refund,
    Template.CANCELLED_CREDIT: _cancelled_credit,
    Template.CANCELLED_PLAIN: _cancelled_plain,
    Template.RESCHEDULED: _rescheduled,
}


class UnknownTemplate(KeyError):
    pass


def render(template, variables):
    """Render one template for the SMS adapter. Never called for WhatsApp."""
    try:
        renderer = RENDERERS[Template(template)]
    except (ValueError, KeyError) as exc:
        raise UnknownTemplate(str(template)) from exc
    return renderer(variables)
