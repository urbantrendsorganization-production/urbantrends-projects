"""Deactivation, never deletion.

Appointments (slice 3) reference Shop, Staff and Service. CLAUDE.md §9 requires
that history survives, and the owner dashboard (slice 9) reports revenue per
staff over past months. A hard delete would take a former stylist's work out of
last month's numbers.

**What happens to a future appointment when its service is deactivated:**
nothing. Deactivation is a configuration change, not a cancellation. Existing
appointments — including future ones — keep their reference, keep their price,
keep their deposit and still appear on the staff day view and in reports. What
deactivation stops is *new* use: the service leaves the public list, leaves the
walk-in picker, and slice 3 will refuse to open a new appointment against it.

The alternative — cascading a cancellation — would silently cancel bookings that
already have money against them. That is a refund event with an SMS attached
(slice 7), not something a settings toggle may do on its own.
"""

import pytest
from django.urls import reverse

from shops.models import Service, Shop, Staff

pytestmark = pytest.mark.django_db


class TestTheApiCannotHardDelete:
    def test_deleting_a_service_deactivates_it(self, api_client, shop_setup):
        api_client.force_login(shop_setup.org.owner)

        response = api_client.delete(
            reverse(
                "shops:service-detail",
                args=[shop_setup.organization.id, shop_setup.shop.id, shop_setup.braids.id],
            )
        )

        assert response.status_code == 204
        shop_setup.braids.refresh_from_db()
        assert shop_setup.braids.is_active is False
        assert (
            Service.objects.for_org(shop_setup.organization)
            .filter(pk=shop_setup.braids.pk)
            .exists()
        )

    def test_deleting_a_staff_member_deactivates_them(self, api_client, shop_setup):
        api_client.force_login(shop_setup.org.owner)

        response = api_client.delete(
            reverse(
                "shops:staff-detail",
                args=[shop_setup.organization.id, shop_setup.shop.id, shop_setup.grace.id],
            )
        )

        assert response.status_code == 204
        shop_setup.grace.refresh_from_db()
        assert shop_setup.grace.is_active is False
        assert (
            Staff.objects.for_org(shop_setup.organization).filter(pk=shop_setup.grace.pk).exists()
        )

    def test_deleting_a_shop_deactivates_it(self, api_client, shop_setup):
        api_client.force_login(shop_setup.org.owner)

        response = api_client.delete(
            reverse("shops:shop-detail", args=[shop_setup.organization.id, shop_setup.shop.id])
        )

        assert response.status_code == 204
        shop_setup.shop.refresh_from_db()
        assert shop_setup.shop.is_active is False
        assert Shop.objects.for_org(shop_setup.organization).filter(pk=shop_setup.shop.pk).exists()


class TestDeactivationBlocksNewUse:
    def test_a_deactivated_service_leaves_the_public_list(self, api_client, shop_setup):
        listing = reverse("public_api:service-list", args=[shop_setup.shop.slug])
        assert len(api_client.get(listing).json()) == 1

        shop_setup.braids.is_active = False
        shop_setup.braids.save()

        assert api_client.get(listing).json() == []

    def test_a_deactivated_shop_has_no_public_booking_page(self, api_client, shop_setup):
        page = reverse("public_api:shop-detail", args=[shop_setup.shop.slug])
        assert api_client.get(page).status_code == 200

        shop_setup.shop.is_active = False
        shop_setup.shop.save()

        assert api_client.get(page).status_code == 404

    def test_a_deactivated_staff_member_leaves_the_public_picker(self, api_client, shop_setup):
        picker = reverse("public_api:staff-list", args=[shop_setup.shop.slug, shop_setup.braids.id])
        assert len(api_client.get(picker).json()) == 2

        shop_setup.grace.is_active = False
        shop_setup.grace.save()

        names = [row["display_name"] for row in api_client.get(picker).json()]
        assert names == ["Wanjiku"]

    def test_a_non_bookable_staff_member_leaves_the_picker_but_keeps_working(
        self, api_client, shop_setup
    ):
        """A manager who covers the desk is active staff without being
        bookable. Two flags, because they are two different facts."""
        shop_setup.grace.is_bookable = False
        shop_setup.grace.save()

        picker = reverse("public_api:staff-list", args=[shop_setup.shop.slug, shop_setup.braids.id])
        assert [row["display_name"] for row in api_client.get(picker).json()] == ["Wanjiku"]
        shop_setup.grace.refresh_from_db()
        assert shop_setup.grace.is_active is True


class TestDeactivationPreservesReferences:
    def test_a_deactivated_service_keeps_its_price_and_deposit(self, shop_setup):
        """Slice 9 reports revenue over past months; the figures have to survive
        the service being retired."""
        shop_setup.braids.is_active = False
        shop_setup.braids.save()
        shop_setup.braids.refresh_from_db()

        assert shop_setup.braids.price == 3500
        assert shop_setup.braids.deposit_amount == 875

    def test_a_deactivated_staff_member_keeps_their_service_links(self, shop_setup):
        from shops.models import StaffService

        shop_setup.grace.is_active = False
        shop_setup.grace.save()

        assert (
            StaffService.objects.for_org(shop_setup.organization)
            .filter(staff=shop_setup.grace)
            .count()
            == 2
        )

    def test_a_deactivated_staff_member_is_still_listed_to_the_owner(self, api_client, shop_setup):
        """Gone from the client's picker, still on the owner's staff list —
        otherwise last month's revenue has a row with no name against it."""
        shop_setup.grace.is_active = False
        shop_setup.grace.save()
        api_client.force_login(shop_setup.org.owner)

        rows = api_client.get(
            reverse("shops:staff-list", args=[shop_setup.organization.id, shop_setup.shop.id])
        ).json()

        assert {row["display_name"] for row in rows} == {"Wanjiku", "Grace"}
