"""Listing-scoped messaging: one thread per (listing, buyer).

The seller is always ``listing.seller``; it's denormalised onto the
conversation so "threads where I'm the seller" is a plain indexed filter rather
than a join through the listing. Business rules (who may talk to whom, read
state, blocking) live in ``services.py`` — models stay declarative.

Conversations and messages are kept (audit/history), so no soft-delete here.
Blocks and reports hard-delete per project convention.
"""
from django.conf import settings
from django.db import models

from apps.catalog.models import Listing
from apps.core.models import TimeStampedModel


class Conversation(TimeStampedModel):
    listing = models.ForeignKey(
        Listing, related_name="conversations", on_delete=models.CASCADE
    )
    # The two participants. ``seller`` mirrors ``listing.seller`` at creation.
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="buying_conversations",
        on_delete=models.CASCADE,
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="selling_conversations",
        on_delete=models.CASCADE,
    )
    # Stamped on every new message so inboxes sort by recent activity cheaply.
    last_message_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "messaging_conversation"
        constraints = [
            models.UniqueConstraint(
                fields=["listing", "buyer"], name="uniq_conversation_per_buyer_listing"
            ),
        ]
        indexes = [
            models.Index(fields=["buyer", "-last_message_at"]),
            models.Index(fields=["seller", "-last_message_at"]),
        ]
        ordering = ["-last_message_at", "-created_at"]

    def __str__(self) -> str:
        return f"Conversation #{self.pk} on listing {self.listing_id}"

    def other_party(self, user):
        """The participant who isn't ``user``."""
        return self.seller if user.id == self.buyer_id else self.buyer

    def involves(self, user) -> bool:
        return user.id in (self.buyer_id, self.seller_id)


class Message(TimeStampedModel):
    conversation = models.ForeignKey(
        Conversation, related_name="messages", on_delete=models.CASCADE
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="sent_messages",
        on_delete=models.CASCADE,
    )
    body = models.TextField()
    # Null until the *other* participant opens the thread.
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "messaging_message"
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
        ]
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"Message #{self.pk} from {self.sender_id}"


class Block(TimeStampedModel):
    """``blocker`` no longer wants to hear from ``blocked``. Enforced both ways
    in messaging: a block in either direction freezes the thread.
    """

    blocker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="blocks_made",
        on_delete=models.CASCADE,
    )
    blocked = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="blocks_received",
        on_delete=models.CASCADE,
    )

    class Meta:
        db_table = "messaging_block"
        constraints = [
            models.UniqueConstraint(fields=["blocker", "blocked"], name="uniq_block"),
        ]

    def __str__(self) -> str:
        return f"{self.blocker_id} blocked {self.blocked_id}"


class Report(TimeStampedModel):
    """A user-reported user, surfaced in the Phase 6 admin moderation queue."""

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="reports_made",
        on_delete=models.CASCADE,
    )
    reported = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="reports_received",
        on_delete=models.CASCADE,
    )
    reason = models.TextField(blank=True)

    class Meta:
        db_table = "messaging_report"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.reporter_id} reported {self.reported_id}"
