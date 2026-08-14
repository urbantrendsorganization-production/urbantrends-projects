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


def variables_for(appointment, template, *, payment=None):
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
    return variables


def booking_link(appointment):
    """The one link in the message.

    Points at the booking's own page, which is the confirmation screen the
    client just left — the same unguessable id the countdown screen polls, and
    CLAUDE.md §12's "the link is the session".

    It is **not yet** the signed, expiring manage link with a reschedule and a
    cancel on it. That screen is the lifecycle slice, and a link to a page that
    cannot do what the SMS implies is worse than a link to the one that can
    already show them their booking. Widening this to the manage token is one
    function, here, when that screen exists.
    """
    from django.conf import settings

    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/booking/{appointment.pk}"


def queue_message(appointment, template, *, payment=None, to=None):
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
        variables=variables_for(appointment, template, payment=payment),
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
