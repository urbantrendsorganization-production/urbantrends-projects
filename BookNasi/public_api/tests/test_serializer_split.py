"""LOAD-BEARING. The public/private serializer split.

CLAUDE.md §1: "Build every API as if a third party will integrate it, because
one will." The failure this guards against is not a bug anyone writes on
purpose — it is a field added to `ShopSerializer` in slice 6 that quietly
appears on an unauthenticated endpoint because the two shared a base class.

So the assertions here are on the **exact field set**, not on a sample of
forbidden names. A new field on either side fails this test until someone
decides, in writing, which surface it belongs to.
"""

import pytest

from public_api.serializers import (
    PublicServiceSerializer,
    PublicShopSerializer,
    PublicStaffSerializer,
)
from shops.serializers import ServiceSerializer, ShopSerializer, StaffSerializer

pytestmark = pytest.mark.loadbearing


EXPECTED_PUBLIC_SHOP_FIELDS = {
    "slug",
    "name",
    "address",
    "area",
    "directions_url",
    "phone",
    "logo_url",
    "accent_color",
    # Drives the visible hold countdown, which CLAUDE.md §10 forbids hiding.
    "hold_ttl_minutes",
    # The refund rule is read before payment, never after.
    "refund_window_hours",
    "opening_hours",
}

EXPECTED_PUBLIC_SERVICE_FIELDS = {
    "id",
    "name",
    "description",
    "duration_minutes",
    "price",
    "deposit_mode",
    "deposit_amount",
    "balance_due",
}

EXPECTED_PUBLIC_STAFF_FIELDS = {"id", "display_name"}


class TestExactFieldSets:
    def test_public_shop(self):
        assert set(PublicShopSerializer().fields) == EXPECTED_PUBLIC_SHOP_FIELDS

    def test_public_service(self):
        assert set(PublicServiceSerializer().fields) == EXPECTED_PUBLIC_SERVICE_FIELDS

    def test_public_staff(self):
        assert set(PublicStaffSerializer().fields) == EXPECTED_PUBLIC_STAFF_FIELDS


class TestNothingTenantScopedEscapes:
    @pytest.mark.parametrize(
        "serializer",
        [PublicShopSerializer, PublicServiceSerializer, PublicStaffSerializer],
    )
    def test_no_organization_field(self, serializer):
        assert not {f for f in serializer().fields if "organization" in f or f == "org"}

    def test_internal_scheduling_policy_stays_internal(self):
        """`buffer_minutes` is how the shop runs its own floor. The client needs
        the hold TTL and the refund window; it has no business with the rest."""
        assert "buffer_minutes" not in PublicShopSerializer().fields
        assert "buffer_minutes" in ShopSerializer().fields

    def test_activity_flags_stay_internal(self):
        """A hidden row is absent from the public list, not present-and-flagged.
        Exposing the flag tells a client something exists that they cannot see."""
        for field in ("is_active", "is_publicly_listed"):
            assert field not in PublicServiceSerializer().fields
        assert "is_active" not in PublicShopSerializer().fields

    def test_staff_account_linkage_stays_internal(self):
        assert "membership" not in PublicStaffSerializer().fields
        assert "membership" in StaffSerializer().fields

    def test_no_internal_ids_leak_through_service(self):
        assert "shop" not in PublicServiceSerializer().fields


class TestTheTwoSurfacesShareNoCode:
    """Inheritance is the trap. A `PublicShopSerializer(ShopSerializer)` with a
    shorter `fields` list still inherits whatever the parent adds later."""

    @pytest.mark.parametrize(
        "public,private",
        [
            (PublicShopSerializer, ShopSerializer),
            (PublicServiceSerializer, ServiceSerializer),
            (PublicStaffSerializer, StaffSerializer),
        ],
    )
    def test_no_inheritance_between_them(self, public, private):
        assert not issubclass(public, private)
        assert not issubclass(private, public)

    @pytest.mark.parametrize(
        "public", [PublicShopSerializer, PublicServiceSerializer, PublicStaffSerializer]
    )
    def test_public_serializers_are_not_model_serializers(self, public):
        """A ModelSerializer picks up new columns by default. Declaring every
        field by hand means a new column reaches the public API only when
        somebody writes a line in that module."""
        from rest_framework import serializers

        assert not issubclass(public, serializers.ModelSerializer)

    def test_the_private_field_sets_are_strictly_larger(self):
        """Sanity: if these ever converge, the split has stopped meaning
        anything."""
        assert set(ServiceSerializer().fields) > set(PublicServiceSerializer().fields) - {
            "balance_due"
        }
