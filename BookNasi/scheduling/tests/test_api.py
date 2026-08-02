"""The two availability endpoints. Read-only, and they must agree.

The public route and the org-scoped route differ in exactly two things: who may
ask, and which `Policy` applies. Anything else that diverges means a client and
a stylist are looking at different calendars, which is the failure that ends
with two people in one chair and both of them holding a phone.

Slice 5 adds the other half. The two surfaces agree on what they **offer** and
diverge on what they let you **write**: shop configuration binds the public
booking page and advises the staff screen. `TestTheTwoSurfacesAgree` pins the
first; `TestTheTwoSurfacesDivergeOnWrites` pins the second, at the real
endpoints, in both directions — including the one rule that binds everyone.
"""

from datetime import timedelta

import pytest
from django.urls import reverse

from scheduling.tests.conftest import eat
from shops.models import Leave, ShopClosure, StaffService

pytestmark = pytest.mark.django_db


def public_url(shop_setup, service=None):
    return reverse(
        "public_api:availability",
        args=[shop_setup.shop.slug, (service or shop_setup.braids).id],
    )


def staff_url(shop_setup, staff=None):
    return reverse(
        "scheduling:staff-availability",
        args=[
            shop_setup.organization.id,
            shop_setup.shop.id,
            (staff or shop_setup.wanjiku).id,
        ],
    )


