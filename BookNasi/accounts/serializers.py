from django.contrib.auth import authenticate, password_validation
from rest_framework import serializers

from accounts.models import User
from accounts.phone import InvalidPhoneNumber, normalize_phone


class PhoneField(serializers.CharField):
    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        try:
            return normalize_phone(value)
        except InvalidPhoneNumber as exc:
            raise serializers.ValidationError(str(exc)) from exc


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "phone", "email", "full_name", "date_joined"]
        read_only_fields = fields


class LoginSerializer(serializers.Serializer):
    phone = PhoneField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate(self, attrs):
        user = authenticate(
            request=self.context.get("request"),
            username=attrs["phone"],
            password=attrs["password"],
        )
        if user is None:
            # One message for both wrong-number and wrong-password, so the
            # endpoint cannot be used to test which numbers have accounts.
            raise serializers.ValidationError("That phone number and password do not match.")
        attrs["user"] = user
        return attrs


class InviteAcceptSerializer(serializers.Serializer):
    token = serializers.CharField(write_only=True)
    full_name = serializers.CharField(max_length=120)
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate_password(self, value):
        password_validation.validate_password(value)
        return value
