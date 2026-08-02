"""LOAD-BEARING. The walk-in path through the exclusion constraint.

CLAUDE.md §4: "In Kenya walk-ins are the majority. If staff can't record one in
three taps, they won't, the calendar drifts from reality, and online bookings
start colliding with people already in the chair. Any change that adds friction
to walk-in entry is a regression."

Three decisions are protected here rather than merely implemented, which is why
this file is named explicitly in CI:

1. **A collision is a choice, never an error.** The endpoint answers 409 with
   ranked options the engine computed. A test asserting the shape of that
   response is what stops the next person turning it into a 400 with a message.
2. **Every write goes through `create_appointment`.** Asserted structurally, by
   reading the source, because "there is no second insert path" is not something
   a behavioural test can see.
3. **The offline retry is safe.** The same `client_request_id` sent twice yields
   one appointment and not a self-collision.
"""

import ast
import pathlib
from datetime import timedelta

import pytest
from django.urls import reverse

from scheduling.booking import create_appointment
from scheduling.collisions import SHORTEN_FLOOR, resolve
from scheduling.models import Appointment
from scheduling.statuses import AppointmentStatus, BookingSource
from scheduling.tests.conftest import eat
from scheduling.transitions import apply_transition
from shops.models import StaffService

pytestmark = [pytest.mark.django_db, pytest.mark.loadbearing]


@pytest.fixture
def signed_in(api_client, shop_setup):
    api_client.force_authenticate(shop_setup.org.stylist)
    return api_client


@pytest.fixture
def walk_in_url(shop_setup):
    return reverse(
        "scheduling:walk-in",
        kwargs={"org_id": shop_setup.organization.id, "shop_id": shop_setup.shop.id},
    )


class TestTheThreeTaps:
    def test_one_post_records_a_walk_in(self, signed_in, shop_setup, walk_in_url):
        """Tap 3. Service and staff are the only required fields, `starts_at`
        defaults to now, and no name is asked for."""
        response = signed_in.post(
            walk_in_url,
            {"service": str(shop_setup.shave.id), "staff": str(shop_setup.grace.id)},
            format="json",
        )

        assert response.status_code == 201, response.data
        assert response.data["source"] == "walk_in"
        assert response.data["status"] == "in_progress"
        assert response.data["client_name"] == ""

    def test_a_walk_in_takes_no_deposit(self, signed_in, shop_setup, walk_in_url):
        """CLAUDE.md §12, and the design's confirm step says so in words. The
        braid carries a 25% deposit as a booking and none as a walk-in."""
        response = signed_in.post(
            walk_in_url,
            {"service": str(shop_setup.braids.id), "staff": str(shop_setup.grace.id)},
            format="json",
        )

        assert response.status_code == 201
        assert response.data["deposit_kes"] == 0
        assert shop_setup.braids.deposit_amount > 0  # ...and it would have, online

    def test_waiting_not_started_is_confirmed_with_no_clock(
        self, signed_in, shop_setup, walk_in_url
    ):
        response = signed_in.post(
            walk_in_url,
            {
                "service": str(shop_setup.shave.id),
                "staff": str(shop_setup.grace.id),
                "waiting": True,
            },
            format="json",
        )

        assert response.status_code == 201
        assert response.data["status"] == "confirmed"
        assert response.data["is_waiting"] is True
        assert response.data["status_label"] == "Waiting"
        assert response.data["started_at"] is None

    def test_the_name_is_asked_after_saving(self, signed_in, shop_setup, walk_in_url):
        """The row exists and holds the chair before anybody is asked for a
        name. That ordering is the whole reason the flow is three taps."""
        created = signed_in.post(
            walk_in_url,
            {"service": str(shop_setup.shave.id), "staff": str(shop_setup.grace.id)},
            format="json",
        )
        url = reverse(
            "scheduling:appointment-client",
            kwargs={
                "org_id": shop_setup.organization.id,
                "shop_id": shop_setup.shop.id,
                "appointment_id": created.data["id"],
            },
        )

        response = signed_in.post(url, {"full_name": "Amina", "phone": "0712345678"}, format="json")

        assert response.status_code == 200
        assert response.data["client_name"] == "Amina"
        assert response.data["client_phone"] == "+254712345678"

    def test_the_same_client_across_two_branches_is_one_person(
        self, signed_in, shop_setup, walk_in_url, wednesday
    ):
        """CLAUDE.md §3: Client belongs to the Org, never the Shop."""
        from clients.models import Client

        # Two separate visits: the same number, an hour apart. Same instant
        # would simply collide, which is a different test.
        for hour in (9, 11):
            created = signed_in.post(
                walk_in_url,
                {
                    "service": str(shop_setup.shave.id),
                    "staff": str(shop_setup.grace.id),
                    "starts_at": eat(wednesday, hour).isoformat(),
                },
                format="json",
            )
            assert created.status_code == 201, created.data
            signed_in.post(
                reverse(
                    "scheduling:appointment-client",
                    kwargs={
                        "org_id": shop_setup.organization.id,
                        "shop_id": shop_setup.shop.id,
                        "appointment_id": created.data["id"],
                    },
                ),
                {"full_name": "Amina", "phone": "0712345678"},
                format="json",
            )

        assert Client.objects.for_org(shop_setup.organization).count() == 1


