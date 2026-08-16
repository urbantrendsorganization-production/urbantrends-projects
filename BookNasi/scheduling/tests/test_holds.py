"""LOAD-BEARING. The hold: it takes the slot, and it gives it back.

Slice 5 ships the whole booking flow with no payment in it, which makes the
hold's lifecycle the entire thing that can go wrong. Two failures are
unrecoverable in a way a client can see:

1. **A hold that never releases** is a slot nobody can ever book again. Not a
   double-booking, but indistinguishable from one to the client who cannot have
   it, and invisible to the shop until somebody complains.
2. **A hold that releases while the client is paying** takes a slot from
   somebody who has already been charged. Slice 6 makes that a refund and a
   support call — the `slotLost` state CLAUDE.md §12 still has open.

So release is tested from both ends: the scheduled task, the Beat sweep, an
early resolution, and a task that fires when it should not.

Celery runs eagerly here (`CELERY_TASK_ALWAYS_EAGER`), so `apply_async` executes
inline. That makes the *scheduling* observable but not the *timing* — the tests
that care about expiry call the task directly with a moved clock, which is the
same trick the availability engine uses with its injected `now`.
"""

import threading
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.db import connections
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from clients.models import Client
from scheduling import tasks
from scheduling.abuse import (
    ABANDONED_COOLDOWN,
    MAX_ABANDONED_HOLDS,
    MAX_HOLDS_PER_PHONE_PER_DAY,
    MAX_OPEN_HOLDS_PER_STAFF,
    HoldRefused,
    check_can_hold,
)
from scheduling.booking import SlotUnavailable
from scheduling.holds import (
    ServiceNotPubliclyBookable,
    client_for_phone,
    create_hold,
    release_hold,
)
from scheduling.models import Appointment
from scheduling.statuses import AppointmentStatus, BookingSource
from scheduling.tests.conftest import WEDNESDAY, eat
from scheduling.transitions import apply_transition

pytestmark = [pytest.mark.django_db, pytest.mark.loadbearing]