class TestPublicAvailability:
    def test_it_needs_no_login(self, api_client, shop_setup, wednesday):
        response = api_client.get(public_url(shop_setup), {"date": wednesday.isoformat()})

        assert response.status_code == 200

    def test_it_returns_slots_per_staff_and_an_any_staff_list(
        self, api_client, shop_setup, wednesday
    ):
        body = api_client.get(public_url(shop_setup), {"date": wednesday.isoformat()}).json()

        assert {entry["display_name"] for entry in body["by_staff"]} == {"Wanjiku", "Grace"}
        assert body["any_staff"]
        assert body["date"] == wednesday.isoformat()

    def test_any_staff_deduplicates_a_start_offered_by_two_stylists(
        self, api_client, shop_setup, wednesday
    ):
        """ "Anyone available" is earliest-available-slot, not an assignment
        algorithm — CLAUDE.md §12. The client should see 09:00 once, not once
        per stylist who happens to be free."""
        body = api_client.get(public_url(shop_setup), {"date": wednesday.isoformat()}).json()

        starts = [slot["starts_at"] for slot in body["any_staff"]]

        assert len(starts) == len(set(starts))
        assert starts == sorted(starts)

    def test_slots_carry_both_utc_and_the_eat_wall_clock(self, api_client, shop_setup, wednesday):
        """The wall clock is computed server-side so a browser with a
        misconfigured timezone cannot render 09:00 as 06:00 and book the wrong
        hour."""
        body = api_client.get(public_url(shop_setup), {"date": wednesday.isoformat()}).json()
        first = body["by_staff"][0]["slots"][0]

        assert first["local_time"] == "09:00"
        assert first["starts_at"].startswith("2026-09-09T06:00")
        assert first["duration_minutes"] == 240

    def test_a_deposit_free_service_is_not_reachable(self, api_client, shop_setup, wednesday):
        """CLAUDE.md §5, enforced at the API and not only in the UI. Without a
        payment there is no phone verification, so there is nothing to offer."""
        response = api_client.get(
            public_url(shop_setup, shop_setup.shave), {"date": wednesday.isoformat()}
        )

        assert response.status_code == 404

    def test_a_closed_day_returns_an_empty_list_not_an_error(
        self, api_client, shop_setup, wednesday
    ):
        """Zero availability is an ordinary Sunday, not a 500."""
        ShopClosure.objects.create(shop=shop_setup.shop, starts_on=wednesday, ends_on=wednesday)

        response = api_client.get(public_url(shop_setup), {"date": wednesday.isoformat()})

        assert response.status_code == 200
        assert response.json()["any_staff"] == []
        assert all(entry["slots"] == [] for entry in response.json()["by_staff"])

    def test_a_missing_date_is_a_400_with_a_readable_message(self, api_client, shop_setup):
        """Not a default of today: a client on a slow connection would silently
        get a different day than the chip they tapped."""
        response = api_client.get(public_url(shop_setup))

        assert response.status_code == 400
        assert "date" in response.json()

    def test_a_malformed_date_is_a_400(self, api_client, shop_setup):
        response = api_client.get(public_url(shop_setup), {"date": "next tuesday"})

        assert response.status_code == 400

    def test_it_can_be_narrowed_to_one_stylist(self, api_client, shop_setup, wednesday):
        body = api_client.get(
            public_url(shop_setup),
            {"date": wednesday.isoformat(), "staff": str(shop_setup.wanjiku.id)},
        ).json()

        assert [entry["display_name"] for entry in body["by_staff"]] == ["Wanjiku"]

    def test_another_shops_stylist_is_a_404(self, api_client, shop_setup, rival_shop, wednesday):
        response = api_client.get(
            public_url(shop_setup),
            {"date": wednesday.isoformat(), "staff": str(rival_shop.wanjiku.id)},
        )

        assert response.status_code == 404

    def test_another_shops_service_is_a_404(self, api_client, shop_setup, rival_shop, wednesday):
        url = reverse("public_api:availability", args=[shop_setup.shop.slug, rival_shop.braids.id])

        response = api_client.get(url, {"date": wednesday.isoformat()})

        assert response.status_code == 404

    def test_a_stylist_on_leave_disappears_from_the_day(self, api_client, shop_setup, wednesday):
        Leave.objects.create(staff=shop_setup.wanjiku, starts_on=wednesday, ends_on=wednesday)

        body = api_client.get(public_url(shop_setup), {"date": wednesday.isoformat()}).json()
        by_name = {entry["display_name"]: entry["slots"] for entry in body["by_staff"]}

        assert by_name["Wanjiku"] == []
        assert by_name["Grace"]

    def test_per_staff_durations_produce_different_slot_sets(
        self, api_client, shop_setup, wednesday
    ):
        StaffService.objects.for_org(shop_setup.organization).filter(
            staff=shop_setup.wanjiku, service=shop_setup.braids
        ).update(duration_override_minutes=120)

        body = api_client.get(public_url(shop_setup), {"date": wednesday.isoformat()}).json()
        by_name = {entry["display_name"]: entry["slots"] for entry in body["by_staff"]}

        assert by_name["Wanjiku"][0]["duration_minutes"] == 120
        assert by_name["Grace"][0]["duration_minutes"] == 240
        assert len(by_name["Wanjiku"]) > len(by_name["Grace"])

    def test_a_day_beyond_the_horizon_is_empty(self, api_client, shop_setup, wednesday):
        far = wednesday + timedelta(days=196)  # 28 weeks: still a Wednesday

        body = api_client.get(public_url(shop_setup), {"date": far.isoformat()}).json()

        assert body["any_staff"] == []

    def test_it_leaks_nothing_tenant_scoped(self, api_client, shop_setup, wednesday):
        raw = api_client.get(
            public_url(shop_setup), {"date": wednesday.isoformat()}
        ).content.decode()

        assert str(shop_setup.organization.id) not in raw
        assert "organization" not in raw
        assert "buffer_minutes" not in raw
        assert "membership" not in raw