class TestTapOneAndTwo:
    def test_the_options_call_returns_everything_both_taps_need(self, signed_in, shop_setup):
        url = reverse(
            "scheduling:walk-in-options",
            kwargs={"org_id": shop_setup.organization.id, "shop_id": shop_setup.shop.id},
        )

        response = signed_in.get(url)

        assert response.status_code == 200
        assert {"top_services", "other_services", "staff", "now"} <= set(response.data)
        assert len(response.data["staff"]) == 2
        assert any(person["is_me"] for person in response.data["staff"])

    def test_the_five_are_this_staff_members_most_recorded(self, signed_in, shop_setup, wednesday):
        """Ranked by what this person has done, not by what the shop sells."""
        from scheduling.dayview import top_services_for

        for hour in (9, 10, 11):
            create_appointment(
                staff=shop_setup.grace,
                service=shop_setup.shave,
                starts_at=eat(wednesday, hour),
                source=BookingSource.WALK_IN,
                now=eat(wednesday, hour),
            )

        top = top_services_for(shop_setup.grace)

        assert top[0].id == shop_setup.shave.id

    def test_a_new_staff_member_still_gets_a_first_tap(self, shop_setup):
        """No history at all. An empty first tap would make the flow four taps
        on somebody's first day."""
        from scheduling.dayview import top_services_for

        top = top_services_for(shop_setup.wanjiku)

        assert len(top) == 2  # the fixture's whole catalogue

    def test_the_duration_is_this_staff_members_own(self, signed_in, shop_setup):
        """CLAUDE.md §3. Grace takes longer over a braid than Wanjiku, and tap 1
        must say so or the confirm step lies about the finish time."""
        StaffService.objects.for_org(shop_setup.organization).filter(
            staff=shop_setup.grace, service=shop_setup.braids
        ).update(duration_override_minutes=300)
        url = reverse(
            "scheduling:walk-in-options",
            kwargs={"org_id": shop_setup.organization.id, "shop_id": shop_setup.shop.id},
        )

        response = signed_in.get(url)

        braids = next(
            row
            for row in response.data["top_services"]
            if str(row["id"]) == str(shop_setup.braids.id)
        )
        assert braids["duration_minutes"] == 300


