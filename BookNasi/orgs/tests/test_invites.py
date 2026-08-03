from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from orgs.models import Membership, Role, StaffInvite, hash_invite_token

pytestmark = pytest.mark.django_db


@pytest.fixture
def invite(org_a):
    invite, token = StaffInvite.issue(
        organization=org_a.organization, phone="0712555001", created_by=org_a.owner
    )
    return invite, token


def accept(api_client, token, **overrides):
    payload = {"token": token, "full_name": "Grace Njeri", "password": "correct-horse-battery"}
    return api_client.post(
        reverse("accounts:invite-accept"), {**payload, **overrides}, format="json"
    )


class TestIssuing:
    def test_owner_can_invite_a_stylist(self, api_client, org_a):
        api_client.force_login(org_a.owner)

        response = api_client.post(
            reverse("orgs:invite-list", args=[org_a.organization.id]),
            {"phone": "0712555001", "role": "staff"},
            format="json",
        )

        assert response.status_code == 201
        assert response.json()["phone"] == "+254712555001"
        assert response.json()["status"] == "pending"
        assert response.json()["token"]

    def test_a_stylist_cannot_invite_anyone(self, api_client, org_a):
        api_client.force_login(org_a.stylist)

        response = api_client.post(
            reverse("orgs:invite-list", args=[org_a.organization.id]),
            {"phone": "0712555001"},
            format="json",
        )

        assert response.status_code == 403

    def test_only_the_hash_is_stored(self, invite):
        stored, token = invite

        assert stored.token_hash == hash_invite_token(token)
        assert token not in stored.token_hash
        assert len(stored.token_hash) == 64

    def test_cannot_invite_someone_already_on_the_organization(self, api_client, org_a):
        api_client.force_login(org_a.owner)

        response = api_client.post(
            reverse("orgs:invite-list", args=[org_a.organization.id]),
            {"phone": org_a.stylist.phone},
            format="json",
        )

        assert response.status_code == 400

    def test_cannot_open_a_second_invite_for_the_same_number(self, api_client, org_a, invite):
        api_client.force_login(org_a.owner)

        response = api_client.post(
            reverse("orgs:invite-list", args=[org_a.organization.id]),
            {"phone": "0712555001"},
            format="json",
        )

        assert response.status_code == 400

    def test_owner_role_cannot_be_invited(self, api_client, org_a):
        api_client.force_login(org_a.owner)

        response = api_client.post(
            reverse("orgs:invite-list", args=[org_a.organization.id]),
            {"phone": "0712555001", "role": "owner"},
            format="json",
        )

        assert response.status_code == 400

    def test_the_list_shows_the_adoption_state(self, api_client, org_a, invite):
        """Drives the design's `Invited 3 Aug · hasn't signed in yet` row, which
        doubles as the owner's adoption report."""
        api_client.force_login(org_a.owner)

        rows = api_client.get(reverse("orgs:invite-list", args=[org_a.organization.id])).json()

        assert [row["status"] for row in rows] == ["pending"]


