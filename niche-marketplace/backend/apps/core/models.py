from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base giving every model ``created_at`` / ``updated_at``.

    Per project convention, all models inherit from this.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
