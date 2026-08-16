"""Who can see a client, export one, and erase one.

The permission split here is not the same as everywhere else in the product, so
it is asserted rather than assumed. Reading is a managing role, matching the
rest of the org's configuration. **Erasing is owner-only**, like slice 13's
M-Pesa credentials and for a related reason: it cannot be undone, and it is
quiet — the row that remains looks like any other erased row, so nobody else on
the account would notice somebody had gone.
"""

import json

import pytest
from django.urls import reverse

from clients.models import Client, ScrubReason
from orgs.models import Membership, Role

pytestmark = pytest.mark.loadbearing


def list_url(org):
    return reverse("clients:client-list", args=[org.id])


def detail_url(client):
    return reverse("clients:client-detail", args=[client.organization_id, client.id])


def export_url(client):
    return reverse("clients:client-export", args=[client.organization_id, client.id])


def erase_url(client):
    return reverse("clients:client-erase", args=[client.organization_id, client.id])


@pytest.fixture
def someone(db, shop_setup):
    return Client.objects.create(
        organization=shop_setup.organization,
        full_name="Amina Wanjiru",
        phone="+254712000301",
    )


@pytest.fixture
def manager(db, shop_setup, make_user):
    user = make_user(full_name="Branch Manager")
    Membership.objects.create(
        organization=shop_setup.organization,
        user=user,
        role=Role.MANAGER,
        accepted_at=shop_setup.shop.created_at,
    )
    return user


class TestReading:
    def test_an_owner_sees_the_list(self, api_client, shop_setup, someone):
        api_client.force_login(shop_setup.org.owner)

        response = api_client.get(list_url(shop_setup.organization))

        assert response.status_code == 200
        assert any(row["full_name"] == "Amina Wanjiru" for row in _rows(response))

    def test_a_manager_sees_it_too(self, api_client, shop_setup, someone, manager):
        api_client.force_login(manager)

        assert api_client.get(list_url(shop_setup.organization)).status_code == 200

    def test_a_stylist_does_not(self, api_client, shop_setup, someone):
        api_client.force_login(shop_setup.org.stylist)

        assert api_client.get(list_url(shop_setup.organization)).status_code == 403

    def test_another_tenants_client_is_invisible(self, api_client, shop_setup, rival_shop):
        """Not a 403 on the org either — slice 1's rule. A 403 would confirm the
        organization exists."""
        theirs = Client.objects.create(
            organization=rival_shop.organization, full_name="Theirs", phone="+254712000302"
        )
        api_client.force_login(shop_setup.org.owner)

        assert api_client.get(detail_url(theirs)).status_code == 404

    def test_searching_by_number_finds_them(self, api_client, shop_setup, someone):
        """The realistic lookup: a client rings the shop and gives a number."""
        api_client.force_login(shop_setup.org.owner)

        response = api_client.get(list_url(shop_setup.organization), {"q": "712000301"})

        assert len(_rows(response)) == 1

    def test_outstanding_requests_can_be_filtered(self, api_client, shop_setup, someone):
        from django.utils import timezone

        someone.erasure_requested_at = timezone.now()
        someone.save()
        api_client.force_login(shop_setup.org.owner)

        response = api_client.get(list_url(shop_setup.organization), {"requested": "1"})

        assert len(_rows(response)) == 1


class TestExport:
    def test_it_comes_back_as_a_file(self, api_client, shop_setup, someone):
        api_client.force_login(shop_setup.org.owner)

        response = api_client.get(export_url(someone))

        assert response.status_code == 200
        assert "attachment" in response["Content-Disposition"]

    def test_the_filename_is_the_id_not_the_name(self, api_client, shop_setup, someone):
        """An export of somebody's personal data should not put that data in a
        filename that ends up in a downloads folder and a chat thread."""
        api_client.force_login(shop_setup.org.owner)

        response = api_client.get(export_url(someone))

        assert "Amina" not in response["Content-Disposition"]
        assert str(someone.id) in response["Content-Disposition"]

    def test_it_contains_what_is_held(self, api_client, shop_setup, someone):
        api_client.force_login(shop_setup.org.owner)

        payload = json.loads(api_client.get(export_url(someone)).content)

        assert payload["client"]["full_name"] == "Amina Wanjiru"
        assert payload["retention"]["statement"]

    def test_a_stylist_cannot_export(self, api_client, shop_setup, someone):
        api_client.force_login(shop_setup.org.stylist)

        assert api_client.get(export_url(someone)).status_code == 403


