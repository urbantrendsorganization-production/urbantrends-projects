import pytest
from django.urls import reverse

from accounts.models import User
from orgs.models import Membership, Organization, Role, SubscriptionStatus

pytestmark = pytest.mark.django_db

PAYLOAD = {
    "organization_name": "Mint Braids",
    "full_name": "Wanjiku Kamau",
    "phone": "0712345678",
    "password": "correct-horse-battery",
}


def test_signup_creates_user_organization_and_owner_membership(api_client):
    response = api_client.post(reverse("orgs:signup"), PAYLOAD, format="json")

    assert response.status_code == 201
    user = User.objects.get(phone="+254712345678")
    organization = Organization.objects.get(slug="mint-braids")
    membership = Membership.objects.for_org(organization).get(user=user)
    assert organization.owner == user
    assert membership.role == Role.OWNER
    assert membership.accepted_at is not None
    assert organization.subscription_status == SubscriptionStatus.TRIALING
    assert organization.retention_months == 24


def test_signup_logs_the_owner_in(api_client):
    api_client.post(reverse("orgs:signup"), PAYLOAD, format="json")

    assert api_client.get(reverse("accounts:me")).status_code == 200


def test_signup_rolls_all_three_back_when_one_step_fails(api_client, monkeypatch):
    """The three writes are one act. A user with no org, or an org with no
    owner membership, is a support ticket that cannot be resolved through the
    product."""
    from orgs import views

    def explode(*args, **kwargs):
        raise RuntimeError("membership write failed")

    monkeypatch.setattr(views.Membership.objects, "create", explode)

    with pytest.raises(RuntimeError):
        api_client.post(reverse("orgs:signup"), PAYLOAD, format="json")

    assert not User.objects.filter(phone="+254712345678").exists()
    assert not Organization.objects.filter(slug="mint-braids").exists()


def test_signup_rejects_a_phone_that_already_has_an_account(api_client, make_user):
    make_user(phone="+254712345678")

    response = api_client.post(reverse("orgs:signup"), PAYLOAD, format="json")

    assert response.status_code == 400
    assert "phone" in response.json()


def test_signup_rejects_a_weak_password(api_client):
    response = api_client.post(
        reverse("orgs:signup"), {**PAYLOAD, "password": "12345678"}, format="json"
    )

    assert response.status_code == 400
    assert "password" in response.json()


def test_two_shops_with_the_same_name_get_distinct_slugs(api_client):
    api_client.post(reverse("orgs:signup"), PAYLOAD, format="json")
    api_client.post(
        reverse("orgs:signup"),
        {**PAYLOAD, "phone": "0712345679"},
        format="json",
    )

    assert Organization.objects.filter(slug="mint-braids").exists()
    assert Organization.objects.filter(slug="mint-braids-2").exists()


def test_owner_can_rename_their_organization(api_client, org_a):
    api_client.force_login(org_a.owner)

    response = api_client.patch(
        reverse("orgs:org-detail", args=[org_a.organization.id]),
        {"name": "Mint Braids Kilimani"},
        format="json",
    )

    assert response.status_code == 200
    org_a.organization.refresh_from_db()
    assert org_a.organization.name == "Mint Braids Kilimani"


def test_a_stylist_cannot_rename_the_organization(api_client, org_a):
    api_client.force_login(org_a.stylist)

    response = api_client.patch(
        reverse("orgs:org-detail", args=[org_a.organization.id]),
        {"name": "Hijacked"},
        format="json",
    )

    assert response.status_code == 400
    org_a.organization.refresh_from_db()
    assert org_a.organization.name == "Mint Braids"


def test_subscription_status_cannot_be_set_through_the_api(api_client, org_a):
    """It is a plain enum (CLAUDE.md §12) but it is still billing state, and
    billing state does not move because a client sent a field."""
    api_client.force_login(org_a.owner)

    api_client.patch(
        reverse("orgs:org-detail", args=[org_a.organization.id]),
        {"subscription_status": "active"},
        format="json",
    )

    org_a.organization.refresh_from_db()
    assert org_a.organization.subscription_status == SubscriptionStatus.TRIALING
