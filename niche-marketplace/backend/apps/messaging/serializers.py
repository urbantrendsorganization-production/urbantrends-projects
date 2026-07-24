from rest_framework import serializers

from apps.catalog.models import Listing
from apps.messaging.models import Conversation, Message


class PartySerializer(serializers.Serializer):
    """Minimal user card for a conversation participant."""

    id = serializers.IntegerField()
    name = serializers.CharField(source="public_name")
    avatar = serializers.ImageField()


class ConversationListingSerializer(serializers.ModelSerializer):
    """Just enough of the listing to render a thread header/inbox row."""

    thumbnail = serializers.SerializerMethodField()

    class Meta:
        model = Listing
        fields = ["id", "title", "price", "currency", "status", "thumbnail"]

    def get_thumbnail(self, obj: Listing) -> str | None:
        image = obj.images.all()[0] if obj.images.all() else None
        if not image:
            return None
        file = image.thumbnail or image.image
        if not file:
            return None
        request = self.context.get("request")
        url = file.url
        return request.build_absolute_uri(url) if request else url


class MessageSerializer(serializers.ModelSerializer):
    is_mine = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = ["id", "sender", "body", "is_mine", "read_at", "created_at"]
        read_only_fields = fields

    def get_is_mine(self, obj: Message) -> bool:
        request = self.context.get("request")
        return bool(request and obj.sender_id == request.user.id)


class ConversationSerializer(serializers.ModelSerializer):
    listing = ConversationListingSerializer(read_only=True)
    other_party = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    unread = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            "id",
            "listing",
            "other_party",
            "last_message",
            "unread",
            "last_message_at",
            "created_at",
        ]

    def _viewer(self):
        request = self.context.get("request")
        return request.user if request else None

    def get_other_party(self, obj: Conversation) -> dict:
        viewer = self._viewer()
        other = obj.other_party(viewer) if viewer else obj.seller
        return PartySerializer(other, context=self.context).data

    def get_last_message(self, obj: Conversation) -> dict | None:
        # ``messages`` is prefetched and ordered by created_at.
        messages = list(obj.messages.all())
        if not messages:
            return None
        last = messages[-1]
        return {
            "body": last.body,
            "created_at": last.created_at,
            "sender": last.sender_id,
        }

    def get_unread(self, obj: Conversation) -> int:
        viewer = self._viewer()
        if not viewer:
            return 0
        return sum(
            1
            for m in obj.messages.all()
            if m.read_at is None and m.sender_id != viewer.id
        )


class StartConversationSerializer(serializers.Serializer):
    """Input for opening (or re-opening) a thread from a listing."""

    listing = serializers.PrimaryKeyRelatedField(
        queryset=Listing.objects.alive()
    )


class MessageCreateSerializer(serializers.Serializer):
    body = serializers.CharField()


class ReportSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)
