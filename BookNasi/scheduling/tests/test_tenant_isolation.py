"""LOAD-BEARING. Tenant isolation for slice 3's models and endpoints.

The queryset guard covers the model layer mechanically — `Appointment` and
`Client` are registered in `core/tests/test_org_scoped_manager_guard.py` and
every route to the database is closed there. What is not mechanical is the
endpoint layer and the *derived* organization column: an appointment gets its
org from its shop on every save, and that has to hold even when a caller
supplies a different one.
"""

from datetime import timedelta

import pytest
from django.urls import reverse

from clients.models import Client
from scheduling.models import Appointment
from scheduling.statuses import AppointmentStatus, BookingSource
from scheduling.tests.conftest import eat

pytestmark = [pytest.mark.django_db, pytest.mark.loadbearing]


def make(setup, day, hour=10, **overrides):
    start = eat(day, hour)
    fields = {
        "shop": setup.shop,
        "staff": setup.wanjiku,
        "service": setup.braids,
        "time_range": (start, start + timedelta(hours=1)),
        "status": AppointmentStatus.CONFIRMED,
        "source": BookingSource.STAFF,
        "price_snapshot": 3500,
        "deposit_snapshot": 875,
        "duration_snapshot": 60,
    }
    fields.update(overrides)
    return Appointment.objects.create(**fields)


class TestForeignOrgGets404:
    def test_staff_availability_of_another_org(self, api_client, shop_setup, rival_shop, wednesday):
        """404 rather than 403, so ids stay unenumerable. Slice 1's rule,
        unchanged and re-asserted for every new endpoint."""
        api_client.force_login(rival_shop.org.owner)

        response = api_client.get(
            reverse(
                "scheduling:staff-availability",
                args=[shop_setup.organization.id, shop_setup.shop.id, shop_setup.wanjiku.id],
            ),
            {"date": wednesday.isoformat(), "service": str(shop_setup.braids.id)},
        )

        assert response.status_code == 404

    def test_a_staff_id_from_another_org_inside_your_own_url(
        self, api_client, shop_setup, rival_shop, wednesday
    ):
        """The nested-lookup case: the org resolves, the shop resolves, and the
        staff id belongs to somebody else."""
        api_client.force_login(shop_setup.org.owner)

        response = api_client.get(
            reverse(
                "scheduling:staff-availability",
                args=[shop_setup.organization.id, shop_setup.shop.id, rival_shop.wanjiku.id],
            ),
            {"date": wednesday.isoformat(), "service": str(shop_setup.braids.id)},
        )

        assert response.status_code == 404

    def test_a_service_id_from_another_org(self, api_client, shop_setup, rival_shop, wednesday):
        api_client.force_login(shop_setup.org.owner)

        response = api_client.get(
            reverse(
                "scheduling:staff-availability",
                args=[shop_setup.organization.id, shop_setup.shop.id, shop_setup.wanjiku.id],
            ),
            {"date": wednesday.isoformat(), "service": str(rival_shop.braids.id)},
        )

        assert response.status_code == 404


class TestTheDerivedOrganization:
    def test_it_comes_from_the_shop(self, shop_setup, wednesday):
        appointment = make(shop_setup, wednesday)

        assert appointment.organization_id == shop_setup.organization.id

    def test_a_supplied_organization_is_overwritten_not_trusted(
        self, shop_setup, rival_shop, wednesday
    ):
        """`OrgDerivedModel` recomputes it on every save. A forged value in a
        request body — or in a fixture, or in a management command — never
        reaches the column."""
        appointment = make(shop_setup, wednesday, organization=rival_shop.organization)

        assert appointment.organization_id == shop_setup.organization.id

    def test_it_survives_a_partial_save(self, shop_setup, rival_shop, wednesday):
        """`save(update_fields=[...])` has to carry the derived column too, or a
        partial write leaves it pointing at the old tenant."""
        appointment = make(shop_setup, wednesday)
        appointment.organization = rival_shop.organization
        appointment.status = AppointmentStatus.COMPLETED
        appointment.save(update_fields=["status"])

        appointment.refresh_from_db()
        assert appointment.organization_id == shop_setup.organization.id
        assert appointment.status == AppointmentStatus.COMPLETED


class TestQueriesAreScoped:
    def test_one_orgs_appointments_are_invisible_to_another(
        self, shop_setup, rival_shop, wednesday
    ):
        make(shop_setup, wednesday)
        make(rival_shop, wednesday)

        ours = Appointment.objects.for_org(shop_setup.organization)

        assert ours.count() == 1
        assert ours.first().shop_id == shop_setup.shop.id

    def test_clients_are_scoped_too(self, org_a, org_b):
        Client.objects.create(organization=org_a.organization, phone="0712345678")
        Client.objects.create(organization=org_b.organization, phone="0722000000")

        assert Client.objects.for_org(org_a.organization).count() == 1

    def test_the_availability_loader_never_reads_across_tenants(
        self, shop_setup, rival_shop, wednesday
    ):
        """Both shops have a stylist called Wanjiku working the same hours. The
        loader has to return one shop's day, not a merge of two."""
        from scheduling.loading import gather_shop_day

        make(rival_shop, wednesday)

        facts = gather_shop_day(shop_setup.shop, wednesday)

        assert set(facts) == {shop_setup.wanjiku.id, shop_setup.grace.id}
        assert all(f.busy == () for f in facts.values())


class TestThePublicSurfaceStaysShopScoped:
    def test_availability_by_slug_reaches_only_that_shop(
        self, api_client, shop_setup, rival_shop, wednesday
    ):
        body = api_client.get(
            reverse("public_api:availability", args=[shop_setup.shop.slug, shop_setup.braids.id]),
            {"date": wednesday.isoformat()},
        ).json()

        names = {entry["display_name"] for entry in body["by_staff"]}

        assert names == {"Wanjiku", "Grace"}
        assert len(body["by_staff"]) == 2  # not four

    def test_a_deactivated_shop_has_no_public_availability(self, api_client, shop_setup, wednesday):
        shop_setup.shop.is_active = False
        shop_setup.shop.save(update_fields=["is_active"])

        response = api_client.get(
            reverse("public_api:availability", args=[shop_setup.shop.slug, shop_setup.braids.id]),
            {"date": wednesday.isoformat()},
        )

        assert response.status_code == 404
