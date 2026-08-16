"""The person being booked.

**Minimal on purpose.** Slice 3 needs somewhere for `Appointment.client` to
point, and CLAUDE.md §3 is explicit that this belongs to the Organization, not
the Shop — "a regular who visits two branches must be one person with one
history". Getting that wrong is one of the two shape decisions §3 calls
expensive to reverse, so the row is created here rather than left for slice 5 to
bolt onto an appointments table that already has data in it.

There is no client account and no password. CLAUDE.md §12: the STK push to the
phone number *is* the verification, and the manage link in the SMS is the
session.

## Slice 14 added the erasure state, and nothing else

CLAUDE.md §9 names four things a feature touching client data must keep
working: a stated retention period, an export path, a delete path, and the
processor clause honoured. Thirteen slices left all four unbuilt while the
model comment above promised them to "slice 5". The fields here are the two
facts that could not be derived — *has this person been scrubbed*, and *did
they ask to be* — and `clients/erasure.py` is everything else.

Deliberately still absent: marketing consent (nothing sends marketing), and a
visit-history table (the appointments are the history).
"""

from django.db import models
from django.db.models import Q

from accounts.phone import normalize_phone
from core.models import OrgScopedModel


class ScrubReason(models.TextChoices):
    """Why a row was scrubbed. Three, and they are not interchangeable.

    A controller has to be able to say *why* it no longer holds something, and
    the three answers carry different obligations: a request has a statutory
    clock, retention is our own stated policy expiring, and an owner acting
    unprompted is neither.
    """

    REQUESTED = "requested", "The client asked"
    RETENTION = "retention", "Retention period elapsed"
    SHOP = "shop", "Erased by the shop"


class Client(OrgScopedModel):
    """Org-scoped, never shop-scoped. See the module docstring."""

    full_name = models.CharField(max_length=120, blank=True)
    #: Normalised to +254… on save, because the same person typing 0712345678
    #: at one branch and 254712345678 at another must not become two people.
    phone = models.CharField(max_length=16)

    #: Slice 9 reads this; slice 3 only has to not lose it.
    notes = models.TextField(blank=True)

    # ------------------------------------------------------------ erasure
    #
    # Soft-delete with a PII scrub, which CLAUDE.md §9 requires by name: "not a
    # cascade". A cascade would take the appointments with it, and with them the
    # shop's revenue history, its no-show rate and its utilisation — a client
    # exercising their rights would silently rewrite somebody else's books.
    # `Appointment.client` has been `SET_NULL` since slice 3 for exactly this.

    #: When the personal data was removed. The row survives; the person does
    #: not. Null means an ordinary client.
    scrubbed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    #: How it happened, for the audit trail a controller has to be able to
    #: produce. Deliberately not a free-text field.
    scrub_reason = models.CharField(max_length=16, blank=True, choices=ScrubReason)

    #: Set when the client asks, through the manage link in their SMS. A
    #: request, not an erasure: the token proves control of the phone, which is
    #: the same verification the deposit relies on, but a one-tap irreversible
    #: erase behind an SMS link is too easy to hit by accident. The owner acts
    #: on it, and the DPA clock starts here rather than when they get round to
    #: looking.
    erasure_requested_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "clients"
        ordering = ["full_name", "phone"]
        constraints = [
            # One person per number per organization. Not globally unique: the
            # same phone can be a client of two unrelated salons, and those are
            # two separate records under two separate controllers.
            #
            # Two exclusions, both of them rows with no number to deduplicate
            # on. The constraint means "one person per *number*", and where
            # there is no number it has nothing to say.
            #
            # **Scrubbed rows**, because a scrub blanks the phone: the second
            # erasure in an organization would collide with the first and the
            # write would fail, turning "this person asked to be forgotten"
            # into a 500 whose cause is a unique index. The alternative — a
            # unique placeholder per scrubbed row — keeps the constraint total
            # at the cost of inventing an identifier for somebody who asked not
            # to be identifiable.
            #
            # **Blank phones**, because a walk-in can be recorded with a name
            # and no number at all (`scheduling/views.py`, the attach-client
            # path). Two unnamed people at the chair on a Tuesday are two
            # people, and a constraint that made them one would silently merge
            # their visit histories.
            models.UniqueConstraint(
                fields=["organization", "phone"],
                condition=Q(scrubbed_at__isnull=True) & ~Q(phone=""),
                name="one_client_per_phone_per_org",
            ),
        ]

    def __str__(self):
        return self.full_name or self.phone or "(erased)"

    def save(self, *args, **kwargs):
        # A scrubbed row has no number left to normalise, and `normalize_phone`
        # refuses a blank one — correctly, because an ordinary client must have
        # one. Guarding here rather than loosening the validator keeps "a client
        # with no phone number" impossible everywhere except after an erasure.
        if self.phone:
            self.phone = normalize_phone(self.phone)
        return super().save(*args, **kwargs)

    @property
    def is_erased(self):
        return self.scrubbed_at is not None
