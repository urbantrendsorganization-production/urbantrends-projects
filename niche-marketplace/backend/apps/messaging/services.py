"""Messaging business logic — the single place that decides who may talk to
whom, records read state, and manages blocks/reports. Views stay thin.
"""
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status as http_status
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from apps.catalog.models import Listing
from apps.messaging.models import Block, Conversation, Message, Report


class MessagingBlocked(APIException):
    """A block (in either direction) prevents this messaging action."""

    status_code = http_status.HTTP_403_FORBIDDEN
    default_detail = "Messaging with this user is unavailable."
    default_code = "messaging_blocked"


def is_blocked_between(a, b) -> bool:
    """True if either user has blocked the other."""
    return Block.objects.filter(
        Q(blocker=a, blocked=b) | Q(blocker=b, blocked=a)
    ).exists()


@transaction.atomic
def get_or_start_conversation(*, listing: Listing, buyer) -> Conversation:
    """Return the buyer's thread for ``listing``, creating it if needed.

    One thread per (listing, buyer). The seller is taken from the listing. A
    seller can't open a thread against their own listing, and a block in either
    direction blocks starting one.
    """
    seller = listing.seller
    if buyer.id == seller.id:
        raise ValidationError(
            {"detail": "You can't message yourself about your own listing."}
        )
    if is_blocked_between(buyer, seller):
        raise MessagingBlocked()

    conversation, _ = Conversation.objects.get_or_create(
        listing=listing,
        buyer=buyer,
        defaults={"seller": seller},
    )
    return conversation


@transaction.atomic
def post_message(*, conversation: Conversation, sender, body: str) -> Message:
    """Append a message to a thread the sender participates in."""
    if not conversation.involves(sender):
        raise PermissionDenied("You are not part of this conversation.")

    other = conversation.other_party(sender)
    if is_blocked_between(sender, other):
        raise MessagingBlocked()

    body = (body or "").strip()
    if not body:
        raise ValidationError({"body": ["Message can't be empty."]})

    message = Message.objects.create(
        conversation=conversation, sender=sender, body=body
    )
    conversation.last_message_at = message.created_at
    conversation.save(update_fields=["last_message_at", "updated_at"])
    return message


def mark_conversation_read(*, conversation: Conversation, reader) -> int:
    """Mark the *other* party's unread messages in this thread as read.

    Returns how many were updated. Idempotent — already-read messages are left
    alone.
    """
    return (
        conversation.messages.filter(read_at__isnull=True)
        .exclude(sender=reader)
        .update(read_at=timezone.now())
    )


def unread_count(user) -> int:
    """Total unread messages across every thread the user participates in."""
    return (
        Message.objects.filter(
            Q(conversation__buyer=user) | Q(conversation__seller=user),
            read_at__isnull=True,
        )
        .exclude(sender=user)
        .count()
    )


def conversations_for(user):
    """Every thread the user is a participant in, newest activity first."""
    return (
        Conversation.objects.filter(Q(buyer=user) | Q(seller=user))
        .select_related("listing", "buyer", "seller")
        .prefetch_related("listing__images")
    )


# ---------------------------------------------------------------------------
# Blocking & reporting
# ---------------------------------------------------------------------------


def block_user(*, blocker, blocked) -> Block:
    if blocker.id == blocked.id:
        raise ValidationError({"detail": "You can't block yourself."})
    block, _ = Block.objects.get_or_create(blocker=blocker, blocked=blocked)
    return block


def unblock_user(*, blocker, blocked) -> None:
    Block.objects.filter(blocker=blocker, blocked=blocked).delete()


def report_user(*, reporter, reported, reason: str = "") -> Report:
    if reporter.id == reported.id:
        raise ValidationError({"detail": "You can't report yourself."})
    return Report.objects.create(
        reporter=reporter, reported=reported, reason=(reason or "").strip()
    )
