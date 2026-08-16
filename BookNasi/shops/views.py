from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.tenancy import OrgScopedMixin
from shops import readiness
from shops.models import (
    Leave,
    OpeningHours,
    Service,
    Shop,
    ShopClosure,
    Staff,
    StaffService,
    WorkingHours,
)
from shops.mpesa_serializers import ShopMpesaSerializer
from shops.serializers import (
    LeaveSerializer,
    OpeningHoursSerializer,
    ServiceSerializer,
    ShopClosureSerializer,
    ShopSerializer,
    StaffSerializer,
    StaffServiceSerializer,
    WorkingHoursSerializer,
)
from shops.slugs import suggest_slug, validate_shop_slug


class DeactivateInsteadOfDeleteMixin:
    """DELETE flips `is_active`. It never removes the row.

    Appointments reference Shop, Staff and Service, and CLAUDE.md §9 requires
    that history survives — a deleted stylist must not take last month's revenue
    with them. There is deliberately no code path from the API to a hard delete;
    slice 3 adds `on_delete=PROTECT` on the appointment side, which makes it
    structural rather than merely absent.
    """

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=["is_active", "updated_at"])


class ShopScopedMixin(OrgScopedMixin):
    """Resolves `self.shop` within the already-resolved organization.

    The org lookup 404s first (slice 1), so a shop id from another tenant is
    never reached, let alone read.
    """

    @property
    def shop(self):
        if not hasattr(self, "_shop"):
            self._shop = get_object_or_404(
                Shop.objects.for_org(self.organization), pk=self.kwargs["shop_id"]
            )
        return self._shop

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "shop": self.shop}


class StaffScopedMixin(OrgScopedMixin):
    @property
    def staff(self):
        if not hasattr(self, "_staff"):
            self._staff = get_object_or_404(
                Staff.objects.for_org(self.organization), pk=self.kwargs["staff_id"]
            )
        return self._staff

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "staff": self.staff}


# --------------------------------------------------------------------- shops


class ShopListCreateView(OrgScopedMixin, generics.ListCreateAPIView):
    serializer_class = ShopSerializer
    managing_roles_required = True

    def get_queryset(self):
        return Shop.objects.for_org(self.organization).order_by("name")

    def perform_create(self, serializer):
        serializer.save(organization=self.organization)


class ShopDetailView(
    DeactivateInsteadOfDeleteMixin, OrgScopedMixin, generics.RetrieveUpdateDestroyAPIView
):
    serializer_class = ShopSerializer
    managing_roles_required = True
    lookup_url_kwarg = "shop_id"

    def get_queryset(self):
        return Shop.objects.for_org(self.organization)


class SlugAvailabilityView(OrgScopedMixin, APIView):
    """The booking address is shown from step one of onboarding, so it has to be
    checkable before the shop exists."""

    managing_roles_required = True

    def get(self, request, org_id):
        raw = request.query_params.get("slug", "")
        try:
            slug = validate_shop_slug(raw)
        except Exception as exc:  # ValidationError carries the reason
            message = exc.messages[0] if hasattr(exc, "messages") else str(exc)
            return Response({"slug": raw, "available": False, "reason": message})

        taken = Shop.objects.unscoped().filter(slug=slug).exists()
        body = {"slug": slug, "available": not taken, "url": f"https://{slug}.booknasi.co.ke"}
        if taken:
            body["reason"] = "Already taken."
            body["suggestion"] = suggest_slug(
                slug, taken=set(Shop.objects.unscoped().values_list("slug", flat=True))
            )
        return Response(body)


# ------------------------------------------------------------- shop children


class OpeningHoursListCreateView(ShopScopedMixin, generics.ListCreateAPIView):
    serializer_class = OpeningHoursSerializer
    managing_roles_required = True

    def get_queryset(self):
        return OpeningHours.objects.for_org(self.organization).filter(shop=self.shop)

    def perform_create(self, serializer):
        serializer.save(shop=self.shop)


