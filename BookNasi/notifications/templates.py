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


#: Sent at most once per appointment. Enforced by a unique constraint on
#: `(appointment, template)` — see `notifications/models.py`. A duplicate
#: callback that somehow got past the payment dedupe still cannot double-message
#: a client, which matters because they are charged for neither and trust both.
#:
#: A tuple rather than a set, and that is not a style choice: this list is
#: baked into a migration's constraint condition, and `str` hashing is
#: randomised per process, so a set would serialise in a different order on
#: every run and `makemigrations --check` would report a phantom change.
ONE_SHOT = (Template.BOOKING_CONFIRMED, Template.HOLD_RELEASED, Template.SLOT_LOST)


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


RENDERERS = {
    Template.BOOKING_CONFIRMED: _confirmed,
    Template.HOLD_RELEASED: _released,
    Template.SLOT_LOST: _slot_lost,
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
