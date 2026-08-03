"""The unauthenticated booking surface, end to end."""

import pytest
from django.urls import reverse

from shops.models import StaffService

pytestmark = pytest.mark.django_db


class TestShopDetail:
    def test_it_needs_no_login(self, api_client, shop_setup):
        response = api_client.get(reverse("public_api:shop-detail", args=[shop_setup.shop.slug]))

        assert response.status_code == 200
        assert response.json()["name"] == "Mint Braids Kilimani"

    def test_it_carries_what_the_client_needs_to_finish_a_booking(self, api_client, shop_setup):
        body = api_client.get(reverse("public_api:shop-detail", args=[shop_setup.shop.slug])).json()

        assert body["hold_ttl_minutes"] == 3
        assert body["refund_window_hours"] == 24
        assert len(body["opening_hours"]) == 6

    def test_an_unknown_slug_is_404(self, api_client):
        assert (
            api_client.get(reverse("public_api:shop-detail", args=["no-such-shop"])).status_code
            == 404
        )

    def test_it_leaks_nothing_tenant_scoped(self, api_client, shop_setup):
        body = api_client.get(reverse("public_api:shop-detail", args=[shop_setup.shop.slug])).json()

        assert "organization" not in body
        assert "buffer_minutes" not in body
        assert str(shop_setup.organization.id) not in str(body)


class TestServiceList:
    def test_only_publicly_bookable_services_appear(self, api_client, shop_setup):
        """The deposit-free beard trim is absent, not shown-and-rejected. A
        client should never see something they cannot book. CLAUDE.md §12."""
        rows = api_client.get(
            reverse("public_api:service-list", args=[shop_setup.shop.slug])
        ).json()

        assert [row["name"] for row in rows] == ["Knotless braids, medium, waist length"]

    def test_the_deposit_is_priced_before_anything_else_is_asked(self, api_client, shop_setup):
        """The design's screen 1 puts the deposit on every card up front."""
        row = api_client.get(
            reverse("public_api:service-list", args=[shop_setup.shop.slug])
        ).json()[0]

        assert row["price"] == 3500
        assert row["deposit_amount"] == 875
        assert row["balance_due"] == 2625

    def test_the_balance_always_adds_up(self, api_client, shop_setup):
        """deposit + balance == price, at every rounding edge. If these ever
        disagree the client is shown a total that is not the total."""
        from decimal import Decimal

        from shops.models import DepositMode, Service

        for price in (1333, 1334, 999, 1, 100000):
            Service.objects.create(
                shop=shop_setup.shop,
                name=f"Service {price}",
                duration_minutes=30,
                price=price,
                deposit_mode=DepositMode.PERCENT,
                deposit_value=Decimal("25"),
            )

        rows = api_client.get(
            reverse("public_api:service-list", args=[shop_setup.shop.slug])
        ).json()

        for row in rows:
            assert row["deposit_amount"] + row["balance_due"] == row["price"]

    def test_a_long_service_name_is_returned_whole(self, api_client, shop_setup):
        """ "Knotless braids, medium, waist length" is an ordinary name. Nothing
        truncates it server-side; the design wraps it to two lines instead."""
        row = api_client.get(
            reverse("public_api:service-list", args=[shop_setup.shop.slug])
        ).json()[0]

        assert row["name"] == "Knotless braids, medium, waist length"

    def test_another_shops_services_never_appear(self, api_client, shop_setup, rival_shop):
        rows = api_client.get(
            reverse("public_api:service-list", args=[shop_setup.shop.slug])
        ).json()

        assert all(row["id"] != str(rival_shop.braids.id) for row in rows)


class TestStaffPicker:
    def test_it_lists_stylists_with_their_own_durations(self, api_client, shop_setup):
        """The design's screen 2: Wanjiku 3 hr 30, Grace 4 hr 15. Resolved
        through the same function slice 3 uses."""
        link = StaffService.objects.for_org(shop_setup.organization).get(
            staff=shop_setup.wanjiku, service=shop_setup.braids
        )
        link.duration_override_minutes = 210
        link.save()

        rows = api_client.get(
            reverse("public_api:staff-list", args=[shop_setup.shop.slug, shop_setup.braids.id])
        ).json()

        by_name = {row["display_name"]: row for row in rows}
        assert by_name["Wanjiku"]["duration_minutes"] == 210
        assert by_name["Grace"]["duration_minutes"] == 240

    def test_a_stylist_who_does_not_offer_it_is_omitted(self, api_client, shop_setup):
        StaffService.objects.for_org(shop_setup.organization).filter(
            staff=shop_setup.grace, service=shop_setup.braids
        ).delete()

        rows = api_client.get(
            reverse("public_api:staff-list", args=[shop_setup.shop.slug, shop_setup.braids.id])
        ).json()

        assert [row["display_name"] for row in rows] == ["Wanjiku"]

    def test_a_deposit_free_service_has_no_public_picker(self, api_client, shop_setup):
        """It is not publicly bookable, so there is nothing to pick a stylist
        for."""
        response = api_client.get(
            reverse("public_api:staff-list", args=[shop_setup.shop.slug, shop_setup.shave.id])
        )

        assert response.status_code == 404

    def test_no_account_details_reach_the_client(self, api_client, shop_setup):
        rows = api_client.get(
            reverse("public_api:staff-list", args=[shop_setup.shop.slug, shop_setup.braids.id])
        ).json()

        for row in rows:
            assert set(row) == {"id", "display_name", "duration_minutes"}


class TestNoAuthenticationAnywhere:
    @pytest.mark.parametrize(
        "route,args",
        [
            ("public_api:shop-detail", ["slug"]),
            ("public_api:service-list", ["slug"]),
        ],
    )
    def test_endpoints_are_reachable_signed_out(self, api_client, shop_setup, route, args):
        resolved = [shop_setup.shop.slug if a == "slug" else a for a in args]

        assert api_client.get(reverse(route, args=resolved)).status_code == 200

    def test_being_signed_in_changes_nothing(self, api_client, shop_setup):
        """No `if request.user` branch anywhere on this surface — that branch is
        how tenant data leaks."""
        signed_out = api_client.get(
            reverse("public_api:service-list", args=[shop_setup.shop.slug])
        ).json()

        api_client.force_login(shop_setup.org.owner)
        signed_in = api_client.get(
            reverse("public_api:service-list", args=[shop_setup.shop.slug])
        ).json()

        assert signed_out == signed_in
