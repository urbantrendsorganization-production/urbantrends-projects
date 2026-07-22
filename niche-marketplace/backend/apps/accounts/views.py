from django.contrib.auth import get_user_model
from rest_framework import generics, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import services
from apps.accounts.serializers import (
    MeSerializer,
    PublicUserSerializer,
    RegisterSerializer,
    ResendVerificationSerializer,
    VerifyEmailSerializer,
)

User = get_user_model()


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            {
                "detail": "Registered. Check your email to verify your account.",
                "user": {"id": user.id, "email": user.email},
            },
            status=status.HTTP_201_CREATED,
        )


class VerifyEmailView(APIView):
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        serializer = VerifyEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            services.verify_email(serializer.validated_data["token"])
        except services.VerificationError as exc:
            # Same {detail, code} envelope the global handler produces.
            return Response(
                {"detail": exc.message, "code": exc.code},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"detail": "Email verified. You can now sign in."})


class ResendVerificationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        serializer = ResendVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.resend_verification(serializer.validated_data["email"])
        # Generic response regardless of outcome — don't leak account existence.
        return Response(
            {"detail": "If that account exists and is unverified, a new link is on its way."}
        )


class MeView(generics.RetrieveUpdateAPIView):
    """Read or edit the authenticated user's own profile."""

    serializer_class = MeSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_object(self) -> User:
        return self.request.user


class PublicUserView(generics.RetrieveAPIView):
    """Anyone can view a user's public profile."""

    serializer_class = PublicUserSerializer
    permission_classes = [AllowAny]
    queryset = User.objects.filter(is_active=True)
