from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from apps.accounts.managers import UserManager
from apps.core.models import TimeStampedModel


class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    """Custom user with email as the unique identifier (no username).

    Richer profile fields (display name, avatar, location) arrive in Phase 1;
    Phase 0 only establishes the model so it exists before the first migration.
    """

    email = models.EmailField(unique=True)
    # Optional contact number surfaced on the user's profile.
    phone = models.CharField(max_length=32, blank=True)

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
