"""Queueing a message. The only way anything in this codebase sends one.

Two properties, both load-bearing:

**Queued in the transaction, sent after it commits.** The row is written inside
whatever transaction the caller is in, so a rolled-back payment cannot leave a
promise to message somebody. The *dispatch* goes through
`transaction.on_commit`, so a slow gateway can never hold a database lock — and,
in the callback path specifically, can never delay the 200 that stops Safaricom
retrying. That is the difference between a slow SMS provider and an outage.

**Variables are built here, once.** The provider is handed a template id and a
dict, never a sentence — see `notifications/providers.py`. This module is where
an appointment and a payment become that dict, which means there is one place
that decides what "when" and "paid" mean in a message.
"""

import logging

from django.db import IntegrityError, transaction

from accounts.phone import normalize_phone
from notifications.models import Message
from notifications.templates import ONE_SHOT, Template
from scheduling.availability import LOCAL_TZ

logger = logging.getLogger(__name__)

#: Templates whose copy names a credit. Listed so `variables_for` can guarantee
#: the keys exist for exactly these and not sprinkle empty strings through every
#: other message's variable dict.
CREDIT_TEMPLATES = frozenset({Template.CANCELLED_CREDIT})


def variables_for(appointment, template, *, payment=None, credit=None, restored=()):
    """The dict the provider renders from. EAT, because the client reads it."""
    local = appointment.starts_at.astimezone(LOCAL_TZ)
    shop = appointment.shop
    variables = {
        "when": local.strftime("%a %-d %b, %-I:%M %p").replace("AM", "am").replace("PM", "pm"),
        "staff": appointment.staff.display_name,
        "shop": shop.name,
        "shop_phone": shop.phone or "the shop",
        "service": appointment.service.name,
        "link": booking_link(appointment),
    }
    if payment is not None:
        variables["paid"] = f"{payment.amount:,}"
        variables["receipt"] = payment.mpesa_receipt
        variables["support_code"] = payment.support_code
    if template == Template.BOOKING_CONFIRMED:
        # Both figures from `lifecycle`, which counts spent shop credit as well
        # as M-Pesa. This line used to be `price_snapshot - deposit_snapshot`,
        # and `deposit_snapshot` after `holds.apply_credit` is only what is
        # still owed to M-Pesa — zero when credit covered the deposit outright.
        # A client who had just spent KES 300 of their own credit was sent
        # "Paid KES 0 deposit. Balance KES 1,200 at the shop." and would be
        # charged the full price at the chair. In the one message they keep.
        from scheduling.lifecycle import balance_due_for, paid_deposit_for

        balance = balance_due_for(appointment)
        variables["balance"] = f"{balance:,}" if balance else ""
        # Set here rather than left to the `payment is not None` branch above:
        # a credit-covered booking confirms with no payment at all, so that
        # branch never runs and the `setdefault` below reported a zero.
        variables["paid"] = f"{paid_deposit_for(appointment):,}"
    if template in CREDIT_TEMPLATES:
        # Always present for these templates, even with no credit in hand, so a
        # renderer cannot `KeyError` on a live message path. The values are the
        # real ones whenever `lifecycle.cancel` supplies the credit it just
        # issued — which is the only path that queues `CANCELLED_CREDIT`, and
        # `test_a_credit_cancellation_names_the_figure_and_the_date` holds it
        # to that. Blank here is a bug that shows up as blank copy rather than
        # as a message that never sends.
        variables["credit_expires"] = ""
        variables["credit_reference"] = ""
    # A late cancellation can produce more than one credit: the cash half of a
    # deposit becomes credit on a fresh window while the half that *was* credit
    # comes back on its original expiry (`payments.credit.restore`). Both are
    # "your money is still at this shop", so they are summarised together
    # rather than the message growing a clause per row.
    #
    # Scoped to the credit templates: a refundable cancellation also carries
    # `restored`, and there these keys mean nothing and `paid` must stay the
    # whole deposit rather than the credit portion of it.
    held = (
        ([credit] if credit is not None else []) + list(restored)
        if template in CREDIT_TEMPLATES
        else []
    )
    if held:
        # EAT and a date only. A client reading "valid until 13 Oct" acts on it;
        # one reading a timestamp with an offset does not. The soonest date when
        # there are two, because it is the first one that stops being spendable
        # and the only one it is safe to act on.
        soonest = min(row.expires_at for row in held)
        variables["credit_expires"] = soonest.astimezone(LOCAL_TZ).strftime("%-d %b %Y")
        # Only when there is exactly one to quote. Two references in an SMS is a
        # second segment (§6) to say what the manage link already shows in full.
        variables["credit_reference"] = held[0].reference if len(held) == 1 else ""
        variables["paid"] = f"{sum(row.amount_kes for row in held):,}"
    if restored:
        # A refund that came back as credit, because the deposit was paid with
        # credit — `payments.credit.restore`. The refund message has to say so:
        # "the shop will refund you" would leave the client waiting for a
        # transfer that is not coming, which is the support call §12 exists to
        # prevent, arriving by a new route.
        #
        # The soonest expiry when a deposit drew on more than one credit, since
        # that is the first date any of it stops being spendable, and the
        # reference only when there is exactly one to quote — two references in
        # an SMS is a second segment (§6) to say something the manage link
        # already shows in full.
        soonest = min(row.expires_at for row in restored)
        variables["restored"] = f"{sum(row.amount_kes for row in restored):,}"
        variables["restored_expires"] = soonest.astimezone(LOCAL_TZ).strftime("%-d %b %Y")
        variables["restored_reference"] = restored[0].reference if len(restored) == 1 else ""
    variables.setdefault("paid", "0")
    return variables


