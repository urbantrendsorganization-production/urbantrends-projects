import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from accounts.phone import normalize_phone
from core.managers import OrgScopedQuerySet
from core.models import OrgScopedModel, TimeStampedModel


class Role(models.TextChoices):
    OWNER = "owner", "Owner"
    MANAGER = "manager", "Manager"
    STAFF = "staff", "Staff"


class SubscriptionStatus(models.TextChoices):
    TRIALING = "trialing", "Trialing"
    ACTIVE = "active", "Active"
    PAST_DUE = "past_due", "Past due"
    CANCELLED = "cancelled", "Cancelled"


class Organization(TimeStampedModel):
    """Billing boundary and tenant root. One login, one bill, many shops.

    CLAUDE.md §12: subscription state is a plain enum. No fair-use ceiling is
    modelled and no limit is enforced until there is a billing slice that needs
    one.
    """

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=64, unique=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_organizations",
    )
    subscription_status = models.CharField(
        max_length=16, choices=SubscriptionStatus.choices, default=SubscriptionStatus.TRIALING
    )
    # CLAUDE.md §9 — Kenya DPA 2019 requires a stated retention period. The
    # design's privacy screen defaults to 24 months.
    retention_months = models.PositiveSmallIntegerField(default=24)

    class Meta:
        db_table = "organizations"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(subscription_status__in=SubscriptionStatus.values),
                name="organization_subscription_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(retention_months__gte=1),
                name="organization_retention_months_positive",
            ),
        ]

    def __str__(self):
        return self.name


class Membership(OrgScopedModel):
    """Who may act on this organization.

    Distinct from `Staff`, which arrives in slice 2 and is a bookable person at
    a shop. A manager has a Membership without being bookable; a stylist has
    both. Collapsing them would mean either managers appearing in the client's
    stylist picker or stylists being unable to log in.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.STAFF)
    is_active = models.BooleanField(default=True)
    invited_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="memberships_invited",
    )

    class Meta:
        db_table = "memberships"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "user"], name="one_membership_per_user_per_org"
            ),
            models.CheckConstraint(
                condition=models.Q(role__in=Role.values), name="membership_role_valid"
            ),
        ]

    def __str__(self):
        return f"{self.user.full_name} · {self.role} · {self.organization.name}"


def generate_invite_token():
    return secrets.token_urlsafe(32)


def hash_invite_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


class StaffInviteQuerySet(OrgScopedQuerySet):
    """Extends the org-scoped queryset, not a plain one.

    Overriding `objects` with an unguarded manager would quietly opt this model
    out of the tenancy guard, which is exactly the mistake the guard exists to
    catch. There is a test for this.
    """

    def pending(self):
        return self.filter(
            accepted_at__isnull=True, revoked_at__isnull=True, expires_at__gt=timezone.now()
        )


class StaffInvite(OrgScopedModel):
    """An invite exists before a User does.

    That is the whole reason this is not just a Membership row with a null user:
    the design's staff list shows `Invited 3 Aug · hasn't signed in yet` with a
    resend action, and doubles as the owner's adoption report. Without a record
    that predates the account, that state cannot be drawn.
    """

    phone = models.CharField(max_length=16)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.STAFF)
    # Only the hash is stored. The plaintext token exists once, in the SMS.
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    sent_count = models.PositiveSmallIntegerField(default=1)
    last_sent_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invites_created",
    )

    objects = models.Manager.from_queryset(StaffInviteQuerySet)()  # org-scoped, see above

    class Meta:
        db_table = "staff_invites"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role__in=Role.values), name="invite_role_valid"
            ),
            models.UniqueConstraint(
                fields=["organization", "phone"],
                condition=models.Q(accepted_at__isnull=True, revoked_at__isnull=True),
                name="one_open_invite_per_phone_per_org",
            ),
        ]

    def __str__(self):
        return f"invite {self.phone} · {self.organization.name}"

    def save(self, *args, **kwargs):
        self.phone = normalize_phone(self.phone)
        return super().save(*args, **kwargs)

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def is_pending(self):
        return self.accepted_at is None and self.revoked_at is None and not self.is_expired

    @classmethod
    def issue(cls, *, organization, phone, role=Role.STAFF, created_by=None):
        """Returns (invite, plaintext_token). The token is never stored."""
        token = generate_invite_token()
        invite = cls(
            organization=organization,
            phone=phone,
            role=role,
            token_hash=hash_invite_token(token),
            expires_at=timezone.now() + timedelta(days=settings.STAFF_INVITE_TTL_DAYS),
            created_by=created_by,
        )
        invite.save()
        return invite, token

    @classmethod
    def find_by_token(cls, token):
        """Constant-time lookup by token. Returns None rather than raising.

        The hash column is unique and indexed, so this is one indexed read; the
        `compare_digest` is belt-and-braces against a future refactor that
        replaces the index lookup with a scan.
        """
        if not token:
            return None
        candidate = hash_invite_token(token)
        invite = cls.objects.unscoped().filter(token_hash=candidate).first()
        if invite is None:
            return None
        return invite if hmac.compare_digest(invite.token_hash, candidate) else None

    def rotate_token(self):
        """Resend issues a new token and invalidates the old one."""
        token = generate_invite_token()
        self.token_hash = hash_invite_token(token)
        self.expires_at = timezone.now() + timedelta(days=settings.STAFF_INVITE_TTL_DAYS)
        self.sent_count += 1
        self.last_sent_at = timezone.now()
        self.save(
            update_fields=["token_hash", "expires_at", "sent_count", "last_sent_at", "updated_at"]
        )
        return token


__all__ = [
    "Membership",
    "Organization",
    "Role",
    "StaffInvite",
    "SubscriptionStatus",
    "generate_invite_token",
    "hash_invite_token",
]
