from rest_framework import serializers

from apps.catalog import services
from apps.catalog.models import Category, Condition, Listing, ListingImage


class CategorySerializer(serializers.ModelSerializer):
    """Flat category node. ``attribute_schema`` here is the *effective* schema
    (own fields merged over ancestors'), so a client can render the full form
    for any category without walking the tree itself.
    """

    depth = serializers.IntegerField(read_only=True)
    attribute_schema = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ["id", "name", "slug", "parent", "depth", "attribute_schema"]

    def get_attribute_schema(self, obj: Category) -> list[dict]:
        return obj.effective_schema()


class ListingImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListingImage
        fields = ["id", "image", "thumbnail", "order"]
        read_only_fields = fields


class SellerSerializer(serializers.Serializer):
    """Minimal seller card embedded in a listing."""

    id = serializers.IntegerField()
    name = serializers.CharField(source="public_name")
    avatar = serializers.ImageField()
    location = serializers.CharField()


class ListingSerializer(serializers.ModelSerializer):
    """Read representation of a listing."""

    seller = SellerSerializer(read_only=True)
    category = CategorySerializer(read_only=True)
    images = ListingImageSerializer(many=True, read_only=True)
    condition_display = serializers.CharField(
        source="get_condition_display", read_only=True
    )

    class Meta:
        model = Listing
        fields = [
            "id",
            "seller",
            "category",
            "title",
            "description",
            "price",
            "currency",
            "condition",
            "condition_display",
            "location",
            "status",
            "attributes",
            "images",
            "created_at",
            "published_at",
        ]
        read_only_fields = fields


class ListingWriteSerializer(serializers.ModelSerializer):
    """Create/update a listing. Status is never set here — it moves only through
    the transition endpoint (and thus the service state machine).
    """

    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all())
    condition = serializers.ChoiceField(choices=Condition.choices)
    attributes = serializers.JSONField(required=False)

    class Meta:
        model = Listing
        fields = [
            "id",
            "category",
            "title",
            "description",
            "price",
            "currency",
            "condition",
            "location",
            "attributes",
        ]
        read_only_fields = ["id"]

    def create(self, validated_data: dict) -> Listing:
        seller = self.context["request"].user
        return services.create_listing(seller=seller, **validated_data)

    def update(self, instance: Listing, validated_data: dict) -> Listing:
        return services.update_listing(instance, **validated_data)

    def to_representation(self, instance: Listing) -> dict:
        # Echo back the full read shape after a write.
        return ListingSerializer(instance, context=self.context).data


class TransitionSerializer(serializers.Serializer):
    status = serializers.CharField()
