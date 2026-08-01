from django.contrib.auth import login, logout
from django.db import transaction
from django.middleware.csrf import get_token
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.serializers import InviteAcceptSerializer, LoginSerializer, UserSerializer
from orgs.models import Membership, StaffInvite
from orgs.serializers import MembershipSerializer


class CsrfView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"csrf_token": get_token(request)})


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        login(request, serializer.validated_data["user"])
        return Response(UserSerializer(request.user).data)


class LogoutView(APIView):
    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    def get(self, request):
        memberships = (
            Membership.objects.unscoped()
            .filter(user=request.user, is_active=True)
            .select_related("organization")
        )
        return Response(
            {
                "user": UserSerializer(request.user).data,
                "memberships": MembershipSerializer(memberships, many=True).data,
            }
        )


class InviteAcceptView(APIView):
    """Turns an SMS token into an account and an active membership.

    Deliberately unauthenticated: the invitee has no account yet, which is the
    whole point of StaffInvite existing separately from Membership.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = InviteAcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        invite = StaffInvite.find_by_token(data["token"])
        if invite is None or not invite.is_pending:
            # One message for missing, expired, revoked and already-accepted.
            # Distinguishing them tells a token-guesser which guesses were warm.
            return Response(
                {"detail": "That invite link is no longer valid. Ask the shop to resend it."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            user = User.objects.filter(phone=invite.phone).first()
            if user is None:
                user = User.objects.create_user(
                    phone=invite.phone,
                    password=data["password"],
                    full_name=data["full_name"],
                )
            # An existing user keeps their password — a staff member who already
            # works at another shop in the same org is one person, not two, and
            # an invite must not become a password-reset primitive.

            membership, _ = Membership.objects.unscoped().update_or_create(
                organization=invite.organization,
                user=user,
                defaults={
                    "role": invite.role,
                    "is_active": True,
                    "accepted_at": timezone.now(),
                    "invited_by": invite.created_by,
                },
            )
            invite.accepted_at = timezone.now()
            invite.save(update_fields=["accepted_at", "updated_at"])

        login(request, user)
        return Response(
            {
                "user": UserSerializer(user).data,
                "membership": MembershipSerializer(membership).data,
            },
            status=status.HTTP_201_CREATED,
        )
