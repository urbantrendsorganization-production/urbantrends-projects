"""The setup screen's one derived question: is this shop bookable yet?

`shops/readiness.py` exists because the answer is the availability engine's
composition rule and not a list of non-empty tables. These tests are mostly
about the four ways a shop can look completely configured and still offer
nothing — each of them a real support call waiting to happen, and each of them
something a frontend reimplementation of the rule would get wrong.
"""

from datetime import time
from decimal import Decimal

import pytest
from django.urls import reverse

from shops.models import (
    DepositMode,
    OpeningHours,
    Service,
    Shop,
    Staff,
    StaffService,
    WorkingHours,
)
from shops.readiness import report_for

pytestmark = pytest.mark.django_db


def keys_failing(report):
    return {check["key"] for check in report["checks"] if not check["done"]}


class TestAFullyConfiguredShop:
    def test_the_design_fixture_is_bookable(self, shop_setup):
        """`shop_setup` is the design's Mint Braids: Mon-Sat, two stylists,
        both offering both services. If this is not bookable, the checks are
        wrong rather than the shop."""
        report = report_for(shop_setup.shop)

        assert report["is_bookable"]
        assert keys_failing(report) == set()

    def test_it_reports_the_booking_address(self, shop_setup):
        report = report_for(shop_setup.shop)

        assert report["booking_url"] == "https://mint-braids-kilimani.booknasi.co.ke"


class TestABrandNewShop:
    """What an owner sees the moment after signup — the case that had no
    screen and no answer at all."""

    def test_everything_is_outstanding(self, org_a):
        shop = Shop.objects.create(
            organization=org_a.organization, name="Fresh Cuts", slug="fresh-cuts"
        )
        report = report_for(shop)

        assert not report["is_bookable"]
        assert keys_failing(report) == {
            "hours",
            "services",
            "deposits",
            "collects",
            "staff",
            "rosters",
            "skills",
            "fits",
        }

    def test_the_checks_are_in_the_order_they_should_be_fixed(self, org_a):
        """Hours before services before staff. An owner works down the list,
        and a list that asked for skills before it asked for staff would be
        asking for something impossible."""
        shop = Shop.objects.create(
            organization=org_a.organization, name="Fresh Cuts", slug="fresh-cuts-2"
        )
        report = report_for(shop)

        assert [check["key"] for check in report["checks"]] == [
            "hours",
            "services",
            "deposits",
            "collects",
            "staff",
            "rosters",
            "skills",
            "fits",
        ]


class TestTheWaysAShopLooksDoneAndOffersNothing:
    """The four that catch people out. Each one passes every naive
    "is the table empty" check and still produces zero slots."""

    def test_a_stylist_with_no_service_ticked_offers_nothing(self, shop_setup):
        """A missing `StaffService` row is not "the default duration" — it is
        "does not do this". `loading.staff_for_service` requires the link."""
        StaffService.objects.for_org(shop_setup.organization).filter(
            staff__shop=shop_setup.shop
        ).delete()

        report = report_for(shop_setup.shop)

        assert not report["is_bookable"]
        assert "skills" in keys_failing(report)
        # Everything before it still passes: the shop is not missing staff or
        # services, it is missing the join between them.
        assert "staff" not in keys_failing(report)
        assert "services" not in keys_failing(report)

    def test_a_link_that_exists_but_is_switched_off_is_not_a_skill(self, shop_setup):
        StaffService.objects.for_org(shop_setup.organization).filter(
            staff__shop=shop_setup.shop
        ).update(is_offered=False)

        report = report_for(shop_setup.shop)

        assert "skills" in keys_failing(report)

    def test_a_stylist_rostered_only_on_a_day_the_shop_is_shut(self, shop_setup):
        """The fixture opens Monday to Saturday. Rostering everyone on Sunday
        alone is a complete roster that overlaps nothing."""
        WorkingHours.objects.for_org(shop_setup.organization).filter(
            staff__shop=shop_setup.shop
        ).delete()
        for staff in Staff.objects.for_org(shop_setup.organization).filter(shop=shop_setup.shop):
            WorkingHours.objects.create(
                staff=staff, weekday=6, starts_at=time(9, 0), ends_at=time(18, 0)
            )

        report = report_for(shop_setup.shop)

        assert not report["is_bookable"]
        assert "rosters" in keys_failing(report)

    def test_a_shift_too_short_for_anything_the_stylist_offers(self, shop_setup):
        """Everything ticked, everyone rostered, and no window long enough.

        The fixture's only deposit-taking service is a four-hour braid, so a
        one-hour shift is complete on every other check and yields nothing.
        """
        WorkingHours.objects.for_org(shop_setup.organization).filter(
            staff__shop=shop_setup.shop
        ).update(starts_at=time(9, 0), ends_at=time(10, 0))

        report = report_for(shop_setup.shop)

        assert not report["is_bookable"]
        assert keys_failing(report) == {"fits"}

    def test_a_per_staff_override_can_make_it_fit(self, shop_setup):
        """`resolve_duration`, not `service.duration_minutes` — CLAUDE.md §3's
        senior stylist, and the reason this check reads through the one
        resolution function rather than the service's own column."""
        WorkingHours.objects.for_org(shop_setup.organization).filter(
            staff__shop=shop_setup.shop
        ).update(starts_at=time(9, 0), ends_at=time(10, 0))
        StaffService.objects.for_org(shop_setup.organization).filter(
            staff=shop_setup.wanjiku, service=shop_setup.braids
        ).update(duration_override_minutes=45)

        report = report_for(shop_setup.shop)

        assert report["is_bookable"]


