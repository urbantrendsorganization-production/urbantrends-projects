"""The person being booked.

**Minimal on purpose.** Slice 3 needs somewhere for `Appointment.client` to
point, and CLAUDE.md §3 is explicit that this belongs to the Organization, not
the Shop — "a regular who visits two branches must be one person with one
history". Getting that wrong is one of the two shape decisions §3 calls
expensive to reverse, so the row is created here rather than left for slice 5 to
bolt onto an appointments table that already has data in it.

What is *not* here, and belongs to slice 5: the booking-management token, visit
history, marketing consent, and the DPA §9 export and scrub paths. There is no
API for this model in slice 3 and no serializer.

There is no client account and no password. CLAUDE.md §12: the STK push to the
phone number *is* the verification, and the manage link in the SMS is the
session.
"""

from django.db import models

from accounts.phone import normalize_phone
from core.models import OrgScopedModel


class Client(OrgScopedModel):
    """Org-scoped, never shop-scoped. See the module docstring."""

    full_name = models.CharField(max_length=120, blank=True)
    #: Normalised to +254… on save, because the same person typing 0712345678
    #: at one branch and 254712345678 at another must not become two people.
    phone = models.CharField(max_length=16)

    #: Slice 9 reads this; slice 3 only has to not lose it.
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "clients"
        ordering = ["full_name", "phone"]
        constraints = [
            # One person per number per organization. Not globally unique: the
            # same phone can be a client of two unrelated salons, and those are
            # two separate records under two separate controllers.
            models.UniqueConstraint(
                fields=["organization", "phone"], name="one_client_per_phone_per_org"
            ),
        ]

    def __str__(self):
        return self.full_name or self.phone

    def save(self, *args, **kwargs):
        self.phone = normalize_phone(self.phone)
        return super().save(*args, **kwargs)
