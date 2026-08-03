"""Serializers for the unauthenticated public booking surface.

**These share no code with `shops/serializers.py`, deliberately.**

CLAUDE.md §1: "Build every API as if a third party will integrate it, because
one will." The tempting version of this module is to import `ShopSerializer`
and subclass it with a shorter `fields` list. That fails the first time someone
adds a field to the parent — the new field appears on the public endpoint
silently, because `fields` on the parent is what changed, not the child. The
same trap exists for a single serializer with an `if request.user` branch.

So the classes here are written out in full, declare their fields explicitly,
and are tested by asserting the exact field set. Duplication is the point: the
two surfaces are meant to be able to diverge without either dragging the other
along.

What must never appear here:

- `organization`, or anything that reveals which tenant owns the shop
- `buffer_minutes` — internal scheduling policy, not the client's business
- `is_active`, `is_publicly_listed` — a hidden row is simply absent instead
- staff `membership`, which links to a user account

What must appear here, because the client cannot complete a booking without it:

- `hold_ttl_minutes`, which drives the visible countdown (CLAUDE.md §10)
- `refund_window_hours`, because the refund rule is stated *before* payment
- `deposit_amount`, the exact figure that will be pushed to M-Pesa
"""

from rest_framework import serializers

from shops.models import OpeningHours, Service, Shop, Staff


class PublicOpeningHoursSerializer(serializers.Serializer):
    weekday = serializers.IntegerField(read_only=True)
    opens_at = serializers.TimeField(read_only=True)
    closes_at = serializers.TimeField(read_only=True)

    class Meta:
        model = OpeningHours


class PublicShopSerializer(serializers.Serializer):
    """Explicit fields, not a ModelSerializer.

    A `ModelSerializer` with `exclude` would leak any future column by default;
    one with `fields` would still inherit `Meta` changes. Declaring each field
    by hand means a new model column reaches this endpoint only when someone
    writes a line here.
    """

    slug = serializers.SlugField(read_only=True)
    name = serializers.CharField(read_only=True)
    address = serializers.CharField(read_only=True)
    area = serializers.CharField(read_only=True)
    directions_url = serializers.URLField(read_only=True)
    phone = serializers.CharField(read_only=True)
    logo_url = serializers.URLField(read_only=True)
    accent_color = serializers.CharField(read_only=True)
    # Drives the hold countdown. The countdown is not themeable and not
    # hideable — CLAUDE.md §10 — so the client has to be told its length.
    hold_ttl_minutes = serializers.IntegerField(read_only=True)
    # The refund rule is shown before payment, never after.
    refund_window_hours = serializers.IntegerField(read_only=True)
    opening_hours = serializers.SerializerMethodField()

    class Meta:
        model = Shop

    def get_opening_hours(self, shop):
        rows = shop.opening_hours.order_by("weekday")
        return PublicOpeningHoursSerializer(rows, many=True).data


class PublicServiceSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    duration_minutes = serializers.IntegerField(read_only=True)
    price = serializers.IntegerField(read_only=True)
    deposit_mode = serializers.CharField(read_only=True)
    #: The figure the client is shown and the figure slice 6 pushes to M-Pesa.
    #: One number, computed once, by shops.money.deposit_amount.
    deposit_amount = serializers.IntegerField(read_only=True)
    balance_due = serializers.SerializerMethodField()

    class Meta:
        model = Service

    def get_balance_due(self, service):
        """What is still owed at the shop. The design shows this on the confirm
        card next to the deposit, so it is computed here rather than in the
        client, where a rounding difference would show up as a wrong number."""
        return max(service.price - service.deposit_amount, 0)


class HoldRequestSerializer(serializers.Serializer):
    """What the confirm step sends. Input only.

    No name and no email. CLAUDE.md §12: the phone number is the whole of the
    client's identity, and the STK push to it is the verification. Asking for
    anything else here would be a field that costs bookings and buys nothing —
    the shop learns the name when the client sits down.
    """

    service = serializers.UUIDField()
    #: Required, even when the client picked "anyone available". The
    #: availability response names the stylist who owns each start precisely so
    #: this can be concrete — `Appointment.staff` is not nullable and the
    #: exclusion constraint is per staff member.
    staff = serializers.UUIDField()
    starts_at = serializers.DateTimeField()
    phone = serializers.CharField(max_length=20)
    #: Same guard as the staff app's walk-in: a client on 3G who taps Confirm,
    #: sees nothing, and taps again must not create two holds and be told the
    #: second collided with the first.
    client_request_id = serializers.CharField(required=False, allow_blank=True, max_length=64)

    def validate_phone(self, value):
        from accounts.phone import InvalidPhoneNumber, normalize_phone

        try:
            return normalize_phone(value)
        except InvalidPhoneNumber as exc:
            # The library message names the accepted formats, which is what a
            # client mistyping their own number actually needs.
            raise serializers.ValidationError(str(exc)) from exc


class PublicHoldSerializer(serializers.Serializer):
    """The held slot, as the client's countdown screen needs it.

    Deliberately thin. This is an unauthenticated endpoint keyed by an
    unguessable id, and everything it returns is either something the caller
    just sent or something already on the public service list. No client name,
    no other bookings, nothing about the shop's day.
    """

    id = serializers.UUIDField(read_only=True)
    status = serializers.CharField(read_only=True)
    starts_at = serializers.DateTimeField(read_only=True)
    ends_at = serializers.DateTimeField(read_only=True)
    local_time = serializers.SerializerMethodField()
    hold_expires_at = serializers.DateTimeField(read_only=True)
    #: Seconds left, computed server-side at the moment of the response. The
    #: countdown is a rendering of this and never the thing that decides — a
    #: client whose clock is wrong must still be told the truth about the slot.
    seconds_remaining = serializers.SerializerMethodField()
    staff_name = serializers.SerializerMethodField()
    service_name = serializers.SerializerMethodField()
    price_kes = serializers.IntegerField(source="price_snapshot", read_only=True)
    deposit_kes = serializers.IntegerField(source="deposit_snapshot", read_only=True)
    balance_kes = serializers.SerializerMethodField()

    def get_local_time(self, appointment):
        from scheduling.availability import LOCAL_TZ

        return appointment.starts_at.astimezone(LOCAL_TZ).strftime("%H:%M")

    def get_seconds_remaining(self, appointment):
        from django.utils import timezone

        if appointment.hold_expires_at is None:
            return 0
        return max(0, int((appointment.hold_expires_at - timezone.now()).total_seconds()))

    def get_staff_name(self, appointment):
        return appointment.staff.display_name

    def get_service_name(self, appointment):
        return appointment.service.name

    def get_balance_kes(self, appointment):
        return max(appointment.price_snapshot - appointment.deposit_snapshot, 0)


class PublicStaffSerializer(serializers.Serializer):
    """No membership, no user id, no phone. A client picking a stylist needs a
    name and a duration, and nothing that identifies an account."""

    id = serializers.UUIDField(read_only=True)
    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = Staff