@pytest.fixture(autouse=True)
def eager_celery(settings):
    """`apply_async` runs inline, so a hold's release task is observable without
    a broker. Timing is asserted by calling the task with a moved clock, never
    by waiting."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True


def hold(shop_setup, when=None, *, phone="0712345678", staff=None, service=None, now=None):
    when = when or eat(WEDNESDAY, 10)
    return create_hold(
        shop=shop_setup.shop,
        service=service or shop_setup.braids,
        staff=staff or shop_setup.wanjiku,
        starts_at=when,
        phone=phone,
        now=now or (when - timedelta(hours=2)),
    )


class TestTheHoldTakesTheSlot:
    def test_it_creates_a_pending_payment_appointment(self, shop_setup, wednesday):
        appointment = hold(shop_setup, eat(wednesday, 10))

        assert appointment.status == AppointmentStatus.PENDING_PAYMENT
        assert appointment.source == BookingSource.ONLINE
        assert appointment.deposit_snapshot == shop_setup.braids.deposit_amount

    def test_the_expiry_comes_from_the_shop(self, shop_setup, wednesday):
        """A `pending_payment` row *is* a hold, so it is never written without
        one — a null expiry would be a row the sweep has to guess about."""
        now = eat(wednesday, 8)
        appointment = create_hold(
            shop=shop_setup.shop,
            service=shop_setup.braids,
            staff=shop_setup.wanjiku,
            starts_at=eat(wednesday, 10),
            phone="0712345678",
            now=now,
        )

        assert appointment.hold_expires_at == now + timedelta(
            minutes=shop_setup.shop.hold_ttl_minutes
        )

    def test_the_slot_is_genuinely_gone_while_held(self, shop_setup, wednesday):
        """The point of the hold. `pending_payment` is inside ACTIVE_STATUSES,
        so the exclusion constraint defends it exactly as a confirmed booking
        would — a client off finding their M-Pesa PIN cannot lose the slot to
        the next visitor."""
        hold(shop_setup, eat(wednesday, 10))

        with pytest.raises(SlotUnavailable):
            hold(shop_setup, eat(wednesday, 10), phone="0722000002")

    def test_a_release_task_is_scheduled_and_remembered(self, shop_setup, wednesday):
        appointment = hold(shop_setup, eat(wednesday, 10))

        assert appointment.hold_release_task_id


class TestExpiryReleasesTheSlot:
    def test_the_scheduled_task_releases_it(self, shop_setup, wednesday):
        appointment = hold(shop_setup, eat(wednesday, 10))

        # Move past the expiry rather than waiting for it.
        Appointment.all_objects.filter(pk=appointment.pk).update(
            hold_expires_at=timezone.now() - timedelta(seconds=1)
        )
        result = tasks.release_expired_hold(str(appointment.pk))

        appointment.refresh_from_db()
        assert result == "released"
        assert appointment.status == AppointmentStatus.CANCELLED
        assert appointment.hold_released_at is not None

    def test_the_released_slot_is_offered_again(self, shop_setup, wednesday, clear_cache):
        """The assertion that matters. Not just that the row changed status —
        that the engine puts the time back on the list a client can book."""
        from scheduling.availability import Policy, derive_slots
        from scheduling.cache import facts_for_staff_day

        when = eat(wednesday, 10)
        appointment = hold(shop_setup, when)

        def offered():
            facts = facts_for_staff_day(shop_setup.wanjiku, wednesday)
            slots = derive_slots(
                facts,
                duration_minutes=240,
                policy=Policy.for_public(shop_setup.shop),
                now=eat(wednesday, 8),
            )
            return [slot.starts_at for slot in slots]

        assert when not in offered()

        Appointment.all_objects.filter(pk=appointment.pk).update(
            hold_expires_at=timezone.now() - timedelta(seconds=1)
        )
        tasks.release_expired_hold(str(appointment.pk))

        assert when in offered()

    def test_the_sweep_catches_what_the_task_missed(self, shop_setup, wednesday):
        """The backstop. A lost broker, a redeployed worker, a dropped task id —
        all of them cost a minute here instead of a permanently held slot."""
        appointment = hold(shop_setup, eat(wednesday, 10))
        Appointment.all_objects.filter(pk=appointment.pk).update(
            hold_expires_at=timezone.now() - timedelta(seconds=30),
            # The scheduled task is gone, as if the queue had been lost.
            hold_release_task_id=None,
        )

        assert tasks.sweep_expired_holds() == 1

        appointment.refresh_from_db()
        assert appointment.status == AppointmentStatus.CANCELLED

    def test_the_sweep_leaves_live_holds_alone(self, shop_setup, wednesday):
        """Releasing a hold that has not expired takes a slot from a client who
        is mid-payment. Worse than never releasing it."""
        appointment = hold(shop_setup, eat(wednesday, 10))

        assert tasks.sweep_expired_holds() == 0

        appointment.refresh_from_db()
        assert appointment.status == AppointmentStatus.PENDING_PAYMENT

    def test_a_task_that_fires_early_does_nothing(self, shop_setup, wednesday):
        """Clock skew between web and worker, or a re-delivery. Leaving it is
        correct — the sweep takes it a minute after it genuinely expires."""
        appointment = hold(shop_setup, eat(wednesday, 10))

        assert tasks.release_expired_hold(str(appointment.pk)) == "not-yet"

        appointment.refresh_from_db()
        assert appointment.status == AppointmentStatus.PENDING_PAYMENT

    def test_releasing_twice_is_harmless(self, shop_setup, wednesday):
        """The eta task and the sweep can both arrive. So can a payment
        callback a second before either."""
        appointment = hold(shop_setup, eat(wednesday, 10))
        Appointment.all_objects.filter(pk=appointment.pk).update(
            hold_expires_at=timezone.now() - timedelta(seconds=1)
        )

        assert tasks.release_expired_hold(str(appointment.pk)) == "released"
        appointment.refresh_from_db()
        assert tasks.release_expired_hold(str(appointment.pk)) == "resolved"

    def test_a_deleted_appointment_does_not_crash_the_worker(self, shop_setup, wednesday):
        appointment = hold(shop_setup, eat(wednesday, 10))
        pk = str(appointment.pk)
        appointment.delete()

        assert tasks.release_expired_hold(pk) == "gone"


class TestResolvingEarlyCancelsTheTask:
    def test_leaving_pending_payment_revokes_it(self, shop_setup, wednesday, monkeypatch):
        """The task id is cleared and a revoke is attempted. Revoking is an
        optimisation — the task re-checks before acting — so what is asserted
        here is that the intent is expressed, not that the broker obeyed."""
        revoked = []
        from config.celery import app

        monkeypatch.setattr(app.control, "revoke", lambda task_id: revoked.append(task_id))

        appointment = hold(shop_setup, eat(wednesday, 10))
        task_id = appointment.hold_release_task_id
        assert task_id

        apply_transition(appointment, AppointmentStatus.CANCELLED)

        assert revoked == [task_id]
        appointment.refresh_from_db()
        assert appointment.hold_release_task_id is None

    def test_a_broker_that_refuses_the_revoke_does_not_fail_the_booking(
        self, shop_setup, wednesday, monkeypatch
    ):
        from config.celery import app

        def boom(task_id):
            raise ConnectionError("no broker")

        monkeypatch.setattr(app.control, "revoke", boom)
        appointment = hold(shop_setup, eat(wednesday, 10))

        apply_transition(appointment, AppointmentStatus.CANCELLED)

        appointment.refresh_from_db()
        assert appointment.status == AppointmentStatus.CANCELLED

    def test_a_client_cancelling_is_not_recorded_as_an_abandonment(self, shop_setup, wednesday):
        """Penalising the cancel button teaches people to close the tab instead,
        and a closed tab is what actually costs the shop a slot."""
        appointment = hold(shop_setup, eat(wednesday, 10))

        release_hold(appointment, expired=False)

        appointment.refresh_from_db()
        assert appointment.status == AppointmentStatus.CANCELLED
        assert appointment.hold_released_at is None


class TestClientIdentity:
    def test_a_returning_phone_matches_the_existing_client(self, shop_setup, wednesday):
        """CLAUDE.md §3 and §12. No account and no OTP, so the number is the
        identity — and a second record would silently split a regular's history
        in two."""
        first = hold(shop_setup, eat(wednesday, 9), phone="0712345678")
        release_hold(first, expired=False)
        second = hold(shop_setup, eat(wednesday, 14), phone="0712345678")

        assert first.client_id == second.client_id
        assert Client.objects.for_org(shop_setup.organization).count() == 1

    def test_the_same_number_written_differently_is_one_person(self, shop_setup, wednesday):
        """`0712345678` on one visit and `+254 712 345 678` on the next. The
        normalisation happens before the lookup, not only inside `save()`."""
        first = hold(shop_setup, eat(wednesday, 9), phone="0712345678")
        release_hold(first, expired=False)
        second = hold(shop_setup, eat(wednesday, 14), phone="+254 712 345 678")

        assert first.client_id == second.client_id

    def test_a_returning_client_keeps_the_name_the_shop_typed(self, shop_setup):
        """The booking form does not ask for a name, so matching must not
        overwrite one a staff member entered with a blank."""
        Client.objects.create(
            organization=shop_setup.organization, phone="+254712345678", full_name="Amina"
        )

        client = client_for_phone(shop_setup.organization, "0712345678")

        assert client.full_name == "Amina"

    def test_the_same_number_at_another_organization_is_a_separate_record(
        self, shop_setup, rival_shop
    ):
        """CLAUDE.md §9: two unrelated salons are two controllers. One shop's
        client list is not the other's."""
        client_for_phone(shop_setup.organization, "0712345678")
        client_for_phone(rival_shop.organization, "0712345678")

        assert Client.objects.for_org(shop_setup.organization).count() == 1
        assert Client.objects.for_org(rival_shop.organization).count() == 1


