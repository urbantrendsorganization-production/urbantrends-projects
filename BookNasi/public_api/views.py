"""The unauthenticated booking surface.

Shop-scoped by slug, never org-scoped. There is no request user here and no
membership to check, so isolation comes from the lookup itself: a shop is found
by its public slug, and everything below it is filtered to that shop.

Slice 5 adds availability and hold creation here. Slice 10's widget and any
third-party integrator consume this and only this.
"""

from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from public_api.serializers import (
    PublicServiceSerializer,
    PublicShopSerializer,
    PublicStaffSerializer,
)
from shops.durations import ServiceNotOffered
from shops.models import Service, Shop, Staff, StaffService


class PublicViewMixin:
    permission_classes = [AllowAny]
    authentication_classes = []

    def get_shop(self):
        # `.unscoped()` is correct here and is the reason it is greppable: this
        # surface has no request user and no organization to scope by. The slug
        # *is* the scope — it resolves to exactly one shop in one tenant, and
        # everything below is then filtered to that shop.
        #
        # Only active shops are reachable. A deactivated shop's booking page is
        # gone, which is the point of deactivating it.
        return get_object_or_404(
            Shop.objects.unscoped().filter(is_active=True), slug=self.kwargs["slug"]
        )


class PublicShopDetailView(PublicViewMixin, APIView):
    def get(self, request, slug):
        return Response(PublicShopSerializer(self.get_shop()).data)


class PublicServiceListView(PublicViewMixin, generics.ListAPIView):
    serializer_class = PublicServiceSerializer
    pagination_class = None

    def get_queryset(self):
        # `publicly_bookable()` encodes CLAUDE.md §12's locked decision in SQL:
        # active, listed, and carrying an actual deposit. A deposit-free service
        # is absent from this list — not shown-and-rejected — because the client
        # should never see something they cannot book.
        return (
            Service.objects.for_org(self.get_shop().organization)
            .filter(shop=self.get_shop())
            .publicly_bookable()
            .order_by("name")
        )


class PublicStaffListView(PublicViewMixin, generics.ListAPIView):
    """Stylists who can perform a given service, with their own duration.

    The design's screen 2 shows per-stylist durations ("Wanjiku 3 hr 30, Grace
    4 hr 15") and the handoff is explicit that these must drive availability.
    They are resolved here through the same function slice 3 will use.
    """

    serializer_class = PublicStaffSerializer
    pagination_class = None

    def get_queryset(self):
        shop = self.get_shop()
        return (
            Staff.objects.for_org(shop.organization)
            .filter(shop=shop, is_active=True, is_bookable=True)
            .order_by("display_name")
        )

    def list(self, request, *args, **kwargs):
        shop = self.get_shop()
        service = get_object_or_404(
            Service.objects.for_org(shop.organization).filter(shop=shop).publicly_bookable(),
            pk=kwargs["service_id"],
        )

        links = {
            link.staff_id: link
            for link in StaffService.objects.for_org(shop.organization).filter(service=service)
        }

        rows = []
        for staff in self.get_queryset():
            try:
                minutes = _resolve(service, links.get(staff.id))
            except ServiceNotOffered:
                continue  # This stylist does not do this service; do not offer them.
            rows.append({**PublicStaffSerializer(staff).data, "duration_minutes": minutes})
        return Response(rows)


def _resolve(service, staff_service):
    from shops.durations import resolve_duration

    return resolve_duration(service=service, staff_service=staff_service)