class TestTheDepositRule:
    """CLAUDE.md §5, on the screen where somebody is about to wonder why the
    service they just added will not appear online."""

    def test_a_shop_selling_only_deposit_free_services_is_not_bookable(self, shop_setup):
        # `save()` rather than `update()`: `shops/integrity.py` refuses a bulk
        # write to a deposit field, because one SQL statement cannot reproduce
        # the rounding, floor and clamp in `shops.money.deposit_amount`.
        for service in Service.objects.for_org(shop_setup.organization).filter(
            shop=shop_setup.shop
        ):
            service.deposit_mode = DepositMode.NONE
            service.deposit_value = None
            service.save()

        report = report_for(shop_setup.shop)

        assert not report["is_bookable"]
        assert "deposits" in keys_failing(report)
        # Not "add a service" — they have services. The distinction is the
        # whole reason these are two checks and not one.
        assert "services" not in keys_failing(report)

    def test_deposit_free_services_are_named_even_when_the_check_passes(self, shop_setup):
        """The fixture's beard trim takes no deposit while the braid does, so
        the shop is bookable and one of its two services is invisible online.
        A checklist that only said "pass" would hide that permanently."""
        report = report_for(shop_setup.shop)

        assert report["is_bookable"]
        assert [row["name"] for row in report["deposit_free_services"]] == ["Beard trim"]

    def test_a_bookable_shop_with_no_hidden_services_reports_none(self, shop_setup):
        trim = Service.objects.for_org(shop_setup.organization).get(
            shop=shop_setup.shop, name="Beard trim"
        )
        trim.deposit_mode = DepositMode.PERCENT
        trim.deposit_value = Decimal("25")
        # `deposit_amount` is deliberately not set: it is `editable=False` and
        # written by the model on save, which is the behaviour under test.
        trim.save()

        report = report_for(shop_setup.shop)

        assert report["deposit_free_services"] == []


class TestItOnlyEverDescribesItsOwnShop:
    def test_a_second_shops_configuration_does_not_count(self, org_a, shop_setup):
        """Two shops under one org. The empty one must not inherit the
        configured one's staff, hours or services — every query in the module
        is org-scoped, which is exactly the scoping that would make this pass
        wrongly if the shop filter were dropped."""
        empty = Shop.objects.create(
            organization=org_a.organization, name="Second Branch", slug="second-branch"
        )

        report = report_for(empty)

        assert not report["is_bookable"]
        assert keys_failing(report) == {
            "hours",
            "services",
            "deposits",
            "collects",
            "staff",
            "rosters",
            "skills",
            "fits",
        }

    def test_the_configured_shop_is_unaffected_by_the_empty_one(self, org_a, shop_setup):
        Shop.objects.create(
            organization=org_a.organization, name="Second Branch", slug="second-branch-2"
        )

        assert report_for(shop_setup.shop)["is_bookable"]