class TestDepositFreeServicesAreUnreachable:
    def test_the_flow_cannot_hold_one(self, shop_setup, wednesday):
        """CLAUDE.md §5, at the write path. Slice 2 keeps it off the public
        list; this is the request that did not come from the booking page."""
        assert shop_setup.shave.deposit_amount == 0

        with pytest.raises(ServiceNotPubliclyBookable):
            hold(shop_setup, eat(wednesday, 10), service=shop_setup.shave)

    def test_an_unlisted_service_cannot_be_held_either(self, shop_setup, wednesday):
        """Bookability is `active AND listed AND carries a deposit` — the
        owner's intent is necessary and not sufficient, and the reverse is also
        true."""
        service = shop_setup.braids
        service.is_publicly_listed = False
        service.save()

        with pytest.raises(ServiceNotPubliclyBookable):
            hold(shop_setup, eat(wednesday, 10), service=service)

    def test_a_deactivated_service_cannot_be_held(self, shop_setup, wednesday):
        service = shop_setup.braids
        service.is_active = False
        service.save()

        with pytest.raises(ServiceNotPubliclyBookable):
            hold(shop_setup, eat(wednesday, 10), service=service)


class TestAbuseLimits:
    """The price of the no-OTP decision, asserted. See `scheduling/abuse.py`."""

    def test_one_open_hold_per_number_per_stylist(self, shop_setup, wednesday):
        assert MAX_OPEN_HOLDS_PER_STAFF == 1
        # One `now` for both, because a hold three minutes old has expired and
        # the limit is about *open* holds. Two different clocks would make this
        # pass for the wrong reason.
        now = eat(wednesday, 8)
        hold(shop_setup, eat(wednesday, 9), now=now)

        with pytest.raises(HoldRefused) as caught:
            hold(shop_setup, eat(wednesday, 14), now=now)

        assert caught.value.reason == "open_hold"

    def test_a_parent_can_hold_two_stylists_for_two_children(self, shop_setup, wednesday):
        """The case the ceiling is scoped per stylist to protect.

        One phone, two children, two chairs at the same time. This is what a
        Saturday morning at a salon looks like, and a one-hold-per-number
        ceiling refuses it outright — at the confirm step, with "you already
        have a slot held", and no remedy but to abandon a wanted booking.
        """
        now = eat(wednesday, 8)

        first = hold(shop_setup, eat(wednesday, 9), now=now, staff=shop_setup.wanjiku)
        second = hold(shop_setup, eat(wednesday, 9), now=now, staff=shop_setup.grace)

        assert first.staff_id != second.staff_id
        assert first.client_id == second.client_id, "one phone is one client"

    def test_the_refusal_names_the_stylist_it_is_about(self, shop_setup, wednesday):
        """Scoping the ceiling makes the message ambiguous unless it says who.
        "You already have a slot held" reads as a refusal of the whole booking;
        the actual remedy is to pick a different stylist."""
        now = eat(wednesday, 8)
        hold(shop_setup, eat(wednesday, 9), now=now, staff=shop_setup.wanjiku)

        with pytest.raises(HoldRefused) as caught:
            hold(shop_setup, eat(wednesday, 14), now=now, staff=shop_setup.wanjiku)

        assert "Wanjiku" in str(caught.value)

    def test_two_slots_with_the_same_stylist_still_wait_for_the_first_to_resolve(
        self, shop_setup, wednesday
    ):
        """Documented rather than fixed, because slice 6 fixes it.

        Two children with the *same* stylist on one number is still refused
        while a hold is open. Once there is a payment the first hold leaves
        `pending_payment` within seconds of the PIN and the second booking
        proceeds, so this is a sequencing constraint for as long as slice 5
        stands alone — not a permanent one. Loosening it further would give up
        the only thing the open-hold ceiling actually prevents: one number
        sitting on two of one stylist's slots at once.
        """
        now = eat(wednesday, 8)
        first = hold(shop_setup, eat(wednesday, 9), now=now, staff=shop_setup.wanjiku)

        with pytest.raises(HoldRefused):
            hold(shop_setup, eat(wednesday, 14), now=now, staff=shop_setup.wanjiku)

        # The slice 6 shape, simulated with a direct write because the edge does
        # not exist yet: `STAFF_TRANSITIONS` has no pending_payment -> confirmed,
        # deliberately. Confirming a hold is what a paid callback does, not
        # something a staff member may do — granting it to staff would hand out
        # the deposit-free booking CLAUDE.md §5 exists to prevent. Slice 6 adds
        # that transition to a separate system table.
        Appointment.objects.unscoped().filter(pk=first.pk).update(
            status=AppointmentStatus.CONFIRMED, hold_expires_at=None
        )

        assert hold(shop_setup, eat(wednesday, 14), now=now, staff=shop_setup.wanjiku)

    def test_cancelling_frees_the_number_immediately(self, shop_setup, wednesday):
        """Otherwise the limit becomes a three-minute lockout on the client's
        own mistake."""
        now = eat(wednesday, 8)
        first = hold(shop_setup, eat(wednesday, 9), now=now)
        release_hold(first, expired=False)

        assert hold(shop_setup, eat(wednesday, 14), now=now)

    def test_a_daily_ceiling(self, shop_setup, wednesday):
        client = client_for_phone(shop_setup.organization, "0712345678")
        for index in range(MAX_HOLDS_PER_PHONE_PER_DAY):
            Appointment.objects.create(
                shop=shop_setup.shop,
                staff=shop_setup.wanjiku,
                service=shop_setup.braids,
                client=client,
                # Spaced a week apart so they cannot collide with each other;
                # the limit is about the number, not the calendar.
                time_range=(
                    eat(wednesday, 9) + timedelta(days=index * 7),
                    eat(wednesday, 10) + timedelta(days=index * 7),
                ),
                status=AppointmentStatus.CANCELLED,
                source=BookingSource.ONLINE,
                price_snapshot=3500,
                deposit_snapshot=875,
                duration_snapshot=60,
            )

        with pytest.raises(HoldRefused) as caught:
            check_can_hold(client)

        assert caught.value.reason == "daily_limit"
        assert caught.value.retry_after

    def test_repeated_abandonment_earns_a_cooldown(self, shop_setup, wednesday):
        """Expiries only. Three in an hour and the number waits."""
        client = client_for_phone(shop_setup.organization, "0712345678")
        now = timezone.now()
        for index in range(MAX_ABANDONED_HOLDS):
            Appointment.objects.create(
                shop=shop_setup.shop,
                staff=shop_setup.wanjiku,
                service=shop_setup.braids,
                client=client,
                time_range=(
                    eat(wednesday, 9) + timedelta(days=index * 7),
                    eat(wednesday, 10) + timedelta(days=index * 7),
                ),
                status=AppointmentStatus.CANCELLED,
                source=BookingSource.ONLINE,
                price_snapshot=3500,
                deposit_snapshot=875,
                duration_snapshot=60,
                hold_released_at=now - timedelta(minutes=index),
            )

        with pytest.raises(HoldRefused) as caught:
            check_can_hold(client, now=now)

        assert caught.value.reason == "abandonment_cooldown"

    def test_the_cooldown_shortens_rather_than_resetting_on_retry(self, shop_setup, wednesday):
        """A cooldown that restarts every time you try is a permanent ban with
        extra steps."""
        client = client_for_phone(shop_setup.organization, "0712345678")
        now = timezone.now()
        for index in range(MAX_ABANDONED_HOLDS):
            Appointment.objects.create(
                shop=shop_setup.shop,
                staff=shop_setup.wanjiku,
                service=shop_setup.braids,
                client=client,
                time_range=(
                    eat(wednesday, 9) + timedelta(days=index * 7),
                    eat(wednesday, 10) + timedelta(days=index * 7),
                ),
                status=AppointmentStatus.CANCELLED,
                source=BookingSource.ONLINE,
                price_snapshot=3500,
                deposit_snapshot=875,
                duration_snapshot=60,
                hold_released_at=now - timedelta(minutes=50 + index),
            )

        # The oldest of the three is 52 minutes old, so the cooldown has passed.
        check_can_hold(client, now=now)
        assert ABANDONED_COOLDOWN == timedelta(minutes=30)

    def test_one_shops_abandonments_do_not_lock_another(self, shop_setup, rival_shop):
        """Org-scoped exactly as the client record is."""
        mine = client_for_phone(shop_setup.organization, "0712345678")
        theirs = client_for_phone(rival_shop.organization, "0712345678")
        now = timezone.now()
        Appointment.objects.create(
            shop=shop_setup.shop,
            staff=shop_setup.wanjiku,
            service=shop_setup.braids,
            client=mine,
            time_range=(eat(WEDNESDAY, 9), eat(WEDNESDAY, 10)),
            status=AppointmentStatus.PENDING_PAYMENT,
            source=BookingSource.ONLINE,
            price_snapshot=3500,
            deposit_snapshot=875,
            duration_snapshot=60,
            hold_expires_at=now + timedelta(minutes=3),
        )

        with pytest.raises(HoldRefused):
            check_can_hold(mine, now=now)
        check_can_hold(theirs, now=now)  # unaffected


