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


def variables_for(appointment, template, *, payment=None, credit=None):
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
        balance = max(appointment.price_snapshot - appointment.deposit_snapshot, 0)
        variables["balance"] = f"{balance:,}" if balance else ""
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
    if credit is not None:
        # EAT and a date only. A client reading "valid until 13 Oct" acts on it;
        # one reading a timestamp with an offset does not.
        variables["credit_expires"] = credit.expires_at.astimezone(LOCAL_TZ).strftime("%-d %b %Y")
        variables["credit_reference"] = credit.reference
        variables["paid"] = f"{credit.amount_kes:,}"
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


def queue_message(appointment, template, *, payment=None, credit=None, to=None):
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
        variables=variables_for(appointment, template, payment=payment, credit=credit),
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