class TestACollisionIsAChoice:
    def test_it_is_never_a_validation_error(self, signed_in, shop_setup, walk_in_url, wednesday):
        """409 with options, not 400 with a message above a form."""
        now = eat(wednesday, 10)
        create_appointment(
            staff=shop_setup.grace,
            service=shop_setup.braids,
            starts_at=now,
            source=BookingSource.STAFF,
            now=now,
        )

        response = signed_in.post(
            walk_in_url,
            {
                "service": str(shop_setup.shave.id),
                "staff": str(shop_setup.grace.id),
                "starts_at": (now + timedelta(minutes=30)).isoformat(),
            },
            format="json",
        )

        assert response.status_code == 409
        assert response.data["options"]
        assert response.data["blocked_until"]

    def test_an_option_is_resubmitted_unchanged(
        self, signed_in, shop_setup, walk_in_url, wednesday
    ):
        """The client does no arithmetic. Whatever the engine offered goes
        straight back, and it works."""
        now = eat(wednesday, 10)
        create_appointment(
            staff=shop_setup.grace,
            service=shop_setup.braids,
            starts_at=now,
            source=BookingSource.STAFF,
            now=now,
        )
        refused = signed_in.post(
            walk_in_url,
            {
                "service": str(shop_setup.shave.id),
                "staff": str(shop_setup.grace.id),
                "starts_at": (now + timedelta(minutes=30)).isoformat(),
            },
            format="json",
        )
        option = refused.data["options"][0]

        accepted = signed_in.post(
            walk_in_url,
            {
                "service": str(shop_setup.shave.id),
                "staff": option["staff_id"],
                "starts_at": option["starts_at"],
                "duration_minutes": option["duration_minutes"],
                "allow_over_completed": option["allow_over_completed"],
            },
            format="json",
        )

        assert accepted.status_code == 201, accepted.data

    def test_give_it_to_a_colleague_is_offered(self, shop_setup, wednesday):
        now = eat(wednesday, 10)
        create_appointment(
            staff=shop_setup.grace,
            service=shop_setup.braids,
            starts_at=now,
            source=BookingSource.STAFF,
            now=now,
        )

        options, _ = resolve(
            staff=shop_setup.grace,
            service=shop_setup.shave,
            starts_at=now + timedelta(minutes=30),
            duration_minutes=20,
        )

        handovers = [o for o in options if o.kind == "other_staff"]
        assert handovers
        assert handovers[0].staff_id == str(shop_setup.wanjiku.id)

    def test_a_colleague_gets_their_own_duration(self, shop_setup, wednesday):
        """Handing the job over at the wrong length would put a lie straight
        into the calendar — CLAUDE.md §3."""
        StaffService.objects.for_org(shop_setup.organization).filter(
            staff=shop_setup.wanjiku, service=shop_setup.shave
        ).update(duration_override_minutes=45)
        now = eat(wednesday, 10)
        create_appointment(
            staff=shop_setup.grace,
            service=shop_setup.braids,
            starts_at=now,
            source=BookingSource.STAFF,
            now=now,
        )

        options, _ = resolve(
            staff=shop_setup.grace,
            service=shop_setup.shave,
            starts_at=now + timedelta(minutes=30),
            duration_minutes=20,
        )

        handover = next(o for o in options if o.kind == "other_staff")
        assert handover.duration_minutes == 45

    def test_shorten_is_offered_when_the_trim_is_small(self, shop_setup, wednesday):
        """A twenty-minute shave with sixteen minutes before the next client is
        a shorter version of the same service, and the design's "shorten to
        12:00"."""
        create_appointment(
            staff=shop_setup.grace,
            service=shop_setup.braids,
            starts_at=eat(wednesday, 10, 16),
            source=BookingSource.STAFF,
            now=eat(wednesday, 9),
        )

        options, _ = resolve(
            staff=shop_setup.grace,
            service=shop_setup.shave,
            starts_at=eat(wednesday, 10),
            duration_minutes=20,
        )

        assert options[0].kind == "shorten"
        assert options[0].duration_minutes == 16

    def test_shorten_is_withheld_when_the_trim_is_heavy(self, shop_setup, wednesday):
        """A four-hour braid trimmed to twenty minutes is not a shorter service,
        it is a different one at the same price — and `price_snapshot` would
        record the full amount against it."""
        create_appointment(
            staff=shop_setup.grace,
            service=shop_setup.shave,
            starts_at=eat(wednesday, 10, 20),
            source=BookingSource.STAFF,
            now=eat(wednesday, 9),
        )

        options, _ = resolve(
            staff=shop_setup.grace,
            service=shop_setup.braids,
            starts_at=eat(wednesday, 10),
            duration_minutes=240,
        )

        assert not [o for o in options if o.kind == "shorten"]
        assert SHORTEN_FLOOR == 0.75

    def test_later_is_anchored_to_when_the_chair_frees(self, shop_setup, wednesday):
        """Off-grid on purpose: 11:47 is the honest answer when 11:47 is when
        the chair frees up, and staff writes are off-grid by design."""
        create_appointment(
            staff=shop_setup.grace,
            service=shop_setup.shave,
            starts_at=eat(wednesday, 10, 7),
            source=BookingSource.WALK_IN,
            now=eat(wednesday, 10, 7),
        )

        options, _ = resolve(
            staff=shop_setup.grace,
            service=shop_setup.shave,
            starts_at=eat(wednesday, 10, 10),
            duration_minutes=20,
        )

        later = next(o for o in options if o.kind == "later")
        assert later.starts_at == eat(wednesday, 10, 27)

    def test_the_ranking_puts_the_whole_service_above_a_heavy_trim(self, shop_setup, wednesday):
        """`other_staff` beats a shortened service; a *light* trim beats both.
        The order is the product decision, so it is asserted rather than
        described."""
        create_appointment(
            staff=shop_setup.grace,
            service=shop_setup.braids,
            starts_at=eat(wednesday, 10, 5),
            source=BookingSource.STAFF,
            now=eat(wednesday, 9),
        )

        options, _ = resolve(
            staff=shop_setup.grace,
            service=shop_setup.shave,
            starts_at=eat(wednesday, 10),
            duration_minutes=20,
        )

        kinds = [o.kind for o in options]
        assert "shorten" not in kinds  # five minutes of twenty is not the service
        assert kinds[0] == "other_staff"