class TestErasingIsOwnerOnly:
    def test_the_owner_can(self, api_client, shop_setup, someone):
        api_client.force_login(shop_setup.org.owner)

        response = api_client.post(erase_url(someone))

        assert response.status_code == 200
        someone.refresh_from_db()
        assert someone.is_erased

    def test_a_manager_cannot(self, api_client, shop_setup, someone, manager):
        api_client.force_login(manager)

        assert api_client.post(erase_url(someone)).status_code == 403
        someone.refresh_from_db()
        assert not someone.is_erased

    def test_a_manager_cannot_even_read_the_plan(self, api_client, shop_setup, someone, manager):
        """A 403 on the write with a readable plan would be a lock on the wrong
        door — the plan names what money is about to be voided."""
        api_client.force_login(manager)

        assert api_client.get(erase_url(someone)).status_code == 403

    def test_a_stylist_cannot(self, api_client, shop_setup, someone):
        api_client.force_login(shop_setup.org.stylist)

        assert api_client.post(erase_url(someone)).status_code == 403

    def test_signed_out_is_refused(self, api_client, someone):
        assert api_client.post(erase_url(someone)).status_code in (401, 403)


class TestThePlan:
    def test_it_states_the_cost_before_anything_happens(self, api_client, shop_setup, someone):
        api_client.force_login(shop_setup.org.owner)

        response = api_client.get(erase_url(someone))

        assert response.status_code == 200
        assert response.data["credit_kes"] == 0
        assert response.data["already_erased"] is False
        someone.refresh_from_db()
        assert not someone.is_erased

    def test_a_requested_erasure_is_recorded_as_requested(self, api_client, shop_setup, someone):
        """The audit trail distinction. A request carries a statutory clock and
        a shop acting unprompted does not."""
        from django.utils import timezone

        someone.erasure_requested_at = timezone.now()
        someone.save()
        api_client.force_login(shop_setup.org.owner)

        api_client.post(erase_url(someone))

        someone.refresh_from_db()
        assert someone.scrub_reason == ScrubReason.REQUESTED

    def test_an_unprompted_one_is_not(self, api_client, shop_setup, someone):
        api_client.force_login(shop_setup.org.owner)

        api_client.post(erase_url(someone))

        someone.refresh_from_db()
        assert someone.scrub_reason == ScrubReason.SHOP


class TestAnErasedClientCannotBeEditedBack:
    def test_writing_a_name_onto_a_scrubbed_row_is_refused(self, api_client, shop_setup, someone):
        """Otherwise a note typed into the wrong screen puts somebody back in
        the database with no record of how."""
        from clients import erasure

        erasure.erase(someone)
        api_client.force_login(shop_setup.org.owner)

        response = api_client.patch(
            detail_url(someone), {"full_name": "Amina Wanjiru"}, format="json"
        )

        assert response.status_code == 400
        someone.refresh_from_db()
        assert someone.full_name == ""

    def test_there_is_no_delete_verb(self, api_client, shop_setup, someone):
        """§9 says scrub, not cascade. A `DELETE` that scrubbed would be the
        wrong shape wearing the right name, and is how somebody eventually
        writes the cascade because the method implied it."""
        api_client.force_login(shop_setup.org.owner)

        assert api_client.delete(detail_url(someone)).status_code == 405


class TestTheClientCanAsk:
    """`POST /api/public/v1/manage/<token>/forget-me/` — no session, no account.

    The manage token proves control of the phone number, which is the same
    verification the deposit relies on (§12).
    """

    def url(self, appointment):
        return reverse("public_api:manage-forget-me", args=[appointment.manage_token])

    def test_it_records_a_request_rather_than_erasing(self, api_client, held):
        """One tap on a link that arrived by SMS is too easy a way to reach
        something irreversible that also voids money."""
        from scheduling import manage_tokens

        manage_tokens.issue(held)

        response = api_client.post(self.url(held))

        assert response.status_code == 200
        held.client.refresh_from_db()
        assert held.client.erasure_requested_at is not None
        assert not held.client.is_erased

    def test_it_keeps_the_first_timestamp(self, api_client, held):
        """The DPA clock starts when the person asked. Restarting it on a second
        tap would let a shop reset its own deadline by prompting."""
        from scheduling import manage_tokens

        manage_tokens.issue(held)
        api_client.post(self.url(held))
        held.client.refresh_from_db()
        first = held.client.erasure_requested_at

        api_client.post(self.url(held))

        held.client.refresh_from_db()
        assert held.client.erasure_requested_at == first

    def test_it_returns_the_retention_statement(self, api_client, held):
        from scheduling import manage_tokens

        manage_tokens.issue(held)

        response = api_client.post(self.url(held))

        assert "months" in response.data["statement"]

    def test_a_bad_token_is_the_same_404_as_a_wrong_one(self, db, api_client):
        """No existence oracle — slice 10's rule for every public 404."""
        malformed = api_client.post(reverse("public_api:manage-forget-me", args=["nonsense"]))
        wrong = api_client.post(reverse("public_api:manage-forget-me", args=["a" * 32]))

        assert malformed.status_code == wrong.status_code == 404
        assert malformed.data == wrong.data


def _rows(response):
    body = response.data
    return body["results"] if isinstance(body, dict) and "results" in body else body
