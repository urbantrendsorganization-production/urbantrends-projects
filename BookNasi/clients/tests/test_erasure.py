"""Erasure removes the person and keeps the trade. CLAUDE.md §9.

Two failure modes, opposite in shape, and this file exists because both are
silent:

1. **An erasure that misses a copy.** The client row is blank, every screen
   shows nothing, and the phone number is still sitting on the payment rows —
   the table kept longest and the one nobody thinks of as personal data. The
   shop believes it complied. Nothing says otherwise until a regulator or a
   breach finds it.
2. **An erasure that takes too much.** A cascade would carry the appointments
   away, and with them the revenue figures, the no-show rate and the
   utilisation. One person exercising their rights silently rewrites somebody
   else's books, and the owner has no way to discover why last quarter changed.

So the assertions here are mostly about what is *still there* afterwards, which
is the half a scrub is most likely to get wrong in the exciting direction.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from clients import erasure
from clients.models import Client, ScrubReason

pytestmark = pytest.mark.loadbearing


@pytest.fixture
def booked(db, shop_setup, held):
    """A client with one paid booking, a manage token and some credit."""
    from payments.credit import Credit, CreditSource, CreditState
    from payments.stk import initiate_push
    from scheduling import manage_tokens

    initiate_push(held)
    held.refresh_from_db()
    client = held.client
    client.full_name = "Amina Wanjiru"
    client.notes = "Allergic to the blue dye"
    client.save()

    manage_tokens.issue(held)
    Credit.objects.create(
        shop=shop_setup.shop,
        client=client,
        amount_kes=900,
        remaining_kes=900,
        state=CreditState.OPEN,
        source=CreditSource.LATE_CANCELLATION,
        expires_at=timezone.now() + timedelta(days=60),
        reference="CR-ERASE-1",
    )
    return client


class TestThePersonIsGone:
    def test_the_name_and_number_and_notes_are_cleared(self, booked):
        erasure.erase(booked)

        booked.refresh_from_db()
        assert booked.full_name == ""
        assert booked.phone == ""
        assert booked.notes == ""

    def test_the_payer_number_on_the_payment_rows_goes_too(self, booked):
        """The copy most easily missed.

        `Payment.phone` is the number Safaricom pushed to, on the table kept
        longest, and an erasure that stopped at the client row would leave it
        there while every screen reported the person as gone.
        """
        from payments.models import Payment

        before = Payment.objects.unscoped().filter(appointment__client=booked)
        assert before.exclude(phone="").exists()

        erasure.erase(booked)

        assert (
            not Payment.objects.unscoped()
            .filter(appointment__client=booked)
            .exclude(phone="")
            .exists()
        )

    def test_every_manage_link_stops_working(self, booked):
        """A token is a session (§12). An erased person should not have one —
        and the page it opens would no longer carry their name, which makes a
        live link worse rather than better: a credential nobody can attribute.
        """
        from scheduling import manage_tokens

        appointment = booked.appointments.first()
        token = appointment.manage_token
        assert token

        erasure.erase(booked)

        with pytest.raises(manage_tokens.ManageTokenInvalid):
            manage_tokens.resolve(token)

    def test_it_is_marked_and_dated(self, booked):
        erasure.erase(booked, reason=ScrubReason.REQUESTED)

        booked.refresh_from_db()
        assert booked.is_erased
        assert booked.scrubbed_at is not None
        assert booked.scrub_reason == ScrubReason.REQUESTED


class TestTheTradeSurvives:
    def test_the_appointments_are_still_there(self, booked):
        """§9: soft-delete with a scrub, "not a cascade". A shop's revenue
        history is the shop's data, and a client cannot take it with them."""
        from scheduling.models import Appointment

        count = Appointment.objects.unscoped().filter(client=booked).count()
        assert count

        erasure.erase(booked)

        assert Appointment.objects.unscoped().filter(client=booked).count() == count

    def test_and_they_still_point_at_the_scrubbed_row(self, booked):
        """Not nulled, and this is the half §9 words carefully: erasure "must
        not orphan appointment records in a way that breaks reporting".

        Nulling the link would orphan them. The repeat-client rate groups
        visits by client, so an erased regular's eight visits would stop being
        one person's and the figure would move for a reason no owner could
        find. The row they point at holds no name, no number and no notes, so
        the grouping survives and the person does not.
        """
        from scheduling.models import Appointment

        erasure.erase(booked)

        appointment = Appointment.objects.unscoped().filter(client=booked).first()
        assert appointment is not None
        assert appointment.client_id == booked.pk
        assert appointment.client.full_name == ""

    def test_the_money_is_still_there(self, booked):
        from payments.models import Payment

        amounts = sorted(
            Payment.objects.unscoped()
            .filter(appointment__isnull=False)
            .values_list("amount", flat=True)
        )
        assert amounts

        erasure.erase(booked)

        assert (
            sorted(
                Payment.objects.unscoped()
                .filter(appointment__isnull=False)
                .values_list("amount", flat=True)
            )
            == amounts
        )

    def test_the_dashboard_still_counts_the_visit(self, booked, shop_setup):
        """The specific consequence of a cascade, asserted where it would show.

        Revenue, no-show rate and utilisation all read appointments. If erasure
        took them, an owner's figures would change with no event to explain it.
        """
        from scheduling.models import Appointment

        before = Appointment.objects.unscoped().filter(shop=shop_setup.shop).count()

        erasure.erase(booked)

        assert Appointment.objects.unscoped().filter(shop=shop_setup.shop).count() == before

    def test_the_row_itself_is_not_deleted(self, booked):
        erasure.erase(booked)

        assert Client.objects.unscoped().filter(pk=booked.pk).exists()


