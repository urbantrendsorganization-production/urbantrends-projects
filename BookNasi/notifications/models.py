"""One row per message we tried to send.

Three reasons this is a table and not a log line:

- **Cost.** CLAUDE.md §6 prices it: 300 bookings × 3 messages is 900 a month on
  the cheapest tier. A number nobody records is a number nobody manages.
- **Support.** "Did the client get the link?" is a question a shop asks, and
  the answer has to be better than a guess.
- **Idempotency.** `(appointment, template)` is unique for the one-shot
  messages, so a duplicate callback that somehow got past the payment dedupe
  still cannot send a client two confirmations.

The body is **not** stored. It contains a name, a time and a phone number, and
it is fully reconstructible from the template id and the variables — which are
stored, with the recipient normalised. Keeping the rendered text would be a
second copy of personal data whose only use is convenience (CLAUDE.md §9).
"""

from django.db import models
from django.db.models import Q

from core.models import OrgDerivedModel
from notifications.templates import ONE_SHOT, Template


class MessageStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    SENT = "sent", "Handed to the provider"
    FAILED = "failed", "Provider refused it"


class Message(OrgDerivedModel):
    org_source = "appointment"

    appointment = models.ForeignKey(
        "scheduling.Appointment", on_delete=models.CASCADE, related_name="messages"
    )
    template = models.CharField(max_length=32, choices=Template.choices)
    #: Normalised E.164, as everywhere. See accounts/phone.py.
    to = models.CharField(max_length=16)
    #: What the provider renders from. Not the rendered text — see the module
    #: docstring.
    variables = models.JSONField(default=dict)

    status = models.CharField(
        max_length=8, choices=MessageStatus.choices, default=MessageStatus.QUEUED, db_index=True
    )
    provider = models.CharField(max_length=24, blank=True)
    provider_message_id = models.CharField(max_length=64, blank=True)
    error_detail = models.CharField(max_length=255, blank=True)
    cost_kes = models.PositiveIntegerField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "messages"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["appointment", "template"],
                condition=Q(template__in=list(ONE_SHOT)),
                name="one_shot_message_per_appointment",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "created_at"], name="msg_status_created_idx"),
        ]

    def __str__(self):
        return f"{self.get_template_display()} → {self.to} ({self.status})"


# Slice 8's `Reminder` lives in `notifications/reminders.py`, next to the
# scheduling logic that is the only reason it has the shape it does. Imported
# here so the app registry finds it — Django discovers models through
# `app.models`, and a model in a sibling module is invisible until something
# pulls it in.
from notifications.reminders import Reminder, ReminderKind  # noqa: E402,F401
