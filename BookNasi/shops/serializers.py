"""Serializers for the authenticated, org-scoped API.

These expose internal configuration — buffers, org ids, activity flags. The
public booking surface has its own serializers in `public_api/serializers.py`
and shares nothing with these by design. See that module for why.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from accounts.serializers import PhoneField
from shops.durations import ServiceNotOffered
from shops.models import (
    Leave,
    OpeningHours,
    Service,
    Shop,
    ShopClosure,
    Staff,
    StaffService,
    WorkingHours,
)
from shops.slugs import suggest_slug, validate_shop_slug


def _all_slugs():
    """Deliberately cross-tenant: shop slugs are hostnames in one global
    namespace, so a collision check has to see every tenant's. Returns strings,
    never rows — a caller learns that a name is taken, not who holds it."""
    return set(Shop.objects.unscoped().values_list("slug", flat=True))


class ShopSerializer(serializers.ModelSerializer):
    phone = PhoneField(required=False, allow_blank=True)
    #: Declared explicitly with no validators so that `validate_slug` below owns
    #: the message. Left to ModelSerializer, `unique=True` on the model attaches
    #: a UniqueValidator that fires first and answers "shop with this slug
    #: already exists" — technically true, useless to a salon owner who needs to
    #: know that booking addresses are shared across all of BookNasi and what to
    #: try instead.
    slug = serializers.SlugField(required=False, max_length=63, validators=[])

    class Meta:
        model = Shop
        fields = [
            "id",
            "name",
            "slug",
            "address",
            "area",
            "directions_url",
            "phone",
            "logo_url",
            "accent_color",
            "buffer_minutes",
            "slot_interval_minutes",
            "min_lead_minutes",
            "booking_horizon_days",
            "hold_ttl_minutes",
            "refund_window_hours",
            # Both halves of the cancellation terms, not just the first.
            # `refund_window_hours` shipped in slice 2 and this did not, so the
            # settings screen could show an owner "…becomes credit for 60 days"
            # while their own shop said 90 — the one sentence CLAUDE.md §12
            # insists is worded in a single place, previewed from a number the
            # owner could not see. The public serializer has always sent it.
            "deposit_credit_days",
            "min_deposit_amount",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
        extra_kwargs = {"slug": {"required": False}}

    def validate_slug(self, value):
        try:
            slug = validate_shop_slug(value)
        except DjangoValidationError as exc:
            # Django's ValidationError is not DRF's. Left unconverted it escapes
            # the serializer as a 500 instead of a 400 with the reason in it.
            raise serializers.ValidationError(exc.messages) from exc

        # Deliberately unscoped: shop slugs are hostnames in one global
        # namespace, so a uniqueness check *has* to look across tenants. This is
        # the only genuine cross-tenant read in the product, and it returns a
        # boolean — never a row, never a name.
        taken = Shop.objects.unscoped().filter(slug=slug)
        if self.instance:
            taken = taken.exclude(pk=self.instance.pk)
        if taken.exists():
            # Never silently suffixed. The slug is the booking address the shop
            # puts on WhatsApp; handing them `kilimani-7.booknasi.co.ke` because
            # someone else got there first is a support call, not a convenience.
            alternative = suggest_slug(slug, taken=_all_slugs())
            raise serializers.ValidationError(
                f"'{slug}' is already taken. Booking addresses are shared across all of "
                f"BookNasi, not just your organization. Try '{alternative}'."
            )
        return slug

    def validate(self, attrs):
        if not self.instance and not attrs.get("slug"):
            attrs["slug"] = suggest_slug(attrs.get("name", ""), taken=_all_slugs())
        return attrs


class OpeningHoursSerializer(serializers.ModelSerializer):
    class Meta:
        model = OpeningHours
        fields = ["id", "weekday", "opens_at", "closes_at"]

    def validate(self, attrs):
        opens = attrs.get("opens_at", getattr(self.instance, "opens_at", None))
        closes = attrs.get("closes_at", getattr(self.instance, "closes_at", None))
        if opens and closes and closes <= opens:
            raise serializers.ValidationError({"closes_at": "Closing time must be after opening."})
        return attrs


class ShopClosureSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShopClosure
        fields = ["id", "starts_on", "ends_on", "reason"]

    def validate(self, attrs):
        starts = attrs.get("starts_on", getattr(self.instance, "starts_on", None))
        ends = attrs.get("ends_on", getattr(self.instance, "ends_on", None))
        if starts and ends and ends < starts:
            raise serializers.ValidationError({"ends_on": "A closure cannot end before it starts."})
        return attrs


class StaffSerializer(serializers.ModelSerializer):
    has_signed_in = serializers.SerializerMethodField()

    class Meta:
        model = Staff
        fields = [
            "id",
            "shop",
            "membership",
            "display_name",
            "is_bookable",
            "is_active",
            "has_signed_in",
            "created_at",
        ]
        read_only_fields = ["id", "shop", "created_at"]

    def get_has_signed_in(self, staff):
        """Drives the design's adoption column on the staff list."""
        return bool(staff.membership_id and staff.membership.accepted_at)

    def validate_membership(self, membership):
        shop = self.instance.shop if self.instance else self.context.get("shop")
        if membership and shop and membership.organization_id != shop.organization_id:
            raise serializers.ValidationError("That person belongs to a different organization.")
        return membership


class WorkingHoursSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkingHours
        fields = ["id", "weekday", "starts_at", "ends_at"]

    def validate(self, attrs):
        starts = attrs.get("starts_at", getattr(self.instance, "starts_at", None))
        ends = attrs.get("ends_at", getattr(self.instance, "ends_at", None))
        if starts and ends and ends <= starts:
            raise serializers.ValidationError({"ends_at": "End time must be after start."})
        return attrs


class LeaveSerializer(serializers.ModelSerializer):
    class Meta:
        model = Leave
        fields = ["id", "starts_on", "ends_on", "reason"]

    def validate(self, attrs):
        starts = attrs.get("starts_on", getattr(self.instance, "starts_on", None))
        ends = attrs.get("ends_on", getattr(self.instance, "ends_on", None))
        if starts and ends and ends < starts:
            raise serializers.ValidationError({"ends_on": "Leave cannot end before it starts."})
        return attrs


class ServiceSerializer(serializers.ModelSerializer):
    #: Both read-only and both derived. `deposit_amount` is written by
    #: shops.money.deposit_amount on save; `is_publicly_bookable` is computed
    #: from it. Neither is settable, so neither can drift from the rule.
    deposit_amount = serializers.IntegerField(read_only=True)
    is_publicly_bookable = serializers.BooleanField(read_only=True)

    class Meta:
        model = Service
        fields = [
            "id",
            "shop",
            "name",
            "description",
            "duration_minutes",
            "price",
            "deposit_mode",
            "deposit_value",
            "deposit_amount",
            "is_active",
            "is_publicly_listed",
            "is_publicly_bookable",
            "created_at",
        ]
        read_only_fields = ["id", "shop", "created_at"]

    def validate(self, attrs):
        # Run the model's own rules rather than restating them here. Two copies
        # of the deposit validation is how the API and the database end up
        # disagreeing about what a valid service is.
        instance = self.instance or Service()
        for field, value in attrs.items():
            setattr(instance, field, value)
        if not instance.shop_id and self.context.get("shop"):
            instance.shop = self.context["shop"]
        try:
            instance.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            ) from exc
        return attrs


class StaffServiceSerializer(serializers.ModelSerializer):
    effective_duration_minutes = serializers.SerializerMethodField()

    class Meta:
        model = StaffService
        fields = [
            "id",
            "staff",
            "service",
            "duration_override_minutes",
            "is_offered",
            "effective_duration_minutes",
        ]
        read_only_fields = ["id", "staff"]

    def get_effective_duration_minutes(self, link):
        """Reads through the one resolution function, so the API can never
        report a duration the availability engine would not agree with."""
        try:
            return link.effective_duration_minutes
        except ServiceNotOffered:
            return None

    def validate_service(self, service):
        """The object-level tenancy check for this relation.

        DRF resolves the incoming id through the model's default manager, which
        is deliberately unguarded (see core/models.py) — so a foreign id
        *resolves* rather than blowing up, and is rejected here with a 400
        instead of escaping as a 500.
        """
        staff = self.instance.staff if self.instance else self.context.get("staff")
        if staff and service.shop_id != staff.shop_id:
            raise serializers.ValidationError("That service belongs to a different shop.")
        return service
