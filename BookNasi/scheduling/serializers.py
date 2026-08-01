"""Availability responses.

Read-only throughout: slice 3 has no write endpoint. `create_appointment` in
`booking.py` is the only way an appointment comes into existence, and slices 4
and 5 own the routes that call it.

Times go out in **both** forms. `starts_at` is a UTC instant, which is what a
third-party integrator and slice 5's confirm step should use. `local_time` is
the EAT wall clock as a plain `HH:MM` string, which is what the design's slot
chips print — computed here rather than in the client, so a browser with a
misconfigured timezone cannot render 09:00 as 06:00 and book the wrong hour.
"""

from rest_framework import serializers

from scheduling.availability import LOCAL_TZ


class SlotSerializer(serializers.Serializer):
    starts_at = serializers.DateTimeField(read_only=True)
    ends_at = serializers.DateTimeField(read_only=True)
    local_time = serializers.SerializerMethodField()
    duration_minutes = serializers.IntegerField(read_only=True)

    def get_local_time(self, slot):
        return slot.starts_at.astimezone(LOCAL_TZ).strftime("%H:%M")


class StaffSlotsSerializer(serializers.Serializer):
    """One stylist's slots. The org-scoped day view returns a list of these."""

    staff_id = serializers.UUIDField(read_only=True)
    display_name = serializers.CharField(read_only=True)
    slots = SlotSerializer(many=True, read_only=True)
