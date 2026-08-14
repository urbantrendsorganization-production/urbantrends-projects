"""Handing a queued message to the provider.

Runs in a worker, always. Nothing in a request or a callback handler waits on a
messaging gateway — see `notifications/service.py` on why that is not a
performance preference.

Never log the body, the recipient or any variable. CLAUDE.md §5 is about M-Pesa
payloads specifically, and a worker log is exactly the place a number leaks into
a file nobody is thinking about. The message id and the template are enough to
trace anything.
"""

import logging

from celery import shared_task
from django.utils import timezone

from notifications.models import Message, MessageStatus
from notifications.providers import Outgoing, get_provider

logger = logging.getLogger(__name__)

#: Two attempts, then the row sits `failed` for someone to see. A gateway that
#: refuses twice is not going to accept on the fifth, and a message retried
#: forever is a message nobody notices.
MAX_ATTEMPTS = 2


#: How long to wait before the second attempt. Long enough that a gateway
#: having a moment has had it, short enough that a booking confirmation is still
#: worth reading by the time it lands.
RETRY_COUNTDOWN_SECONDS = 60


@shared_task(bind=True, name="notifications.deliver_message")
def deliver_message(self, message_id):
    # QUEUED *or* FAILED. A single refusal sets FAILED below, so loading only
    # QUEUED rows made `MAX_ATTEMPTS` unreachable — the retry this constant
    # documents never happened, and one transient gateway refusal permanently
    # lost a booking confirmation. SENT is still excluded, which is what keeps
    # the task safe to run twice.
    message = (
        Message.objects.unscoped()
        .filter(pk=message_id, status__in=(MessageStatus.QUEUED, MessageStatus.FAILED))
        .first()
    )
    if message is None:
        # Already sent, or the row is gone. Safe to run twice, by design.
        return "resolved"
    if message.attempts >= MAX_ATTEMPTS:
        return "exhausted"

    provider = get_provider()
    message.attempts += 1
    message.provider = provider.name

    receipt = provider.send(
        Outgoing(
            template=message.template,
            to=message.to,
            variables=message.variables,
            reference=str(message.pk),
        )
    )

    if receipt.accepted:
        message.status = MessageStatus.SENT
        message.sent_at = timezone.now()
        message.provider_message_id = receipt.provider_message_id
        message.cost_kes = receipt.cost_kes
    else:
        message.status = MessageStatus.FAILED
        message.error_detail = receipt.error_detail[:255]
        logger.warning(
            "message %s (%s) refused by %s: %s",
            message.pk,
            message.template,
            provider.name,
            receipt.error_code,
        )

    message.save(
        update_fields=[
            "status",
            "attempts",
            "provider",
            "provider_message_id",
            "cost_kes",
            "error_detail",
            "sent_at",
            "updated_at",
        ]
    )

    # The row being reloadable is only half a retry; something has to come back
    # for it. Re-queued here rather than swept by Beat because a confirmation
    # SMS is worth a minute, not the next sweep interval, and one more periodic
    # task is one more thing to reason about. `MAX_ATTEMPTS` is enforced at the
    # top, so this can fire exactly once.
    if message.status == MessageStatus.FAILED and message.attempts < MAX_ATTEMPTS:
        # `throw=False`: the retry is still queued, but the task returns its
        # status instead of raising. Raising would propagate out of the
        # `on_commit` hook that dispatches it under eager execution, which turns
        # a refused SMS into an exception in whatever was committing — a
        # callback, a hold release — and those must not fail because a gateway
        # said no. `MAX_ATTEMPTS` is enforced at the top of this function.
        self.retry(countdown=RETRY_COUNTDOWN_SECONDS, max_retries=MAX_ATTEMPTS - 1, throw=False)

    return message.status
