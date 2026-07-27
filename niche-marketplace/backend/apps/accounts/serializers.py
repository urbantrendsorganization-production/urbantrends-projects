from django.contrib.auth import get_user_model, password_validation
from rest_framework import serializers

from apps.accounts import services

User = get_user_model()


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(
        write_only=True, style={"input_type": "password"}
    )
    display_name = serializers.CharField(
        max_length=80, required=False, allow_blank=True, default=""
    )

    def validate_email(self, value: str) -> str:
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate_password(self, value: str) -> str:
        password_validation.validate_password(value)
        return value

    def create(self, validated_data: dict) -> User:
        return services.register_user(**validated_data)


class MeSerializer(serializers.ModelSerializer):
    """Full self view — used for reading and editing one's own profile."""

    joined_at = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "display_name",
            "avatar",
            "location",
            "phone",
            "is_verified",
            "joined_at",
        ]
        # Email and verification status aren't editable from the profile form.
        read_only_fields = ["id", "email", "is_verified", "joined_at"]


class PublicUserSerializer(serializers.ModelSerializer):
    """Public profile — deliberately omits email, phone, and status flags."""

    name = serializers.CharField(source="public_name", read_only=True)
    joined_at = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = User
        fields = ["id", "name", "display_name", "avatar", "location", "joined_at"]


class VerifyEmailSerializer(serializers.Serializer):
    token = serializers.CharField()


class ResendVerificationSerializer(serializers.Serializer):
    email = serializers.EmailField()
