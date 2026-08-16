"""The client list an owner works from, and nothing more.

There has never been a client API. Slice 3 said so in the model's docstring and
left it to "slice 5", which built the booking flow and did not need one. Slice
14 needs exactly enough of one to satisfy CLAUDE.md §9: find a person, see what
is held, export it, remove it.

Deliberately not a CRUD surface. There is no create — clients come into
existence by booking or by being recorded at the chair — and no destroy, because
§9 says soft-delete with a scrub and a `DELETE` verb that did something else
would be the wrong shape wearing the right name.
"""

from rest_framework import serializers

from clients.models import Client


class ClientSerializer(serializers.ModelSerializer):
    """One row in the owner's list."""

    is_erased = serializers.BooleanField(read_only=True)
    #: Surfaced so the list can sort and badge by it. A shop that has been
    #: asked has a clock running, and the screen's job is to make that visible
    #: rather than leave it in a column nobody queries.
    erasure_requested_at = serializers.DateTimeField(read_only=True)
    last_seen = serializers.SerializerMethodField()
    visits = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = [
            "id",
            "full_name",
            "phone",
            "notes",
            "is_erased",
            "scrubbed_at",
            "scrub_reason",
            "erasure_requested_at",
            "last_seen",
            "visits",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "is_erased",
            "scrubbed_at",
            "scrub_reason",
            "erasure_requested_at",
            "created_at",
        ]

    def get_last_seen(self, client):
        # `getattr` because the annotation is only present on the list
        # queryset; the detail view serialises a plain instance.
        value = getattr(client, "last_seen", None)
        return value.isoformat() if value else None

    def get_visits(self, client):
        return getattr(client, "visits", None)

    def validate(self, attrs):
        if self.instance and self.instance.is_erased and attrs:
            # Writing a name back onto a scrubbed row would un-erase somebody by
            # accident — a note typed into the wrong screen, and the person is
            # in the database again with no record of how.
            raise serializers.ValidationError(
                "This client has been erased. Their details cannot be edited back in."
            )
        return attrs


class ErasurePlanSerializer(serializers.Serializer):
    """What erasing will cost, for the confirm screen. Read-only."""

    appointments = serializers.IntegerField()
    credit_kes = serializers.IntegerField()
    already_erased = serializers.BooleanField()