class OpeningHoursDetailView(ShopScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = OpeningHoursSerializer
    managing_roles_required = True
    lookup_url_kwarg = "pk"

    def get_queryset(self):
        return OpeningHours.objects.for_org(self.organization).filter(shop=self.shop)


class ClosureListCreateView(ShopScopedMixin, generics.ListCreateAPIView):
    serializer_class = ShopClosureSerializer
    managing_roles_required = True

    def get_queryset(self):
        return ShopClosure.objects.for_org(self.organization).filter(shop=self.shop)

    def perform_create(self, serializer):
        serializer.save(shop=self.shop)


class ClosureDetailView(ShopScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ShopClosureSerializer
    managing_roles_required = True
    lookup_url_kwarg = "pk"

    def get_queryset(self):
        return ShopClosure.objects.for_org(self.organization).filter(shop=self.shop)


class StaffListCreateView(ShopScopedMixin, generics.ListCreateAPIView):
    serializer_class = StaffSerializer
    managing_roles_required = True

    def get_queryset(self):
        return (
            Staff.objects.for_org(self.organization)
            .filter(shop=self.shop)
            .select_related("membership")
        )

    def perform_create(self, serializer):
        serializer.save(shop=self.shop)


class StaffDetailView(
    DeactivateInsteadOfDeleteMixin, ShopScopedMixin, generics.RetrieveUpdateDestroyAPIView
):
    serializer_class = StaffSerializer
    managing_roles_required = True
    lookup_url_kwarg = "staff_id"

    def get_queryset(self):
        return (
            Staff.objects.for_org(self.organization)
            .filter(shop=self.shop)
            .select_related("membership")
        )


class ServiceListCreateView(ShopScopedMixin, generics.ListCreateAPIView):
    serializer_class = ServiceSerializer
    managing_roles_required = True

    def get_queryset(self):
        return Service.objects.for_org(self.organization).filter(shop=self.shop)

    def perform_create(self, serializer):
        serializer.save(shop=self.shop)


class ServiceDetailView(
    DeactivateInsteadOfDeleteMixin, ShopScopedMixin, generics.RetrieveUpdateDestroyAPIView
):
    serializer_class = ServiceSerializer
    managing_roles_required = True
    lookup_url_kwarg = "service_id"

    def get_queryset(self):
        return Service.objects.for_org(self.organization).filter(shop=self.shop)


# ------------------------------------------------------------ staff children


class WorkingHoursListCreateView(StaffScopedMixin, generics.ListCreateAPIView):
    serializer_class = WorkingHoursSerializer
    managing_roles_required = True

    def get_queryset(self):
        return WorkingHours.objects.for_org(self.organization).filter(staff=self.staff)

    def perform_create(self, serializer):
        serializer.save(staff=self.staff)


class WorkingHoursDetailView(StaffScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = WorkingHoursSerializer
    managing_roles_required = True
    lookup_url_kwarg = "pk"

    def get_queryset(self):
        return WorkingHours.objects.for_org(self.organization).filter(staff=self.staff)


class LeaveListCreateView(StaffScopedMixin, generics.ListCreateAPIView):
    serializer_class = LeaveSerializer
    managing_roles_required = True

    def get_queryset(self):
        return Leave.objects.for_org(self.organization).filter(staff=self.staff)

    def perform_create(self, serializer):
        serializer.save(staff=self.staff)


class LeaveDetailView(StaffScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = LeaveSerializer
    managing_roles_required = True
    lookup_url_kwarg = "pk"

    def get_queryset(self):
        return Leave.objects.for_org(self.organization).filter(staff=self.staff)


class StaffServiceListCreateView(StaffScopedMixin, generics.ListCreateAPIView):
    serializer_class = StaffServiceSerializer
    managing_roles_required = True

    def get_queryset(self):
        return (
            StaffService.objects.for_org(self.organization)
            .filter(staff=self.staff)
            .select_related("service")
        )

    def perform_create(self, serializer):
        serializer.save(staff=self.staff)


class StaffServiceDetailView(StaffScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = StaffServiceSerializer
    managing_roles_required = True
    lookup_url_kwarg = "pk"

    def get_queryset(self):
        return (
            StaffService.objects.for_org(self.organization)
            .filter(staff=self.staff)
            .select_related("service")
        )

    def perform_destroy(self, instance):
        # The link row itself is config, not history — appointments reference
        # staff and service directly, never this join. Removing it is safe.
        super().perform_destroy(instance)


class ShopOpenOnView(ShopScopedMixin, APIView):
    """Config-level: is the shop open at all on this date?

    Not availability. It answers only "weekly hours minus dated closures", which
    is one of slice 3's inputs, and it exists here so the settings screen can
    show the effect of a closure without waiting for the engine.
    """

    def get(self, request, org_id, shop_id):
        from datetime import date

        raw = request.query_params.get("date")
        try:
            day = date.fromisoformat(raw) if raw else date.today()
        except ValueError:
            return Response(
                {"detail": "date must be YYYY-MM-DD"}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response({"date": day.isoformat(), "is_open": self.shop.is_open_on(day)})


class ShopReadinessView(ShopScopedMixin, APIView):
    """What is still missing before this shop can be booked online.

    Managing roles only, matching every other write endpoint on this shop: the
    answer is a description of the shop's configuration, and a stylist has no
    reason to read one and no screen that asks for it.

    The rule itself lives in `shops/readiness.py` — see that module for why it
    is derived here rather than in the settings screen.
    """

    managing_roles_required = True

    def get(self, request, org_id, shop_id):
        return Response(readiness.report_for(self.shop))


class ShopMpesaView(ShopScopedMixin, APIView):
    """Whose M-Pesa account this shop's deposits land in.

    **Owner only**, unlike every other endpoint in this file. See
    `core/tenancy.OrgScopedMixin.owner_role_required`: a manager already sets
    prices and deposit rules and so decides how much is taken, but repointing
    where it goes is a different act and a quiet one — the number is masked on
    the way back out, so nobody else on the account could see it had changed.

    GET returns the connection with the secrets masked. PATCH writes it.
    """

    owner_role_required = True

    def get(self, request, org_id, shop_id):
        return Response(ShopMpesaSerializer(self.shop).data)

    def patch(self, request, org_id, shop_id):
        serializer = ShopMpesaSerializer(self.shop, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ShopMpesaDisconnectView(ShopScopedMixin, APIView):
    """Stop collecting into this shop's own account.

    A named action rather than a PATCH of four empty strings, because a stale
    form or a half-loaded screen can send the second by accident and the result
    — a shop that silently stops taking deposits — is indistinguishable from
    the shop working until a client tries to pay.

    Clears the credentials rather than only flipping `collects_via`. A shop that
    disconnects has usually rotated or lost the keys; keeping ciphertext nobody
    can vouch for around is a row that will be reconnected by accident later.
    """

    owner_role_required = True

    def post(self, request, org_id, shop_id):
        shop = self.shop
        shop.mpesa_shortcode = ""
        shop.mpesa_till_number = ""
        shop.mpesa_transaction_type = ""
        shop.seal_mpesa_credentials(consumer_key="", consumer_secret="", passkey="")
        shop.save(
            update_fields=[
                "mpesa_shortcode",
                "mpesa_till_number",
                "mpesa_transaction_type",
                "mpesa_consumer_key_enc",
                "mpesa_consumer_secret_enc",
                "mpesa_passkey_enc",
                "mpesa_key_id",
                "updated_at",
            ]
        )
        return Response(ShopMpesaSerializer(shop).data)
