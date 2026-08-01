import uuid

from django.db import models

from core.managers import OrgScopedManager


class TimeStampedModel(models.Model):
    """UUID primary keys throughout.

    Sequential integer ids leak tenant volume and make org and appointment ids
    guessable from the outside — and slice 5 puts appointment ids in URLs that
    are opened from an SMS by someone with no login.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class OrgScopedModel(TimeStampedModel):
    """Anything that belongs to one tenant. See core/managers.py."""

    organization = models.ForeignKey(
        "orgs.Organization",
        on_delete=models.CASCADE,
        related_name="%(class)ss",
    )

    objects = OrgScopedManager()

    class Meta:
        abstract = True