class TestStaffAvailability:
    def test_it_requires_a_login(self, api_client, shop_setup, wednesday):
        response = api_client.get(
            staff_url(shop_setup),
            {"date": wednesday.isoformat(), "service": str(shop_setup.braids.id)},
        )

        assert response.status_code in (401, 403)

    def test_an_owner_sees_the_day(self, api_client, shop_setup, wednesday):
        api_client.force_login(shop_setup.org.owner)

        response = api_client.get(
            staff_url(shop_setup),
            {"date": wednesday.isoformat(), "service": str(shop_setup.braids.id)},
        )

        assert response.status_code == 200
        assert response.json()["by_staff"][0]["display_name"] == "Wanjiku"

    def test_another_tenants_org_is_a_404_not_a_403(
        self, api_client, shop_setup, rival_shop, wednesday
    ):
        """404 so ids are not enumerable — the slice 1 rule, unchanged."""
        api_client.force_login(rival_shop.org.owner)

        response = api_client.get(
            staff_url(shop_setup),
            {"date": wednesday.isoformat(), "service": str(shop_setup.braids.id)},
        )

        assert response.status_code == 404

    def test_staff_have_no_lead_time(self, api_client, shop_setup, wednesday):
        """The same engine under `Policy.for_staff()`. A walk-in starts now, and
        a 30-minute lead time would make the three-tap entry impossible."""
        api_client.force_login(shop_setup.org.owner)

        body = api_client.get(
            staff_url(shop_setup),
            {"date": wednesday.isoformat(), "service": str(shop_setup.braids.id)},
        ).json()

        assert body["by_staff"][0]["slots"][0]["local_time"] == "09:00"

    def test_a_deposit_free_service_is_visible_to_staff(self, api_client, shop_setup, wednesday):
        """The other half of CLAUDE.md §5: staff can book it and record it as a
        walk-in; only the *public* surface refuses."""
        api_client.force_login(shop_setup.org.owner)

        response = api_client.get(
            staff_url(shop_setup),
            {"date": wednesday.isoformat(), "service": str(shop_setup.shave.id)},
        )

        assert response.status_code == 200
        assert response.json()["by_staff"][0]["slots"]

    def test_a_missing_service_is_a_404(self, api_client, shop_setup, wednesday):
        api_client.force_login(shop_setup.org.owner)

        response = api_client.get(staff_url(shop_setup), {"date": wednesday.isoformat()})

        assert response.status_code == 404


class TestTheTwoSurfacesAgree:
    def test_the_same_service_and_day_give_the_same_slots(self, api_client, shop_setup, wednesday):
        """The one assertion that would catch the engine being forked. Lead time
        and horizon are the only permitted difference, and neither applies to a
        day well in the future with `now` far in the past."""
        public = api_client.get(
            public_url(shop_setup),
            {"date": wednesday.isoformat(), "staff": str(shop_setup.wanjiku.id)},
        ).json()

        api_client.force_login(shop_setup.org.owner)
        staff = api_client.get(
            staff_url(shop_setup),
            {"date": wednesday.isoformat(), "service": str(shop_setup.braids.id)},
        ).json()

        assert public["by_staff"][0]["slots"] == staff["by_staff"][0]["slots"]

    def test_both_are_read_only(self, api_client, shop_setup, wednesday):
        """Slice 3 ships no booking endpoint. `create_appointment` exists and is
        tested; slices 4 and 5 expose it."""
        api_client.force_login(shop_setup.org.owner)

        for url in (public_url(shop_setup), staff_url(shop_setup)):
            assert api_client.post(url, {}, format="json").status_code == 405
            assert api_client.delete(url).status_code == 405