class TestCredit:
    def test_the_plan_names_the_amount_before_anything_happens(self, booked):
        """A confirm screen that had to guess at the number, or omit it, would
        be asking somebody to agree to something nobody had told them."""
        plan = erasure.plan_for(booked)

        assert plan.credit_kes == 900
        assert plan.appointments >= 1
        assert plan.already_erased is False

    def test_it_is_voided_with_its_own_reason(self, booked):
        """Not `CANCELLED`. The shop did not decide this and should not appear
        on its own books to have."""
        from payments.credit import Credit, CreditState

        erasure.erase(booked)

        credit = Credit.objects.unscoped().filter(client=booked).first()
        assert credit is not None
        assert credit.state == CreditState.VOIDED_ON_ERASURE
        assert credit.state != CreditState.CANCELLED

    def test_the_credit_row_survives_for_the_books(self, booked):
        from payments.credit import Credit

        before = Credit.objects.unscoped().count()

        erasure.erase(booked)

        assert Credit.objects.unscoped().count() == before

    def test_a_client_with_credit_can_actually_be_erased(self, booked):
        """`Credit.client` is still `PROTECT`, and that is not in the way.

        Worth its own test because it nearly was changed. `PROTECT` fires on a
        row deletion, and erasure never deletes a row — so a client holding an
        unspent balance was always erasable, and relaxing the foreign key would
        have given up a real guard against a hard delete in exchange for
        nothing.
        """
        erasure.erase(booked)

        booked.refresh_from_db()
        assert booked.is_erased


class TestIdempotence:
    def test_erasing_twice_is_not_an_error(self, booked):
        """Three callers can reach an already-scrubbed row — the owner's
        button, the retention sweep, and a re-run after a partial failure — and
        the second must not be an error somebody has to interpret."""
        erasure.erase(booked)
        first = Client.objects.unscoped().get(pk=booked.pk).scrubbed_at

        erasure.erase(Client.objects.unscoped().get(pk=booked.pk))

        assert Client.objects.unscoped().get(pk=booked.pk).scrubbed_at == first

    def test_two_erasures_in_one_org_do_not_collide(self, db, shop_setup):
        """The unique constraint blanks to the same value twice.

        Left total, the second erasure in an organization would fail on
        `(organization, phone)` — turning "this person asked to be forgotten"
        into a 500 whose cause is a unique index.
        """
        first = Client.objects.create(
            organization=shop_setup.organization, full_name="A", phone="+254712000101"
        )
        second = Client.objects.create(
            organization=shop_setup.organization, full_name="B", phone="+254712000102"
        )

        erasure.erase(first)
        erasure.erase(second)

        assert Client.objects.unscoped().filter(scrubbed_at__isnull=False).count() == 2


