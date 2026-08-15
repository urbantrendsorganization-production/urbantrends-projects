"""The endpoint: who may read it, what it returns, and what it refuses.

The access test is the one that matters. CLAUDE.md §12 gives every stylist their
own login so that revenue can be attributed per person; the same decision means
a stylist who could open this page would be reading their colleagues' takings.
"""

import pytest
from django.urls import reverse

from reporting.tests.conftest import REPORT_WEDNESDAY
from scheduling.statuses import AppointmentStatus

pytestmark = pytest.mark.django_db

S = AppointmentStatus


@pytest.fixture
def url(shop_setup):
    return reverse("reporting:report", args=[shop_setup.organization.id])


@pytest.fixture
def as_owner(api_client, shop_setup):
    api_client.force_authenticate(shop_setup.org.owner)
    return api_client


def window(period_days=30):
    return {"from": (REPORT_WEDNESDAY.replace(day=1)).isoformat(), "to": "2026-06-30"}


class TestWhoMayRead:
    def test_an_owner_may(self, as_owner, url):
        assert as_owner.get(url, window()).status_code == 200

    def test_a_manager_may(self, api_client, url, shop_setup, make_user):
        from orgs.models import Membership, Role

        manager = make_user(full_name="Manager")
        Membership.objects.create(
            organization=shop_setup.organization, user=manager, role=Role.MANAGER
        )
        api_client.force_authenticate(manager)

        assert api_client.get(url, window()).status_code == 200

    def test_a_stylist_may_not(self, api_client, url, shop_setup):
        """Per-person logins exist so revenue can be attributed. A stylist who
        can read the attribution can read everybody's pay."""
        api_client.force_authenticate(shop_setup.org.stylist)

        assert api_client.get(url, window()).status_code == 403

    def test_someone_from_another_organization_gets_a_404_not_a_403(
        self, api_client, url, rival_shop
    ):
        """`core/tenancy.py`'s rule: a 403 confirms the organization exists."""
        api_client.force_authenticate(rival_shop.org.owner)

        assert api_client.get(url, window()).status_code == 404

    def test_an_anonymous_request_is_refused(self, api_client, url):
        assert api_client.get(url, window()).status_code in (401, 403)


class TestThePeriod:
    def test_no_range_is_the_last_thirty_days(self, as_owner, url):
        body = as_owner.get(url).json()

        assert body["period"]["days"] == 30

    def test_the_previous_range_is_returned_alongside(self, as_owner, url):
        """The comparison is against the shop's own preceding period and never
        against a pre-BookNasi baseline. The dates it is being compared to are
        printed so nobody has to guess which."""
        body = as_owner.get(url, {"from": "2026-06-01", "to": "2026-06-30"}).json()

        assert body["period"]["previous"] == {
            "starts_on": "2026-05-02",
            "ends_on": "2026-05-31",
            "days": 30,
        }

    def test_a_bad_range_is_a_400_with_a_readable_reason(self, as_owner, url):
        response = as_owner.get(url, {"from": "2026-06-30", "to": "2026-06-01"})

        assert response.status_code == 400
        assert "period" in response.json()

    def test_an_enormous_range_is_refused_rather_than_run(self, as_owner, url):
        response = as_owner.get(url, {"from": "2015-01-01", "to": "2026-01-01"})

        assert response.status_code == 400


class TestTheShape:
    def test_the_body_carries_every_block_the_screen_draws(self, as_owner, url):
        body = as_owner.get(url).json()

        for block in ("period", "scope", "verdict", "outcomes", "no_show", "money", "clients"):
            assert block in body, block
        assert isinstance(body["staff"], list)
        assert isinstance(body["today"], list)

    def test_revenue_and_collected_deposits_are_separate_fields(self, as_owner, url, record, paid):
        """Billed and banked. A single `revenue` field would invite somebody to
        add the deposit to it and report the money twice."""
        paid(record(day=REPORT_WEDNESDAY, hour=9, price=3500), amount=875)
        body = as_owner.get(url, {"from": "2026-06-01", "to": "2026-06-30"}).json()

        assert body["revenue_kes"] == 3500
        assert body["money"]["collected_kes"] == 875

    def test_a_rate_with_no_denominator_is_null_not_zero(self, as_owner, url):
        body = as_owner.get(url, {"from": "2026-06-01", "to": "2026-06-30"}).json()

        assert body["no_show"]["rate"] is None
        assert body["clients"]["repeat_rate"] is None

    def test_the_staff_columns_keep_deposits_next_to_no_shows(self, as_owner, url):
        """The design says to keep them adjacent because the adjacency is the
        argument: the stylist with no deposits is the one with seven no-shows."""
        body = as_owner.get(url).json()
        columns = list(body["staff"][0])

        assert columns.index("no_shows") - columns.index("deposits_kes") == 1