class TestTheTwoSurfacesDivergeOnWrites:
    """The other half of the agreement above, and the one that took a slice to
    settle. Both surfaces *offer* the same tidy grid — `derive_slots` is always
    bounded by the working window, whatever the policy says — so the divergence
    is not in what is shown. It is in what may be **written**.

    Slice 4 made shop configuration binding for the public and advisory for
    staff: opening hours, dated closures, the slot grid and the turnaround
    buffer. Slice 5 is the mirror, and this class is the pair of assertions that
    pins it. Each test drives the same instant at the two real endpoints — the
    public hold and the staff walk-in — and asserts the answers differ in the
    permitted direction and only there.

    The last test is the important one: collisions are not advisory for anyone.
    That is the line `enforce_shop_config` must never be read as crossing.
    """

    def hold_at(self, api_client, shop_setup, when, phone="0712345678"):
        return api_client.post(
            reverse("public_api:hold-create", kwargs={"slug": shop_setup.shop.slug}),
            {
                "service": str(shop_setup.braids.id),
                "staff": str(shop_setup.wanjiku.id),
                "starts_at": when.isoformat(),
                "phone": phone,
            },
            format="json",
        )

    def walk_in_at(self, api_client, shop_setup, when, **extra):
        api_client.force_login(shop_setup.org.owner)
        return api_client.post(
            reverse(
                "scheduling:walk-in",
                args=[shop_setup.organization.id, shop_setup.shop.id],
            ),
            {
                "service": str(shop_setup.braids.id),
                "staff": str(shop_setup.wanjiku.id),
                "starts_at": when.isoformat(),
                **extra,
            },
            format="json",
        )

    def test_a_time_that_is_on_no_grid_is_refused_publicly_and_recorded_by_staff(
        self, api_client, shop_setup, wednesday
    ):
        """11:04. A client cannot ask for it — the design's chips are clock
        times and an off-grid start read back as "11:04" looks like a mistake.
        A stylist recording what is happening in front of them can, because
        11:04 is when the client actually sat down."""
        off_grid = eat(wednesday, 11, 4)

        assert self.hold_at(api_client, shop_setup, off_grid).status_code == 409
        assert self.walk_in_at(api_client, shop_setup, off_grid).status_code == 201

    def test_a_start_after_working_hours_is_refused_publicly_and_recorded_by_staff(
        self, api_client, shop_setup, wednesday
    ):
        """CLAUDE.md's 6:15 pm walk-in, at the endpoints. The fixture's stylists
        work until 18:00, so 18:30 is outside the window on both surfaces — and
        only one of them may refuse it."""
        late = eat(wednesday, 18, 30)

        assert self.hold_at(api_client, shop_setup, late).status_code == 409
        assert self.walk_in_at(api_client, shop_setup, late).status_code == 201

    def test_a_dated_closure_is_absolute_publicly_and_advisory_for_staff(
        self, api_client, shop_setup, wednesday
    ):
        """A shop that shut for a funeral and then opened at four. The closure
        is the fact that wins for a client picking a time next week; it is a
        note on the wall for the stylist standing in the open shop."""
        ShopClosure.objects.create(
            shop=shop_setup.shop, starts_on=wednesday, ends_on=wednesday, reason="Funeral"
        )

        assert self.hold_at(api_client, shop_setup, eat(wednesday, 10)).status_code == 409
        assert self.walk_in_at(api_client, shop_setup, eat(wednesday, 10)).status_code == 201

    def test_a_collision_is_refused_on_both_surfaces(self, api_client, shop_setup, wednesday):
        """The line that does not move. Two people cannot occupy one chair, the
        exclusion constraint refuses the row regardless of policy, and the only
        difference between the two surfaces is what the refusal *says*: the
        client is told the slot went, the stylist is handed ranked options.
        """
        taken = eat(wednesday, 10)
        assert self.hold_at(api_client, shop_setup, taken).status_code == 201

        client_refusal = self.hold_at(api_client, shop_setup, taken, phone="0722000002")
        staff_refusal = self.walk_in_at(api_client, shop_setup, taken)

        assert client_refusal.status_code == 409
        assert staff_refusal.status_code == 409
        assert staff_refusal.json()["options"], "a staff collision must arrive as a choice"

    def test_the_public_lead_time_is_the_only_divergence_on_the_offer_list(
        self, api_client, shop_setup, wednesday
    ):
        """Stated as a test so it is not re-derived by hand later: the offer
        lists diverge on lead time and horizon and on nothing else. Shop
        configuration shapes both lists identically — it is only the write that
        it stops binding.
        """
        shop_setup.shop.min_lead_minutes = 0
        shop_setup.shop.booking_horizon_days = 365
        shop_setup.shop.save(update_fields=["min_lead_minutes", "booking_horizon_days"])

        public = api_client.get(
            public_url(shop_setup),
            {"date": wednesday.isoformat(), "staff": str(shop_setup.wanjiku.id)},
        ).json()
        api_client.force_login(shop_setup.org.owner)
        staff = api_client.get(
            staff_url(shop_setup),
            {"date": wednesday.isoformat(), "service": str(shop_setup.braids.id)},
        ).json()

        assert public["by_staff"][0]["slots"] == staff["by_staff"][0]["slots"]
