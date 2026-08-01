import uuid

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone

from accounts.phone import normalize_phone


class UserManager(models.Manager):
    use_in_migrations = True

    def _create(self, phone, password, **extra):
        if not phone:
            raise ValueError("A phone number is required")
        email = extra.pop("email", None) or None
        user = self.model(
            phone=normalize_phone(phone),
            email=self.normalize_email(email),
            **extra,
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    @staticmethod
    def normalize_email(email):
        # Stored lower-cased so `Owner@Shop.co.ke` and `owner@shop.co.ke` cannot
        # become two accounts. None rather than "" so the unique index permits
        # any number of users without an email — most staff will not have one.
        return email.strip().lower() if email else None

    def create_user(self, phone, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create(phone, password, **extra)

    def create_superuser(self, phone, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        if not extra["is_staff"] or not extra["is_superuser"]:
            raise ValueError("A superuser must have is_staff and is_superuser set")
        return self._create(phone, password, **extra)

    def get_by_natural_key(self, username):
        return self.get(phone=normalize_phone(username))


class User(AbstractBaseUser, PermissionsMixin):
    """Phone-first identity.

    CLAUDE.md §12: staff invites arrive by SMS and salon staff frequently have
    no working email, so the phone is the username and email is optional.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone = models.CharField(max_length=16, unique=True)
    email = models.EmailField(unique=True, null=True, blank=True)
    full_name = models.CharField(max_length=120)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False, help_text="Django admin access, not shop staff.")
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        db_table = "users"

    def __str__(self):
        return f"{self.full_name} <{self.phone}>"

    def save(self, *args, **kwargs):
        self.phone = normalize_phone(self.phone)
        self.email = UserManager.normalize_email(self.email)
        return super().save(*args, **kwargs)
