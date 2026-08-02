"""Availability and staff-day responses.

Times go out in **both** forms. `starts_at` is a UTC instant, which is what a
third-party integrator and slice 5's confirm step should use. `local_time` is
the EAT wall clock as a plain `HH:MM` string, which is what the design's slot
chips print — computed here rather than in the client, so a browser with a
misconfigured timezone cannot render 09:00 as 06:00 and book the wrong hour.

Slice 4 adds the write serializers, and every one of them is input-only. There
is no `ModelSerializer` on `Appointment` with writable fields anywhere in this
file, on purpose: `booking.create_appointment` and `transitions.apply_transition`
are the only ways a row is written, and a serializer with `.save()` on it would
be a second insert path that skips the re-derivation and the advisory lock.
"""

from rest_framework import serializers

from scheduling.availability import LOCAL_TZ
from scheduling.statuses import AppointmentStatus
from scheduling.transitions import undo_target


class SlotSerializer(serializers.Serializer):
    starts_at = serializers.DateTimeField(read_only=True)
    ends_at = serializers.DateTimeField(read_only=True)
    local_time = serializers.SerializerMethodField()
    duration_minutes = serializers.IntegerField(read_only=True)

    def get_local_time(self, slot):
        starts_at = slot["starts_at"] if isinstance(slot, dict) else slot.starts_at
        return starts_at.astimezone(LOCAL_TZ).strftime("%H:%M")


class AnyStaffSlotSerializer(SlotSerializer):
    """ "Anyone available", with the stylist who actually owns each start.

    Named because the confirm step books against a concrete person — see
    `_earliest_per_start` in views.py. Without these two fields the client
    would have to re-query to find out who it just booked with.
    """

    staff_id = serializers.UUIDField(read_only=True)
    staff_name = serializers.CharField(read_only=True)


class StaffSlotsSerializer(serializers.Serializer):
    """One stylist's slots. The org-scoped day view returns a list of these."""

    staff_id = serializers.UUIDField(read_only=True)
    display_name = serializers.CharField(read_only=True)
    slots = SlotSerializer(many=True, read_only=True)


# ------------------------------------------------------------- the staff day


class AppointmentSerializer(serializers.Serializer):
    """One row on Today, and the whole of the detail card.

    Read-only. One shape for both screens rather than a list serializer and a
    detail serializer, because the detail card opens from a row that is already
    in memory and a second shape would make it flicker as the fetch lands.
    """

    id = serializers.UUIDField(read_only=True)
    status = serializers.CharField(read_only=True)
    status_label = serializers.SerializerMethodField()
    source = serializers.CharField(read_only=True)
    is_waiting = serializers.BooleanField(read_only=True)

    starts_at = serializers.DateTimeField(read_only=True)
    ends_at = serializers.DateTimeField(read_only=True)
    #: Where it was scheduled to end, which stops matching `ends_at` the moment
    #: somebody finishes early. The detail card shows the booked span.
    booked_ends_at = serializers.DateTimeField(read_only=True)
    started_at = serializers.DateTimeField(read_only=True)
    finished_at = serializers.DateTimeField(read_only=True)
    local_time = serializers.SerializerMethodField()

    staff_id = serializers.UUIDField(read_only=True)
    staff_name = serializers.SerializerMethodField()
    service_name = serializers.SerializerMethodField()
    client_name = serializers.SerializerMethodField()
    client_phone = serializers.SerializerMethodField()

    price_kes = serializers.IntegerField(source="price_snapshot", read_only=True)
    deposit_kes = serializers.IntegerField(source="deposit_snapshot", read_only=True)
    duration_minutes = serializers.IntegerField(source="duration_snapshot", read_only=True)

    #: What the single Undo button would do, or null when there is nothing to
    #: undo. Sent rather than inferred so the button's existence and the
    #: server's transition table cannot disagree.
    undo_to = serializers.SerializerMethodField()

    def get_status_label(self, appointment):
        if appointment.is_waiting and appointment.source == "walk_in":
            # The design's walk-in state. Derived, not stored — see
            # Appointment.is_waiting.
            return "Waiting"
        return AppointmentStatus(appointment.status).label

    def get_local_time(self, appointment):
        return appointment.starts_at.astimezone(LOCAL_TZ).strftime("%H:%M")

    def get_staff_name(self, appointment):
        return appointment.staff.display_name

    def get_service_name(self, appointment):
        return appointment.service.name

    def get_client_name(self, appointment):
        return appointment.client.full_name if appointment.client_id else ""

    def get_undo_to(self, appointment):
        target = undo_target(appointment)
        return target.value if target else None

    def get_client_phone(self, appointment):
        # Present because the design's detail card has a call button. Never on
        # the list response — a day's phone numbers in one payload is a DPA §9
        # surface with no screen behind it.
        if not self.context.get("include_contact") or not appointment.client_id:
            return ""
        return appointment.client.phone