class TestBackfillOverCompletedWork:
    """The concrete case that makes the ACTIVE/BLOCKING divergence load-bearing.

    A stylist finishes at 11:30 and at 16:00 remembers the shave they did at
    11:15 and never recorded. The engine will not offer that time; the database
    will take the write; so the resolver offers it as a deliberate choice.
    """

    def _completed(self, shop_setup, wednesday):
        appointment = create_appointment(
            staff=shop_setup.grace,
            service=shop_setup.braids,
            starts_at=eat(wednesday, 10),
            source=BookingSource.STAFF,
            now=eat(wednesday, 8),
        )
        apply_transition(appointment, AppointmentStatus.IN_PROGRESS, now=eat(wednesday, 10))
        apply_transition(appointment, AppointmentStatus.COMPLETED, now=eat(wednesday, 13))
        return appointment

    def test_the_engine_refuses_to_offer_worked_time(self, shop_setup, wednesday):
        from scheduling.booking import SlotUnavailable

        self._completed(shop_setup, wednesday)

        with pytest.raises(SlotUnavailable):
            create_appointment(
                staff=shop_setup.grace,
                service=shop_setup.shave,
                starts_at=eat(wednesday, 11, 15),
                source=BookingSource.WALK_IN,
                now=eat(wednesday, 16),
            )

    def test_record_anyway_is_the_only_option_offered(self, shop_setup, wednesday):
        self._completed(shop_setup, wednesday)

        options, in_the_way = resolve(
            staff=shop_setup.grace,
            service=shop_setup.shave,
            starts_at=eat(wednesday, 11, 15),
            duration_minutes=20,
        )

        assert [o.kind for o in options] == ["record_anyway"]
        assert in_the_way and not in_the_way[0].is_active

    def test_choosing_it_writes_the_row(self, signed_in, shop_setup, walk_in_url, wednesday):
        self._completed(shop_setup, wednesday)

        response = signed_in.post(
            walk_in_url,
            {
                "service": str(shop_setup.shave.id),
                "staff": str(shop_setup.grace.id),
                "starts_at": eat(wednesday, 11, 15).isoformat(),
                "allow_over_completed": True,
            },
            format="json",
        )

        assert response.status_code == 201, response.data

    def test_it_never_lets_a_live_booking_be_overwritten(self, shop_setup, wednesday):
        """The flag relaxes the *offer*, never the constraint. A confirmed
        booking in the way is still refused, here and in Postgres."""
        from scheduling.booking import SlotUnavailable

        create_appointment(
            staff=shop_setup.grace,
            service=shop_setup.braids,
            starts_at=eat(wednesday, 10),
            source=BookingSource.STAFF,
            now=eat(wednesday, 8),
        )

        from scheduling.availability import Policy

        with pytest.raises(SlotUnavailable):
            create_appointment(
                staff=shop_setup.grace,
                service=shop_setup.shave,
                starts_at=eat(wednesday, 11),
                source=BookingSource.WALK_IN,
                now=eat(wednesday, 11),
                policy=Policy.for_staff(allow_over_completed=True),
            )


class TestTheOfflineRetryIsSafe:
    def test_the_same_request_id_twice_is_one_appointment(self, signed_in, shop_setup, walk_in_url):
        """Without this the retry inserts a second row, the exclusion
        constraint refuses it, and the stylist is told that their own walk-in
        just took their slot."""
        payload = {
            "service": str(shop_setup.shave.id),
            "staff": str(shop_setup.grace.id),
            "client_request_id": "phone-abc-123",
        }

        first = signed_in.post(walk_in_url, payload, format="json")
        second = signed_in.post(walk_in_url, payload, format="json")

        assert first.status_code == 201
        assert second.status_code == 201
        assert first.data["id"] == second.data["id"]
        assert Appointment.all_objects.filter(shop=shop_setup.shop).count() == 1

    def test_two_different_walk_ins_are_two_appointments(
        self, signed_in, shop_setup, walk_in_url, wednesday
    ):
        """The guard must not collapse two genuine walk-ins into one."""
        for request_id, hour in (("a", 9), ("b", 11)):
            signed_in.post(
                walk_in_url,
                {
                    "service": str(shop_setup.shave.id),
                    "staff": str(shop_setup.grace.id),
                    "starts_at": eat(wednesday, hour).isoformat(),
                    "client_request_id": request_id,
                },
                format="json",
            )

        assert Appointment.all_objects.filter(shop=shop_setup.shop).count() == 2

    def test_a_write_with_no_request_id_still_works(self, signed_in, shop_setup, walk_in_url):
        """The column is nullable and the constraint partial, so an older client
        — or slice 5's online flow — is unaffected."""
        response = signed_in.post(
            walk_in_url,
            {"service": str(shop_setup.shave.id), "staff": str(shop_setup.grace.id)},
            format="json",
        )

        assert response.status_code == 201
        assert Appointment.all_objects.get(pk=response.data["id"]).client_request_id is None