class TestTheRequestPath:
    def test_a_request_is_kept_after_the_erasure(self, booked):
        """The audit trail. A controller asked to show it acted on a request
        needs both the ask and the action; clearing the flag would leave only
        the action."""
        booked.erasure_requested_at = timezone.now()
        booked.save()

        erasure.erase(booked, reason=ScrubReason.REQUESTED)

        booked.refresh_from_db()
        assert booked.erasure_requested_at is not None


class TestRetention:
    def test_a_client_who_has_not_visited_in_two_years_is_swept(self, db, shop_setup, settings):
        from clients.tasks import scrub_expired_clients

        settings.CLIENT_RETENTION_MONTHS = 24
        stale = Client.objects.create(
            organization=shop_setup.organization, full_name="Old", phone="+254712000201"
        )
        Client.objects.unscoped().filter(pk=stale.pk).update(
            created_at=timezone.now() - timedelta(days=1000)
        )

        assert scrub_expired_clients() >= 1

        stale.refresh_from_db()
        assert stale.is_erased
        assert stale.scrub_reason == ScrubReason.RETENTION

    def test_a_recent_client_is_left_alone(self, db, shop_setup):
        from clients.tasks import scrub_expired_clients

        fresh = Client.objects.create(
            organization=shop_setup.organization, full_name="New", phone="+254712000202"
        )

        scrub_expired_clients()

        fresh.refresh_from_db()
        assert not fresh.is_erased

    def test_a_client_with_no_appointments_is_measured_from_creation(
        self, db, shop_setup, settings
    ):
        """Otherwise a row created by a booking that never completed lives
        forever — the opposite of a retention policy, applied to the records
        with the least reason to exist."""
        settings.CLIENT_RETENTION_MONTHS = 24
        orphan = Client.objects.create(
            organization=shop_setup.organization, full_name="Never came", phone="+254712000203"
        )
        Client.objects.unscoped().filter(pk=orphan.pk).update(
            created_at=timezone.now() - timedelta(days=1000)
        )

        assert orphan in list(erasure.expired_clients())

    def test_an_already_erased_client_is_not_swept_again(self, db, shop_setup, settings):
        settings.CLIENT_RETENTION_MONTHS = 24
        done = Client.objects.create(
            organization=shop_setup.organization, full_name="Gone", phone="+254712000204"
        )
        Client.objects.unscoped().filter(pk=done.pk).update(
            created_at=timezone.now() - timedelta(days=1000)
        )
        erasure.erase(done)

        assert done not in list(erasure.expired_clients())

    def test_the_statement_names_the_configured_period(self, settings):
        """One wording, like §12's refund sentence. A policy worded twice is a
        policy a shop can state one way to a client and another in its
        settings."""
        settings.CLIENT_RETENTION_MONTHS = 18

        assert "18 months" in erasure.retention_statement()


class TestExport:
    def test_it_carries_the_person_and_their_bookings(self, booked):
        payload = erasure.export_for(booked)

        assert payload["client"]["full_name"] == "Amina Wanjiru"
        assert payload["client"]["notes"] == "Allergic to the blue dye"
        assert len(payload["appointments"]) >= 1
        assert payload["appointments"][0]["payments"]

    def test_it_states_the_retention_period(self, booked):
        payload = erasure.export_for(booked)

        assert payload["retention"]["months_after_last_visit"]
        assert payload["retention"]["statement"]

    def test_an_erased_client_exports_a_truthful_empty_answer(self, booked):
        """Not a 404. Somebody asking what is held after an erasure should be
        told what is left and why, rather than getting a status code that reads
        as evasion."""
        erasure.erase(booked)
        booked.refresh_from_db()

        payload = erasure.export_for(booked)

        assert payload["client"]["erased"] is True
        assert payload["client"]["full_name"] == ""
        assert payload["client"]["erased_at"]

    def test_it_is_json_serialisable(self, booked):
        """It is written to a response body. A `Decimal` or a `datetime` that
        slipped in would be a 500 at the moment somebody exercises a legal
        right."""
        import json

        json.dumps(erasure.export_for(booked))