class TestTheShopScope:
    @pytest.fixture
    def second_shop(self, shop_setup):
        from conftest import _build_shop

        return _build_shop(shop_setup.org, "mint-braids-thika", "Mint Braids Thika Road")

    def test_every_shop_is_listed_even_when_one_is_selected(
        self, as_owner, url, shop_setup, second_shop
    ):
        """The switcher shows today's load per branch and sits on the same
        screen, so scoping the aggregates must not empty the list."""
        body = as_owner.get(url, {"shop": str(shop_setup.shop.id)}).json()

        assert len(body["scope"]["shops"]) == 2
        assert body["scope"]["shop_id"] == str(shop_setup.shop.id)

    def test_selecting_a_shop_narrows_the_numbers(
        self, as_owner, url, record, shop_setup, second_shop
    ):
        record(day=REPORT_WEDNESDAY, hour=9, price=3500)
        params = {"from": "2026-06-01", "to": "2026-06-30"}

        everything = as_owner.get(url, params).json()
        other = as_owner.get(url, {**params, "shop": str(second_shop.shop.id)}).json()

        assert everything["revenue_kes"] == 3500
        assert other["revenue_kes"] == 0

    def test_another_tenants_shop_id_is_a_404(self, as_owner, url, rival_shop):
        assert as_owner.get(url, {"shop": str(rival_shop.shop.id)}).status_code == 404

    def test_a_malformed_shop_id_is_a_404_and_not_a_500(self, as_owner, url):
        """A typed-in or truncated id. Handing it to the ORM raises a UUID
        `ValidationError` from inside a read, which surfaces as a server error
        for what is only an unknown id."""
        assert as_owner.get(url, {"shop": "not-a-uuid"}).status_code == 404

    def test_an_organization_with_no_shops_gets_an_empty_report(self, api_client, org_a):
        """An owner mid-onboarding. A 404 here reads as broken software rather
        than as an empty shop."""
        api_client.force_authenticate(org_a.owner)
        response = api_client.get(reverse("reporting:report", args=[org_a.organization.id]))

        assert response.status_code == 200
        assert response.json()["scope"]["shops"] == []
        assert response.json()["outcomes"]["total"] == 0


class TestTheCache:
    def test_the_range_aggregates_are_cached(self, as_owner, url, record):
        params = {"from": "2026-06-01", "to": "2026-06-30"}
        as_owner.get(url, params)
        record(day=REPORT_WEDNESDAY, hour=9, price=3500)

        assert as_owner.get(url, params).json()["revenue_kes"] == 0

    def test_fresh_bypasses_it(self, as_owner, url, record):
        params = {"from": "2026-06-01", "to": "2026-06-30"}
        as_owner.get(url, params)
        record(day=REPORT_WEDNESDAY, hour=9, price=3500)

        assert as_owner.get(url, {**params, "fresh": "1"}).json()["revenue_kes"] == 3500

    def test_todays_load_is_never_served_from_the_cache(self, as_owner, url, shop_setup):
        """ "How full is Thika Road right now" is the one question on this screen
        where five minutes is visible."""
        from datetime import timedelta

        from django.utils import timezone

        from reporting.period import today_eat
        from scheduling.models import Appointment
        from scheduling.statuses import BookingSource
        from scheduling.tests.conftest import eat

        params = {"from": "2026-06-01", "to": "2026-06-30"}
        as_owner.get(url, params)

        starts_at = eat(today_eat(), 10)
        if starts_at < timezone.now():
            starts_at = timezone.now() + timedelta(minutes=5)
        Appointment.objects.create(
            shop=shop_setup.shop,
            staff=shop_setup.wanjiku,
            service=shop_setup.braids,
            time_range=(starts_at, starts_at + timedelta(hours=1)),
            status=S.CONFIRMED,
            source=BookingSource.WALK_IN,
            price_snapshot=3500,
            deposit_snapshot=0,
            duration_snapshot=60,
        )

        today = as_owner.get(url, params).json()["today"]

        assert today[0]["appointments"] == 1
        assert today[0]["walk_ins"] == 1

    def test_two_managers_see_the_same_numbers(self, as_owner, url, api_client, shop_setup):
        """The cache key carries the scope and not the user. Two people looking
        at the same range must not be able to disagree."""
        from accounts.models import User
        from orgs.models import Membership, Role

        manager = User.objects.create_user(phone="+254712000777", password="x", full_name="Manager")
        Membership.objects.create(
            organization=shop_setup.organization, user=manager, role=Role.MANAGER
        )
        api_client.force_authenticate(manager)
        params = {"from": "2026-06-01", "to": "2026-06-30"}

        assert as_owner.get(url, params).json() == api_client.get(url, params).json()
