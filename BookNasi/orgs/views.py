from django.contrib.auth import login
from django.db import transaction
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.serializers import UserSerializer
from core.tenancy import MANAGING_ROLES, OrgScopedMixin, organizations_for
from orgs.models import Membership, Organization, Role, StaffInvite
from orgs.serializers import (
    MembershipSerializer,
    OrganizationSerializer,
    SignupSerializer,
    StaffInviteSerializer,
    unique_org_slug,
)


class SignupView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        with transaction.atomic():
            user = User.objects.create_user(
                phone=data["phone"],
                password=data["password"],
                full_name=data["full_name"],
                email=data.get("email") or None,
            )
            organization = Organization.objects.create(
                name=data["organization_name"],
                slug=unique_org_slug(data["organization_name"]),
                owner=user,
            )
            membership = Membership.objects.create(
                organization=organization,
                user=user,
                role=Role.OWNER,
                accepted_at=timezone.now(),
            )

        login(request, user)
        return Response(
            {
                "user": UserSerializer(user).data,
                "organization": OrganizationSerializer(organization).data,
                "membership": MembershipSerializer(membership).data,
            },
            status=status.HTTP_201_CREATED,
        )


class OrganizationListView(generics.ListAPIView):
    serializer_class = OrganizationSerializer

    def get_queryset(self):
        return organizations_for(self.request.user).order_by("name")


class OrganizationDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = OrganizationSerializer
    lookup_url_kwarg = "org_id"

    def get_queryset(self):
        return organizations_for(self.request.user)

    def perform_update(self, serializer):
        membership = Membership.objects.for_org(serializer.instance).get(user=self.request.user)
        if membership.role not in MANAGING_ROLES:
            raise ValidationError("Only an owner or manager can change organization settings.")
        serializer.save()


class MembershipListView(OrgScopedMixin, generics.ListAPIView):
    serializer_class = MembershipSerializer

    def get_queryset(self):
        return (
            Membership.objects.for_org(self.organization)
            .select_related("user", "organization")
            .order_by("user__full_name")
        )


class MembershipDetailView(OrgScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = MembershipSerializer
    managing_roles_required = True
    lookup_url_kwarg = "membership_id"

    def get_queryset(self):
        return Membership.objects.for_org(self.organization).select_related("user", "organization")

    def perform_destroy(self, instance):
        if instance.role == Role.OWNER:
            raise ValidationError("The owner's membership cannot be removed.")
        # Deactivate rather than delete: slice 2 hangs Staff off Membership and
        # slice 9 reports revenue per staff. A hard delete would take a former
        # stylist's appointments out of last month's numbers.
        instance.is_active = False
        instance.save(update_fields=["is_active", "updated_at"])


class StaffInviteListView(OrgScopedMixin, generics.ListCreateAPIView):
    serializer_class = StaffInviteSerializer
    managing_roles_required = True

    def get_queryset(self):
        return StaffInvite.objects.for_org(self.organization).order_by("-created_at")

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone = serializer.validated_data["phone"]

        if (
            Membership.objects.for_org(self.organization)
            .filter(user__phone=phone, is_active=True)
            .exists()
        ):
            raise ValidationError({"phone": "That person is already on this organization."})
        if StaffInvite.objects.for_org(self.organization).pending().filter(phone=phone).exists():
            raise ValidationError({"phone": "There is already an open invite for that number."})

        invite, token = StaffInvite.issue(
            organization=self.organization,
            phone=phone,
            role=serializer.validated_data.get("role", Role.STAFF),
            created_by=request.user,
        )
        return Response(self._with_token(invite, token), status=status.HTTP_201_CREATED)

    def _with_token(self, invite, token):
        payload = StaffInviteSerializer(invite).data
        # Returned once, to be handed to the SMS provider in slice 8. Until then
        # it is the only way to complete an invite in dev. It is never stored
        # and never returned again.
        payload["token"] = token
        return payload


class StaffInviteResendView(OrgScopedMixin, APIView):
    managing_roles_required = True

    def post(self, request, org_id, invite_id):
        invite = generics.get_object_or_404(
            StaffInvite.objects.for_org(self.organization), pk=invite_id
        )
        if invite.accepted_at or invite.revoked_at:
            raise ValidationError("That invite has already been used or revoked.")
        token = invite.rotate_token()
        payload = StaffInviteSerializer(invite).data
        payload["token"] = token
        return Response(payload)
