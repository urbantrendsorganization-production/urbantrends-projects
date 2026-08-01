"""Tenant isolation for every model slice 2 adds.

The slice 1 guard makes most of this mechanical — `OrgScopedModel` refuses an
unfiltered queryset, and `core/tests/test_org_scoped_manager_guard.py` proves
that for every registered model. What is *not* mechanical is the endpoint layer:
each new URL has to 404 rather than 403 for a foreign org, and each nested
lookup has to check the parent before the child.
"""

import pytest
from django.urls import reverse

from shops.models import Leave, OpeningHours, Service, ShopClosure, Staff, StaffService

pytestmark = [pytest.mark.django_db, pytest.mark.loadbearing]


SHOP_SCOPED_ENDPOINTS = [
    "shops:opening-hours-list",
    "shops:closure-list",
    "shops:staff-list",
    "shops:service-list",
]
STAFF_SCOPED_ENDPOINTS = [
    "shops:working-hours-list",
    "shops:leave-list",
    "shops:staff-service-list",
]


class TestForeignOrgGets404:
    def test_shop_list_of_another_org(self, api_client, shop_setup, rival_shop):
        api_client.force_login(shop_setup.org.owner)

        response = api_client.get(reverse("shops:shop-list", args=[rival_shop.organization.id]))

        assert response.status_code == 404

    def test_shop_detail_of_another_org(self, api_client, shop_setup, rival_shop):
        api_client.force_login(shop_setup.org.owner)

        response = api_client.get(
            reverse("shops:shop-detail", args=[rival_shop.organization.id, rival_shop.shop.id])
        )

        assert response.status_code == 404

    @pytest.mark.parametrize("route", SHOP_SCOPED_ENDPOINTS)
    def test_shop_children_of_another_org(self, api_client, shop_setup, rival_shop, route):
        api_client.force_login(shop_setup.org.owner)

        response = api_client.get(
            reverse(route, args=[rival_shop.organization.id, rival_shop.shop.id])
        )

        assert response.status_code == 404

    @pytest.mark.parametrize("route", STAFF_SCOPED_ENDPOINTS)
    def test_staff_children_of_another_org(self, api_client, shop_setup, rival_shop, route):
        api_client.force_login(shop_setup.org.owner)

        response = api_client.get(
            reverse(route, args=[rival_shop.organization.id, rival_shop.wanjiku.id])
        )

        assert response.status_code == 404


class TestRealIdsInTheWrongPairing:
    """Both ids exist; the pairing does not. Guards against resolving the child
    before checking the parent — the classic nested-resource hole."""

    @pytest.mark.parametrize("route", SHOP_SCOPED_ENDPOINTS)
    def test_my_org_with_another_orgs_shop(self, api_client, shop_setup, rival_shop, route):
        api_client.force_login(shop_setup.org.owner)

        response = api_client.get(
            reverse(route, args=[shop_setup.organization.id, rival_shop.shop.id])
        )

        assert response.status_code == 404

    @pytest.mark.parametrize("route", STAFF_SCOPED_ENDPOINTS)
    def test_my_org_with_another_orgs_staff(self, api_client, shop_setup, rival_shop, route):
        api_client.force_login(shop_setup.org.owner)

        response = api_client.get(
            reverse(route, args=[shop_setup.organization.id, rival_shop.wanjiku.id])
        )

        assert response.status_code == 404

    def test_my_shop_with_another_orgs_service(self, api_client, shop_setup, rival_shop):
        api_client.force_login(shop_setup.org.owner)

        response = api_client.get(
            reverse(
                "shops:service-detail",
                args=[shop_setup.organization.id, shop_setup.shop.id, rival_shop.braids.id],
            )
        )

        assert response.status_code == 404


class TestListContentsNeverLeak:
    def test_shop_list_contains_only_my_shops(self, api_client, shop_setup, rival_shop):
        api_client.force_login(shop_setup.org.owner)

        rows = api_client.get(reverse("shops:shop-list", args=[shop_setup.organization.id])).json()

        assert [row["slug"] for row in rows] == [shop_setup.shop.slug]

    def test_service_list_contains_only_my_services(self, api_client, shop_setup, rival_shop):
        api_client.force_login(shop_setup.org.owner)

        rows = api_client.get(
            reverse("shops:service-list", args=[shop_setup.organization.id, shop_setup.shop.id])
        ).json()

        assert len(rows) == 2
        assert all(row["shop"] == str(shop_setup.shop.id) for row in rows)


class TestCrossTenantWrites:
    def test_a_staff_member_cannot_be_linked_to_another_orgs_membership(
        self, api_client, shop_setup, rival_shop
    ):
        api_client.force_login(shop_setup.org.owner)

        response = api_client.post(
            reverse("shops:staff-list", args=[shop_setup.organization.id, shop_setup.shop.id]),
            {"display_name": "Mole", "membership": str(rival_shop.org.owner_membership.id)},
            format="json",
        )

        assert response.status_code == 400

    def test_a_staff_service_link_cannot_cross_shops(self, api_client, shop_setup, rival_shop):
        api_client.force_login(shop_setup.org.owner)

        response = api_client.post(
            reverse(
                "shops:staff-service-list",
                args=[shop_setup.organization.id, shop_setup.wanjiku.id],
            ),
            {"service": str(rival_shop.braids.id)},
            format="json",
        )

        assert response.status_code == 400


class TestDerivedOrganizationColumn:
    """Children carry their own `organization`, derived from the parent and
    never settable. Without the column the slice 1 guard would not apply to
    them at all."""

    @pytest.mark.parametrize(
        "model,attr",
        [
            (OpeningHours, "opening_hours"),
            (ShopClosure, "closures"),
            (Staff, "staff"),
            (Service, "services"),
        ],
    )
    def test_shop_children_inherit_the_shops_org(self, shop_setup, model, attr):
        for row in getattr(shop_setup.shop, attr).all():
            assert row.organization_id == shop_setup.shop.organization_id

    def test_staff_children_inherit_the_staffs_org(self, shop_setup):
        Leave.objects.create(staff=shop_setup.wanjiku, starts_on="2026-08-03", ends_on="2026-08-04")
        for row in StaffService.objects.unscoped().filter(staff=shop_setup.wanjiku):
            assert row.organization_id == shop_setup.organization.id
        for row in Leave.objects.unscoped().filter(staff=shop_setup.wanjiku):
            assert row.organization_id == shop_setup.organization.id

    def test_a_forged_organization_is_overwritten_by_the_parents(self, shop_setup, rival_shop):
        """Even if something hands the model another tenant's org id directly,
        the derived column wins on save."""
        service = Service(
            shop=shop_setup.shop,
            organization=rival_shop.organization,
            name="Forged",
            duration_minutes=30,
            price=1000,
        )
        service.save()

        assert service.organization_id == shop_setup.organization.id

    def test_the_api_cannot_set_it_either(self, api_client, shop_setup, rival_shop):
        api_client.force_login(shop_setup.org.owner)

        response = api_client.post(
            reverse("shops:service-list", args=[shop_setup.organization.id, shop_setup.shop.id]),
            {
                "name": "Wash and go",
                "duration_minutes": 45,
                "price": 1500,
                "deposit_mode": "percent",
                "deposit_value": "25",
                "organization": str(rival_shop.organization.id),
            },
            format="json",
        )

        assert response.status_code == 201
        created = Service.objects.for_org(shop_setup.organization).get(pk=response.json()["id"])
        assert created.organization_id == shop_setup.organization.id