class TestTheHoldEndpoints:
    def test_the_confirm_step_is_one_post(self, api_client, shop_setup, wednesday):
        url = reverse("public_api:hold-create", kwargs={"slug": shop_setup.shop.slug})

        response = api_client.post(
            url,
            {
                "service": str(shop_setup.braids.id),
                "staff": str(shop_setup.wanjiku.id),
                "starts_at": eat(wednesday, 10).isoformat(),
                "phone": "0712345678",
            },
            format="json",
        )

        assert response.status_code == 201, response.data
        assert response.data["status"] == "pending_payment"
        assert response.data["deposit_kes"] == shop_setup.braids.deposit_amount
        assert response.data["balance_kes"] == 3500 - shop_setup.braids.deposit_amount
        assert response.data["seconds_remaining"] > 0

    def test_a_deposit_free_service_is_refused_with_400(self, api_client, shop_setup, wednesday):
        url = reverse("public_api:hold-create", kwargs={"slug": shop_setup.shop.slug})

        response = api_client.post(
            url,
            {
                "service": str(shop_setup.shave.id),
                "staff": str(shop_setup.wanjiku.id),
                "starts_at": eat(wednesday, 10).isoformat(),
                "phone": "0712345678",
            },
            format="json",
        )

        assert response.status_code == 400

    def test_a_bad_number_is_refused_before_anything_is_written(
        self, api_client, shop_setup, wednesday
    ):
        url = reverse("public_api:hold-create", kwargs={"slug": shop_setup.shop.slug})

        response = api_client.post(
            url,
            {
                "service": str(shop_setup.braids.id),
                "staff": str(shop_setup.wanjiku.id),
                "starts_at": eat(wednesday, 10).isoformat(),
                "phone": "0812345678",
            },
            format="json",
        )

        assert response.status_code == 400
        assert not Appointment.all_objects.exists()

    def test_a_taken_slot_is_409_and_never_a_500(self, api_client, shop_setup, wednesday):
        hold(shop_setup, eat(wednesday, 10))
        url = reverse("public_api:hold-create", kwargs={"slug": shop_setup.shop.slug})

        response = api_client.post(
            url,
            {
                "service": str(shop_setup.braids.id),
                "staff": str(shop_setup.wanjiku.id),
                "starts_at": eat(wednesday, 10).isoformat(),
                "phone": "0722000002",
            },
            format="json",
        )

        assert response.status_code == 409
        assert response.data["reason"] in {"SlotTaken", "SlotUnavailable"}

    def test_a_throttled_number_is_429_with_a_retry_hint(self, api_client, shop_setup, wednesday):
        hold(shop_setup, eat(wednesday, 9))
        url = reverse("public_api:hold-create", kwargs={"slug": shop_setup.shop.slug})

        response = api_client.post(
            url,
            {
                "service": str(shop_setup.braids.id),
                "staff": str(shop_setup.wanjiku.id),
                "starts_at": eat(wednesday, 14).isoformat(),
                "phone": "0712345678",
            },
            format="json",
        )

        assert response.status_code == 429
        assert response.data["reason"] == "open_hold"

    def test_the_countdown_can_be_polled_by_id(self, api_client, shop_setup, wednesday):
        appointment = hold(shop_setup, eat(wednesday, 10))
        url = reverse("public_api:hold-detail", kwargs={"hold_id": appointment.pk})

        response = api_client.get(url)

        assert response.status_code == 200
        assert str(response.data["id"]) == str(appointment.pk)
        assert response.data["seconds_remaining"] > 0

    def test_the_hold_response_leaks_nothing_about_the_client(
        self, api_client, shop_setup, wednesday
    ):
        """Unauthenticated and keyed by an unguessable id, so the field set is
        the whole of the protection."""
        appointment = hold(shop_setup, eat(wednesday, 10))
        url = reverse("public_api:hold-detail", kwargs={"hold_id": appointment.pk})

        body = api_client.get(url).data

        assert set(body) == {
            "id",
            "status",
            "starts_at",
            "ends_at",
            "local_time",
            "hold_expires_at",
            "seconds_remaining",
            "staff_name",
            "service_name",
            "price_kes",
            "deposit_kes",
            "balance_kes",
            # Slice 11. What this booking has actually been credited — M-Pesa
            # and spent shop credit together — because `deposit_kes` is only
            # what is still owed to M-Pesa and reads zero when credit covered
            # the deposit outright, which made the paid screen say "KES 0
            # received". Safe to add to this allowlist on the same grounds as
            # the figures above it: it is money this caller has just handed
            # over against a service whose price is printed on the shop's
            # public page, and it says nothing about who they are. It is not a
            # credit *balance* — that stays on the token-gated manage view.
            "paid_kes",
            # slice 6. `payment` is the payment's own state plus the support
            # code — nothing about the client that the caller did not send.
            # `shop_phone` is already on the shop's public page header.
            "payment",
            "shop_phone",
            # The refund terms and the shop's name, for the booking page the
            # confirmation SMS links to. That page is reached by appointment id
            # from an SMS and has no shop object to read them from. All three
            # are already public on the shop's own page — CLAUDE.md §12.
            "shop_name",
            "refund_window_hours",
            "deposit_credit_days",
        }

    def test_the_payment_block_names_no_person(self, api_client, shop_setup, wednesday):
        """The STK screens read themselves out of `payment`, so its field set is
        as load-bearing as the outer one. In particular: no payer phone number.
        The client typed it, but this endpoint is unauthenticated and the id is
        the only thing standing between a guess and someone else's number."""
        from payments.stk import initiate_push

        appointment = hold(shop_setup, eat(wednesday, 10))
        initiate_push(appointment)
        url = reverse("public_api:hold-detail", kwargs={"hold_id": appointment.pk})

        payment = api_client.get(url).data["payment"]

        assert set(payment) == {
            "state",
            "amount_kes",
            "support_code",
            "mpesa_receipt",
            "push_outstanding",
            "message",
            "slot_lost",
        }

    def test_a_client_can_give_the_slot_back(self, api_client, shop_setup, wednesday):
        appointment = hold(shop_setup, eat(wednesday, 10))
        url = reverse("public_api:hold-release", kwargs={"hold_id": appointment.pk})

        response = api_client.post(url)

        assert response.status_code == 200
        appointment.refresh_from_db()
        assert appointment.status == AppointmentStatus.CANCELLED
        assert appointment.hold_released_at is None

    def test_a_walk_in_is_not_reachable_through_the_hold_endpoints(
        self, api_client, shop_setup, wednesday
    ):
        """`source=online` only. A staff-entered appointment id in this URL must
        not become a public read of the shop's day."""
        from scheduling.booking import create_appointment

        walk_in = create_appointment(
            staff=shop_setup.wanjiku,
            service=shop_setup.shave,
            starts_at=eat(wednesday, 11),
            source=BookingSource.WALK_IN,
            now=eat(wednesday, 11),
        )
        url = reverse("public_api:hold-detail", kwargs={"hold_id": walk_in.pk})

        assert api_client.get(url).status_code == 404