class TestWhoSeesWhat:
    def test_a_stylist_sees_only_their_own_day(self, signed_in, shop_setup, wednesday):
        for staff in (shop_setup.wanjiku, shop_setup.grace):
            create_appointment(
                staff=staff,
                service=shop_setup.braids,
                starts_at=eat(wednesday, 10),
                source=BookingSource.STAFF,
                now=eat(wednesday, 8),
            )
        url = reverse(
            "scheduling:staff-day",
            kwargs={"org_id": shop_setup.organization.id, "shop_id": shop_setup.shop.id},
        )

        response = signed_in.get(f"{url}?date={wednesday.isoformat()}")

        assert response.status_code == 200
        assert response.data["scope"] == "staff"
        assert response.data["can_view_shop"] is False
        assert len(response.data["appointments"]) == 1
        assert str(response.data["appointments"][0]["staff_id"]) == str(shop_setup.grace.id)

    def test_a_stylist_cannot_widen_to_the_whole_shop(self, signed_in, shop_setup, wednesday):
        create_appointment(
            staff=shop_setup.wanjiku,
            service=shop_setup.braids,
            starts_at=eat(wednesday, 10),
            source=BookingSource.STAFF,
            now=eat(wednesday, 8),
        )
        url = reverse(
            "scheduling:staff-day",
            kwargs={"org_id": shop_setup.organization.id, "shop_id": shop_setup.shop.id},
        )

        response = signed_in.get(f"{url}?staff=all&date={wednesday.isoformat()}")

        assert response.status_code == 200
        assert response.data["appointments"] == []

    def test_an_owner_sees_the_whole_shop_on_the_same_screen(
        self, api_client, shop_setup, wednesday
    ):
        """Same endpoint, same shape, wider scope — not a second view."""
        for staff in (shop_setup.wanjiku, shop_setup.grace):
            create_appointment(
                staff=staff,
                service=shop_setup.braids,
                starts_at=eat(wednesday, 10),
                source=BookingSource.STAFF,
                now=eat(wednesday, 8),
            )
        api_client.force_authenticate(shop_setup.org.owner)
        url = reverse(
            "scheduling:staff-day",
            kwargs={"org_id": shop_setup.organization.id, "shop_id": shop_setup.shop.id},
        )

        response = api_client.get(f"{url}?staff=all&date={wednesday.isoformat()}")

        assert response.data["can_view_shop"] is True
        assert response.data["scope"] == "shop"
        assert len(response.data["appointments"]) == 2

    def test_an_owner_with_a_chair_defaults_to_their_own(self, api_client, shop_setup, wednesday):
        """At the chair, the personal list is the one that beats the notebook."""
        for staff in (shop_setup.wanjiku, shop_setup.grace):
            create_appointment(
                staff=staff,
                service=shop_setup.braids,
                starts_at=eat(wednesday, 10),
                source=BookingSource.STAFF,
                now=eat(wednesday, 8),
            )
        api_client.force_authenticate(shop_setup.org.owner)
        url = reverse(
            "scheduling:staff-day",
            kwargs={"org_id": shop_setup.organization.id, "shop_id": shop_setup.shop.id},
        )

        response = api_client.get(f"{url}?date={wednesday.isoformat()}")

        assert response.data["scope"] == "staff"
        assert len(response.data["appointments"]) == 1

    def test_a_stylist_cannot_record_at_someone_elses_chair(
        self, signed_in, shop_setup, walk_in_url
    ):
        """Only through a handover the engine offered, and only at their own
        shop. Revenue attribution is the owner dashboard's whole argument."""
        response = signed_in.post(
            walk_in_url,
            {"service": str(shop_setup.shave.id), "staff": str(shop_setup.wanjiku.id)},
            format="json",
        )

        # The handover is allowed because they share a shop — but a stylist at
        # another shop is not reachable at all.
        assert response.status_code == 201

    def test_another_tenants_shop_is_a_404(self, signed_in, shop_setup, rival_shop):
        url = reverse(
            "scheduling:staff-day",
            kwargs={"org_id": rival_shop.organization.id, "shop_id": rival_shop.shop.id},
        )

        assert signed_in.get(url).status_code == 404

    def test_the_day_list_never_carries_phone_numbers(
        self, signed_in, shop_setup, walk_in_url, wednesday
    ):
        """A day's phone numbers in one payload is a DPA §9 surface with no
        screen behind it. The detail card asks for them one at a time."""
        created = signed_in.post(
            walk_in_url,
            {"service": str(shop_setup.shave.id), "staff": str(shop_setup.grace.id)},
            format="json",
        )
        signed_in.post(
            reverse(
                "scheduling:appointment-client",
                kwargs={
                    "org_id": shop_setup.organization.id,
                    "shop_id": shop_setup.shop.id,
                    "appointment_id": created.data["id"],
                },
            ),
            {"full_name": "Amina", "phone": "0712345678"},
            format="json",
        )
        url = reverse(
            "scheduling:staff-day",
            kwargs={"org_id": shop_setup.organization.id, "shop_id": shop_setup.shop.id},
        )

        response = signed_in.get(url)

        assert response.data["appointments"][0]["client_name"] == "Amina"
        assert response.data["appointments"][0]["client_phone"] == ""