class TestInactiveRowsDoNotCount:
    def test_a_deactivated_stylist_is_not_staff(self, shop_setup):
        Staff.objects.for_org(shop_setup.organization).filter(shop=shop_setup.shop).update(
            is_active=False
        )

        report = report_for(shop_setup.shop)

        assert "staff" in keys_failing(report)

    def test_a_stylist_who_is_not_bookable_is_not_staff(self, shop_setup):
        """`is_bookable` is the client-facing switch — a manager who does not
        take appointments. `loading.staff_for_service` filters on it, so this
        check has to as well."""
        Staff.objects.for_org(shop_setup.organization).filter(shop=shop_setup.shop).update(
            is_bookable=False
        )

        report = report_for(shop_setup.shop)

        assert "staff" in keys_failing(report)

    def test_a_deactivated_service_is_not_a_service(self, shop_setup):
        Service.objects.for_org(shop_setup.organization).filter(shop=shop_setup.shop).update(
            is_active=False
        )

        report = report_for(shop_setup.shop)

        assert "services" in keys_failing(report)


class TestTheShapeIsStable:
    """The frontend renders `checks` generically. A check that arrived without
    the fields the screen reads would render as a blank row."""

    def test_every_check_carries_a_title_a_detail_and_an_action(self, shop_setup):
        for check in report_for(shop_setup.shop)["checks"]:
            assert check["key"]
            assert check["title"]
            assert check["detail"]
            assert check["action"] in {"shop", "hours", "services", "staff", "mpesa"}
            assert isinstance(check["done"], bool)

    def test_is_bookable_is_exactly_every_check_passing(self, shop_setup, org_a):
        for shop in (
            shop_setup.shop,
            Shop.objects.create(organization=org_a.organization, name="Empty", slug="empty-shop"),
        ):
            report = report_for(shop)
            assert report["is_bookable"] == all(check["done"] for check in report["checks"])


class TestOpeningHoursOnly:
    def test_hours_alone_do_not_make_a_shop_bookable(self, org_a):
        shop = Shop.objects.create(
            organization=org_a.organization, name="Hours Only", slug="hours-only"
        )
        OpeningHours.objects.create(shop=shop, weekday=0, opens_at=time(9), closes_at=time(17))

        report = report_for(shop)

        assert not report["is_bookable"]
        assert keys_failing(report) == {
            "services",
            "deposits",
            "collects",
            "staff",
            "rosters",
            "skills",
            "fits",
        }


class TestTheEndpoint:
    def url(self, shop):
        return reverse("shops:shop-readiness", args=[shop.organization_id, shop.id])

    def test_an_owner_can_read_it(self, api_client, shop_setup):
        api_client.force_login(shop_setup.org.owner)

        response = api_client.get(self.url(shop_setup.shop))

        assert response.status_code == 200
        assert response.data["is_bookable"] is True

    def test_a_stylist_cannot(self, api_client, shop_setup):
        """Managing roles only, like every other endpoint on this shop's
        configuration. A stylist has no screen that asks for it."""
        api_client.force_login(shop_setup.org.stylist)

        response = api_client.get(self.url(shop_setup.shop))

        assert response.status_code == 403

    def test_another_orgs_shop_is_a_404_not_a_403(self, api_client, shop_setup, rival_shop):
        """Slice 1's rule, re-asserted for the endpoint this slice adds — a
        403 would confirm the shop exists."""
        api_client.force_login(shop_setup.org.owner)

        response = api_client.get(self.url(rival_shop.shop))

        assert response.status_code == 404

    def test_signed_out_is_refused(self, api_client, shop_setup):
        response = api_client.get(self.url(shop_setup.shop))

        assert response.status_code in (401, 403)
