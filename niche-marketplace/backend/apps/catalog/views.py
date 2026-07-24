from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import IsVerified
from apps.catalog import filters, services
from apps.catalog.models import Category, Listing, ListingStatus
from apps.catalog.pagination import ListingCursorPagination
from apps.catalog.permissions import IsSellerOrReadOnly
from apps.catalog.serializers import (
    CategorySerializer,
    ListingImageSerializer,
    ListingSerializer,
    ListingWriteSerializer,
    TransitionSerializer,
)


class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Public, read-only category tree. Clients build navigation and the
    attribute form off ``effective_schema`` exposed by the serializer.
    """

    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [AllowAny]


class ListingViewSet(viewsets.ModelViewSet):
    """Listings CRUD.

    - list/retrieve: public, active listings only (owners see their own drafts).
    - create: verified users only.
    - update/delete/transition/images: the seller only.
    """

    lookup_value_regex = "[0-9]+"
    pagination_class = ListingCursorPagination

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return ListingWriteSerializer
        return ListingSerializer

    def get_permissions(self):
        if self.action == "create":
            return [IsVerified()]
        if self.action in ("update", "partial_update", "destroy", "transition",
                            "add_images", "delete_image"):
            return [IsAuthenticated(), IsSellerOrReadOnly()]
        if self.action == "mine":
            return [IsAuthenticated()]
        return [AllowAny()]

    def get_queryset(self):
        qs = Listing.objects.alive().with_related()

        # The "mine" action and object-level actions need the caller's own
        # listings regardless of status; everything else is public + active.
        if self.action in ("mine", "update", "partial_update", "destroy",
                            "transition", "add_images", "delete_image"):
            return qs

        qs = qs.active()
        seller = self.request.query_params.get("seller")
        if seller:
            qs = qs.filter(seller_id=seller)

        # The public directory feed: apply keyword search and every facet.
        if self.action == "list":
            qs = filters.apply_filters(qs, self.request.query_params)
        return qs

    def get_object(self) -> Listing:
        # For unsafe/owner actions get_queryset already returns all alive
        # listings; object permission then restricts to the seller. For public
        # retrieve, a non-owner may only see an active listing.
        if self.action == "retrieve":
            listing = get_object_or_404(
                Listing.objects.alive().with_related(), pk=self.kwargs["pk"]
            )
            user = self.request.user
            is_owner = user.is_authenticated and listing.seller_id == user.id
            if listing.status != ListingStatus.ACTIVE and not is_owner:
                self.permission_denied(self.request, message="Listing not available.")
            return listing
        return super().get_object()

    def perform_destroy(self, instance: Listing) -> None:
        services.soft_delete_listing(instance)

    @action(detail=False, methods=["get"])
    def mine(self, request: Request) -> Response:
        """The authenticated seller's own listings (any status, not deleted)."""
        page = self.paginate_queryset(self.get_queryset().filter(seller=request.user))
        serializer = ListingSerializer(page, many=True, context=self.get_serializer_context())
        return self.get_paginated_response(serializer.data)

    @action(detail=True, methods=["post"])
    def transition(self, request: Request, pk=None) -> Response:
        """Move a listing between statuses via the service state machine."""
        listing = self.get_object()
        serializer = TransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        listing = services.transition_listing(listing, serializer.validated_data["status"])
        return Response(ListingSerializer(listing, context=self.get_serializer_context()).data)

    @action(
        detail=True,
        methods=["post"],
        url_path="images",
        parser_classes=[MultiPartParser, FormParser],
    )
    def add_images(self, request: Request, pk=None) -> Response:
        """Upload one or more images (multipart, key ``images``)."""
        listing = self.get_object()
        files = request.FILES.getlist("images") or request.FILES.getlist("image")
        if not files:
            return Response(
                {"detail": "No image files provided.", "code": "no_files"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        created = [services.add_image(listing, f) for f in files]
        # Re-fetch so any thumbnail generated by the (possibly eager) task shows.
        refreshed = listing.images.filter(pk__in=[i.pk for i in created])
        data = ListingImageSerializer(
            refreshed, many=True, context=self.get_serializer_context()
        ).data
        return Response(data, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=["delete"],
        url_path=r"images/(?P<image_id>[0-9]+)",
    )
    def delete_image(self, request: Request, pk=None, image_id=None) -> Response:
        """Remove one image from a listing."""
        listing = self.get_object()
        image = get_object_or_404(listing.images, pk=image_id)
        image.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