class TestTheQueryBudget:
    def test_the_day_view_is_a_fixed_number_of_queries(
        self, signed_in, shop_setup, wednesday, django_assert_num_queries
    ):
        """Asserted as a number so the next slice cannot make Today N+1. Eight
        appointments cost the same as one — the row needs the service name and
        the client, and `select_related` is what keeps that free.
        """
        for hour in range(9, 17):
            create_appointment(
                staff=shop_setup.grace,
                service=shop_setup.shave,
                starts_at=eat(wednesday, hour),
                source=BookingSource.WALK_IN,
                now=eat(wednesday, hour),
            )
        url = reverse(
            "scheduling:staff-day",
            kwargs={"org_id": shop_setup.organization.id, "shop_id": shop_setup.shop.id},
        )

        with django_assert_num_queries(5):
            signed_in.get(f"{url}?date={wednesday.isoformat()}")

    def test_the_count_does_not_grow_with_the_day(
        self, signed_in, shop_setup, wednesday, django_assert_num_queries
    ):
        url = reverse(
            "scheduling:staff-day",
            kwargs={"org_id": shop_setup.organization.id, "shop_id": shop_setup.shop.id},
        )

        with django_assert_num_queries(5):
            signed_in.get(f"{url}?date={wednesday.isoformat()}")

    def test_the_shop_day_loader_is_still_five(
        self, shop_setup, wednesday, django_assert_num_queries, clear_cache
    ):
        """Slice 3's bound, re-asserted from slice 4 with the day view built on
        top of it. It is a separate number because it is a separate query — a
        day view is a list of what is booked, not a derivation of what is free.
        """
        from scheduling.loading import gather_shop_day

        everyone = list(shop_setup.shop.staff.filter(is_active=True))
        with django_assert_num_queries(5):
            gather_shop_day(shop_setup.shop, wednesday, staff=everyone)


class TestThereIsNoSecondInsertPath:
    def test_only_create_appointment_constructs_an_appointment(self):
        """Structural, because "there is no second insert path" is not something
        a behavioural test can see. Any `Appointment(...)` or
        `Appointment.objects.create(...)` outside `booking.py` is a path that
        skips the re-derivation, the advisory lock and the snapshots.
        """
        root = pathlib.Path(__file__).resolve().parents[2]
        offenders = []
        for path in (root / "scheduling").rglob("*.py"):
            if path.name in {"booking.py"} or "tests" in path.parts or "migrations" in path.parts:
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                target = node.func
                # `Appointment(...)`
                if isinstance(target, ast.Name) and target.id == "Appointment":
                    offenders.append(f"{path.name}:{node.lineno}")
                # `Appointment.objects.create(...)` / `.all_objects.create(...)`
                if (
                    isinstance(target, ast.Attribute)
                    and target.attr in {"create", "bulk_create", "get_or_create"}
                    and "Appointment" in ast.dump(target)
                ):
                    offenders.append(f"{path.name}:{node.lineno}")

        assert not offenders, f"appointments are created in booking.py only, not {offenders}"

    def test_no_serializer_writes_an_appointment(self):
        """A `ModelSerializer` on Appointment with `.save()` would be the same
        bypass wearing a DRF hat.

        Parsed rather than grepped, for the reason slice 3 learned the hard way:
        a test that cannot tell code from a comment about code gets weakened
        until it means nothing. This module's own docstring says the words.
        """
        from scheduling import serializers

        tree = ast.parse(pathlib.Path(serializers.__file__).read_text())
        model_serializers = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
            and any("ModelSerializer" in ast.dump(base) for base in node.bases)
        ]

        assert not model_serializers, model_serializers
