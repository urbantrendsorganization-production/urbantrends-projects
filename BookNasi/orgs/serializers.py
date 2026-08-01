from django.contrib.auth import password_validation
from django.utils.text import slugify
from rest_framework import serializers

from accounts.serializers import PhoneField, UserSerializer
from orgs.models import Membership, Organization, Role, StaffInvite


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = [
            "id",
            "name",
            "slug",
            "subscription_status",
            "retention_months",
            "created_at",
        ]
        read_only_fields = ["id", "slug", "subscription_status", "created_at"]


class SignupSerializer(serializers.Serializer):
    """The standalone front door: one call creates User, Organization and owner Membership."""

    organization_name = serializers.CharField(max_length=120)
    full_name = serializers.CharField(max_length=120)
    phone = PhoneField()
    email = serializers.EmailField(required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate_password(self, value):
        password_validation.validate_password(value)
        return value

    def validate_phone(self, value):
        from accounts.models import User

        if User.objects.filter(phone=value).exists():
            raise serializers.ValidationError("An account already uses that phone number.")
        return value


class MembershipSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    organization_name = serializers.CharField(source="organization.name", read_only=True)

    class Meta:
        model = Membership
        fields = [
            "id",
            "organization",
            "organization_name",
            "user",
            "role",
            "is_active",
            "invited_at",
            "accepted_at",
        ]
        read_only_fields = ["id", "organization", "organization_name", "user", "accepted_at"]


class StaffInviteSerializer(serializers.ModelSerializer):
    phone = PhoneField()
    status = serializers.SerializerMethodField()

    class Meta:
        model = StaffInvite
        fields = [
            "id",
            "phone",
            "role",
            "status",
            "expires_at",
            "accepted_at",
            "revoked_at",
            "sent_count",
            "last_sent_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "expires_at",
            "accepted_at",
            "revoked_at",
            "sent_count",
            "last_sent_at",
            "created_at",
        ]

    def get_status(self, invite):
        """Drives the design's `Invited 3 Aug · hasn't signed in yet` row."""
        if invite.accepted_at:
            return "accepted"
        if invite.revoked_at:
            return "revoked"
        if invite.is_expired:
            return "expired"
        return "pending"

    def validate_role(self, value):
        if value == Role.OWNER:
            raise serializers.ValidationError(
                "An organization has one owner, set at signup. Invite a manager instead."
            )
        return value


def unique_org_slug(name):
    base = slugify(name)[:56] or "shop"
    slug = base
    suffix = 2
    while Organization.objects.filter(slug=slug).exists():
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug
