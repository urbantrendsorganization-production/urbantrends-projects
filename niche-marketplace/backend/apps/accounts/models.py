from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from apps.accounts.managers import UserManager
from apps.core.models import TimeStampedModel


class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    """Custom user with email as the unique identifier (no username).

    Auth fields and public-profile fields live together on the user so a
    profile lookup is a single row. ``created_at`` (from ``TimeStampedModel``)
    doubles as the public "joined" date.
    """

    email = models.EmailField(unique=True)
    # Optional contact number surfaced on the user's profile.
    phone = models.CharField(max_length=32, blank=True)

    # Public profile
    display_name = models.CharField(max_length=80, blank=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)
    location = models.CharField(max_length=120, blank=True)

    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_verified = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "accounts_user"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.email

    @property
    def public_name(self) -> str:
        """Display name if set, otherwise the local part of the email."""
        return self.display_name or self.email.split("@")[0]