class DayTotalsSerializer(serializers.Serializer):
    appointments = serializers.IntegerField(read_only=True)
    walk_ins = serializers.IntegerField(read_only=True)
    deposit_total_kes = serializers.IntegerField(read_only=True)


class ServiceChipSerializer(serializers.Serializer):
    """Tap 1. The duration is *this staff member's*, resolved server-side."""

    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    price_kes = serializers.IntegerField(source="price", read_only=True)
    duration_minutes = serializers.SerializerMethodField()

    def get_duration_minutes(self, service):
        return self.context["durations"].get(service.id, service.duration_minutes)


class StaffChipSerializer(serializers.Serializer):
    """Tap 2. `free_now` drives the design's "others show when they're free"."""

    id = serializers.UUIDField(read_only=True)
    display_name = serializers.CharField(read_only=True)
    is_me = serializers.SerializerMethodField()
    free_now = serializers.SerializerMethodField()
    free_from = serializers.SerializerMethodField()

    def get_is_me(self, staff):
        return str(staff.id) == str(self.context.get("me_id"))

    def get_free_now(self, staff):
        return bool(self.context["freedom"].get(staff.id, (True, None))[0])

    def get_free_from(self, staff):
        return self.context["freedom"].get(staff.id, (True, None))[1]


class OptionSerializer(serializers.Serializer):
    """A collision resolution, computed by the engine — see collisions.py.

    Every field the walk-in endpoint takes is here, so choosing an option is a
    resubmit of the same request with these values substituted. The client does
    no arithmetic: a UI that worked out "shorten to 12:00" for itself would be a
    second availability engine on the far side of a network boundary.
    """

    kind = serializers.CharField(read_only=True)
    label = serializers.CharField(read_only=True)
    staff_id = serializers.CharField(read_only=True)
    staff_name = serializers.CharField(read_only=True)
    starts_at = serializers.DateTimeField(read_only=True)
    duration_minutes = serializers.IntegerField(read_only=True)
    allow_over_completed = serializers.BooleanField(read_only=True)


# ------------------------------------------------------------------- requests


class WalkInSerializer(serializers.Serializer):
    """Tap 3, submitted. Input only — see the module docstring."""

    service = serializers.UUIDField()
    staff = serializers.UUIDField()
    #: Optional: the server uses `now` when it is absent, which is what the
    #: three-tap flow sends. Present when the staff member adjusted the time or
    #: is resubmitting a collision option.
    starts_at = serializers.DateTimeField(required=False, allow_null=True)
    #: Set by "Waiting, not started". The row is written but the clock does not
    #: start — `confirmed` with a null `started_at`.
    waiting = serializers.BooleanField(required=False, default=False)
    #: Only ever true when it came back from an `Option` the engine produced.
    allow_over_completed = serializers.BooleanField(required=False, default=False)
    duration_minutes = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    #: The offline retry guard. Generated by the phone, stable across retries.
    client_request_id = serializers.CharField(required=False, allow_blank=True, max_length=64)


class ClientDetailsSerializer(serializers.Serializer):
    """Name and phone, asked **after** saving and never before — the design is
    explicit and CLAUDE.md §4 makes anything else a regression."""

    full_name = serializers.CharField(required=False, allow_blank=True, max_length=120)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=16)

    def validate(self, attrs):
        if not attrs.get("full_name") and not attrs.get("phone"):
            raise serializers.ValidationError("Give a name or a number.")
        return attrs


class TransitionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=AppointmentStatus.choices)