@pytest.mark.django_db(transaction=True)
class TestTwoClientsConfirmTheSameSlot:
    """LOAD-BEARING. The race the product exists to lose gracefully.

    `test_concurrency.py` proves the constraint arbitrates two simultaneous
    inserts. This proves the *public endpoint* turns the losing side into
    something a client on a phone can act on: one 201 with a live countdown, one
    409 that says the slot went, and never a 500.

    A 500 here is not a cosmetic failure. It is the moment two people both
    believe they have 10:00, and the one who saw a stack trace is the one who
    turns up. Real threads and real connections, for the same reason
    `test_concurrency.py` uses them: a mocked race only proves the mock agrees
    with the code.
    """

    def test_one_gets_the_hold_and_the_other_gets_a_clean_just_taken(self, shop_setup, wednesday):
        # Throttle counters live in the shared cache and are keyed by IP, which
        # both threads share. Cleared so a full-suite run cannot make this test
        # fail for a reason that has nothing to do with the race.
        cache.clear()

        url = reverse("public_api:hold-create", kwargs={"slug": shop_setup.shop.slug})
        when = eat(wednesday, 10)
        barrier = threading.Barrier(2)
        results = []

        def confirm(phone):
            client = APIClient()
            payload = {
                "service": str(shop_setup.braids.id),
                "staff": str(shop_setup.wanjiku.id),
                "starts_at": when.isoformat(),
                "phone": phone,
            }
            barrier.wait()  # line both taps up on the same instant
            try:
                response = client.post(url, payload, format="json")
                results.append((response.status_code, response.data))
            except Exception as exc:  # noqa: BLE001 — an escaped exception IS a 500
                results.append((500, exc))
            finally:
                connections.close_all()

        threads = [
            threading.Thread(target=confirm, args=(phone,))
            for phone in ("0722000011", "0722000012")
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        codes = sorted(code for code, _ in results)
        assert codes == [201, 409], results

        winner = next(body for code, body in results if code == 201)
        loser = next(body for code, body in results if code == 409)
        assert winner["seconds_remaining"] > 0
        # Either refusal is honest and both are 409: `SlotUnavailable` means the
        # re-derivation already saw the winner's row, `SlotTaken` means only the
        # constraint could tell them apart. Which one arrives depends on query
        # timing, so pinning either would make this test flaky for no gain.
        assert loser["reason"] in {"SlotTaken", "SlotUnavailable"}
        assert "detail" in loser, "the losing client needs a sentence, not a code"

    def test_exactly_one_row_exists_afterwards(self, shop_setup, wednesday):
        """The assertion the 409 is worthless without. A clean refusal on a slot
        that was in fact double-booked would be the worst of both."""
        cache.clear()

        url = reverse("public_api:hold-create", kwargs={"slug": shop_setup.shop.slug})
        when = eat(wednesday, 14)
        barrier = threading.Barrier(3)

        def confirm(phone):
            client = APIClient()
            barrier.wait()
            try:
                client.post(
                    url,
                    {
                        "service": str(shop_setup.braids.id),
                        "staff": str(shop_setup.wanjiku.id),
                        "starts_at": when.isoformat(),
                        "phone": phone,
                    },
                    format="json",
                )
            finally:
                connections.close_all()

        threads = [
            threading.Thread(target=confirm, args=(phone,))
            for phone in ("0722000021", "0722000022", "0722000023")
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        held = Appointment.all_objects.filter(
            staff=shop_setup.wanjiku, status=AppointmentStatus.PENDING_PAYMENT
        )
        assert held.count() == 1

    def test_the_loser_can_take_the_slot_the_moment_the_hold_expires(self, shop_setup, wednesday):
        """The two halves joined up. A client who lost the race is not told to
        come back tomorrow — the winner has minutes, not the day, and when the
        hold lapses the slot is offered again to whoever is still looking.
        """
        cache.clear()

        url = reverse("public_api:hold-create", kwargs={"slug": shop_setup.shop.slug})
        # 13:00, not 16:00: braids run four hours and the stylist finishes at
        # 18:00, so a later start is refused for a reason that has nothing to do
        # with the hold and would make this pass vacuously.
        when = eat(wednesday, 13)
        winner = create_hold(
            shop=shop_setup.shop,
            service=shop_setup.braids,
            staff=shop_setup.wanjiku,
            starts_at=when,
            phone="0722000031",
            now=timezone.now(),
        )

        client = APIClient()
        payload = {
            "service": str(shop_setup.braids.id),
            "staff": str(shop_setup.wanjiku.id),
            "starts_at": when.isoformat(),
            "phone": "0722000032",
        }
        assert client.post(url, payload, format="json").status_code == 409

        # Move past the expiry rather than waiting for it, as the other release
        # tests do — the task reads the real clock and compares it to the row.
        Appointment.all_objects.filter(pk=winner.pk).update(
            hold_expires_at=timezone.now() - timedelta(seconds=1)
        )
        assert tasks.release_expired_hold(str(winner.pk)) == "released"

        assert client.post(url, payload, format="json").status_code == 201