def booking_link(appointment):
    """The one link in the message. CLAUDE.md §12: "the link is the session."

    Slice 7 widened this from the appointment's own id to its manage token, and
    the page behind it from read-only to cancel-and-reschedule. That was always
    the plan — slice 6's note here said it was one function when the screen
    existed, and this is the function.

    `/m/<token>` rather than `/booking/<id>`: the token is the credential, and a
    URL carrying both would invite somebody to treat the id as the thing that
    matters. Short, too — every character here is charged for on every message
    (§6), which is the same reasoning that made the token stored rather than
    signed. See `scheduling/manage_tokens`.

    Falls back to the read-only id page when a booking has no token: walk-ins
    never get one, and neither does a cancelled booking whose token has been
    revoked — but a cancellation SMS still has to link somewhere real.
    """
    from django.conf import settings

    base = settings.PUBLIC_BASE_URL.rstrip("/")
    if appointment.manage_token:
        return f"{base}/m/{appointment.manage_token}"
    return f"{base}/booking/{appointment.pk}"


def queue_message(
    appointment,
    template,
    *,
    payment=None,
    credit=None,
    restored=(),
    to=None,
    variables_extra=None,
):
    """Write the row and arrange for it to be sent after this commits.

    Returns the `Message`, or None when this one-shot has already been sent.
    """
    template = Template(template)
    number = to or (appointment.client.phone if appointment.client_id else None)
    if not number:
        # A walk-in has no client and never will — CLAUDE.md §4. Nothing to say
        # and nobody to say it to.
        return None

    message = Message(
        appointment=appointment,
        template=template,
        to=normalize_phone(number),
        variables={
            **variables_for(
                appointment, template, payment=payment, credit=credit, restored=restored
            ),
            # Whatever the caller knows that this module does not. Slice 8's
            # no-show and refund messages both name a figure that comes from
            # `lifecycle.paid_deposit_for`, which reads payments *and* redeemed
            # credit — arithmetic that belongs there and not here.
            **(variables_extra or {}),
        },
    )
    try:
        with transaction.atomic():
            message.save()
    except IntegrityError:
        if template in ONE_SHOT:
            # Already queued or sent. The constraint is the guard; this is the
            # ordinary case of a retried callback, not an error.
            logger.info("message %s already queued for %s", template, appointment.pk)
            return None
        raise

    _dispatch_after_commit(message)
    return message


def _dispatch_after_commit(message):
    from notifications.tasks import deliver_message

    transaction.on_commit(lambda: deliver_message.delay(str(message.pk)))