class TestAccepting:
    def test_accepting_creates_a_user_and_an_active_membership(self, api_client, org_a, invite):
        _, token = invite

        response = accept(api_client, token)

        assert response.status_code == 201
        user = User.objects.get(phone="+254712555001")
        membership = Membership.objects.for_org(org_a.organization).get(user=user)
        assert user.full_name == "Grace Njeri"
        assert membership.role == Role.STAFF
        assert membership.is_active
        assert membership.accepted_at is not None

    def test_accepting_logs_the_new_staff_member_in(self, api_client, invite):
        _, token = invite

        accept(api_client, token)

        assert api_client.get(reverse("accounts:me")).status_code == 200

    def test_an_invite_is_single_use(self, api_client, invite):
        _, token = invite
        assert accept(api_client, token).status_code == 201

        second = accept(api_client, token)

        assert second.status_code == 400

    def test_an_expired_invite_is_refused(self, api_client, invite):
        stored, token = invite
        stored.expires_at = timezone.now() - timedelta(seconds=1)
        stored.save(update_fields=["expires_at"])

        assert accept(api_client, token).status_code == 400

    def test_a_revoked_invite_is_refused(self, api_client, invite):
        stored, token = invite
        stored.revoked_at = timezone.now()
        stored.save(update_fields=["revoked_at"])

        assert accept(api_client, token).status_code == 400

    def test_every_bad_token_gets_the_same_answer(self, api_client, invite):
        """Missing, expired, revoked and already-used must be indistinguishable,
        or the endpoint tells a guesser which guesses were warm."""
        stored, token = invite
        stored.expires_at = timezone.now() - timedelta(seconds=1)
        stored.save(update_fields=["expires_at"])

        expired = accept(api_client, token)
        nonsense = accept(api_client, "not-a-real-token")

        assert expired.status_code == nonsense.status_code == 400
        assert expired.json() == nonsense.json()

    def test_a_weak_password_is_refused(self, api_client, invite):
        _, token = invite

        assert accept(api_client, token, password="12345678").status_code == 400

    def test_an_existing_user_is_attached_not_duplicated(self, api_client, org_a, org_b, make_user):
        """A stylist who already works for another org is one person. Creating a
        second account would split their login and, later, their client history."""
        existing = make_user(full_name="Grace Njeri", phone="+254712555002")
        _, token = StaffInvite.issue(
            organization=org_a.organization, phone="+254712555002", created_by=org_a.owner
        )

        response = accept(api_client, token)

        assert response.status_code == 201
        assert User.objects.filter(phone="+254712555002").count() == 1
        assert Membership.objects.for_org(org_a.organization).filter(user=existing).exists()

    def test_accepting_does_not_reset_an_existing_password(self, api_client, make_user):
        """Otherwise an invite becomes a password-reset primitive: invite a
        number you do not control, and you take over that account."""
        from orgs.models import Organization

        existing = make_user(phone="+254712555003", password="their-own-password")
        organization = Organization.objects.create(
            name="Sharp Cuts Two", slug="sharp-cuts-two", owner=existing
        )
        _, token = StaffInvite.issue(organization=organization, phone="+254712555003")

        accept(api_client, token, password="attacker-chosen-password")

        existing.refresh_from_db()
        assert existing.check_password("their-own-password")
        assert not existing.check_password("attacker-chosen-password")


class TestResending:
    def test_resend_rotates_the_token_and_invalidates_the_old_one(self, api_client, org_a, invite):
        stored, old_token = invite
        api_client.force_login(org_a.owner)

        response = api_client.post(
            reverse("orgs:invite-resend", args=[org_a.organization.id, stored.id])
        )

        assert response.status_code == 200
        new_token = response.json()["token"]
        assert new_token != old_token
        assert response.json()["sent_count"] == 2
        api_client.logout()
        assert accept(api_client, old_token).status_code == 400
        assert accept(api_client, new_token).status_code == 201

    def test_resend_extends_the_expiry(self, api_client, org_a, invite):
        stored, _ = invite
        stored.expires_at = timezone.now() - timedelta(seconds=1)
        stored.save(update_fields=["expires_at"])
        api_client.force_login(org_a.owner)

        api_client.post(reverse("orgs:invite-resend", args=[org_a.organization.id, stored.id]))

        stored.refresh_from_db()
        assert stored.is_pending

    def test_an_accepted_invite_cannot_be_resent(self, api_client, org_a, invite):
        stored, token = invite
        accept(api_client, token)
        api_client.force_login(org_a.owner)

        response = api_client.post(
            reverse("orgs:invite-resend", args=[org_a.organization.id, stored.id])
        )

        assert response.status_code == 400

    def test_another_orgs_invite_cannot_be_resent(self, api_client, org_a, org_b, invite):
        stored, _ = invite
        api_client.force_login(org_b.owner)

        response = api_client.post(
            reverse("orgs:invite-resend", args=[org_a.organization.id, stored.id])
        )

        assert response.status_code == 404


class TestRemovingPeople:
    def test_removing_a_stylist_deactivates_rather_than_deletes(self, api_client, org_a):
        """Slice 9 reports revenue per staff. A hard delete would take a former
        stylist's work out of last month's numbers."""
        api_client.force_login(org_a.owner)

        response = api_client.delete(
            reverse("orgs:member-detail", args=[org_a.organization.id, org_a.stylist_membership.id])
        )

        assert response.status_code == 204
        org_a.stylist_membership.refresh_from_db()
        assert not org_a.stylist_membership.is_active

    def test_the_owners_membership_cannot_be_removed(self, api_client, org_a):
        api_client.force_login(org_a.owner)

        response = api_client.delete(
            reverse("orgs:member-detail", args=[org_a.organization.id, org_a.owner_membership.id])
        )

        assert response.status_code == 400

    def test_a_stylist_cannot_remove_a_colleague(self, api_client, org_a):
        api_client.force_login(org_a.stylist)

        response = api_client.delete(
            reverse("orgs:member-detail", args=[org_a.organization.id, org_a.owner_membership.id])
        )

        assert response.status_code == 403
