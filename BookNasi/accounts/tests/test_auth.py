import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_login_succeeds_with_an_unnormalised_phone(api_client, make_user):
    make_user(phone="+254712345678", password="correct-horse-battery")

    response = api_client.post(
        reverse("accounts:login"),
        {"phone": "0712 345 678", "password": "correct-horse-battery"},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["phone"] == "+254712345678"


def test_login_failure_does_not_reveal_whether_the_number_exists(api_client, make_user):
    """Same message either way, so the endpoint cannot be walked to find out
    which numbers have accounts."""
    make_user(phone="+254712345678", password="correct-horse-battery")

    wrong_password = api_client.post(
        reverse("accounts:login"),
        {"phone": "+254712345678", "password": "wrong"},
        format="json",
    )
    no_such_user = api_client.post(
        reverse("accounts:login"),
        {"phone": "+254712999999", "password": "wrong"},
        format="json",
    )

    assert wrong_password.status_code == no_such_user.status_code == 400
    assert wrong_password.json() == no_such_user.json()


def test_login_rejects_a_malformed_phone_before_touching_the_database(api_client):
    response = api_client.post(
        reverse("accounts:login"), {"phone": "0812345678", "password": "x"}, format="json"
    )

    assert response.status_code == 400
    assert "phone" in response.json()


def test_inactive_user_cannot_log_in(api_client, make_user):
    user = make_user(phone="+254712345678", password="correct-horse-battery")
    user.is_active = False
    user.save(update_fields=["is_active"])

    response = api_client.post(
        reverse("accounts:login"),
        {"phone": "+254712345678", "password": "correct-horse-battery"},
        format="json",
    )

    assert response.status_code == 400


def test_me_returns_the_user_and_their_memberships(api_client, org_a):
    api_client.force_login(org_a.owner)

    response = api_client.get(reverse("accounts:me"))

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["phone"] == org_a.owner.phone
    assert [m["organization"] for m in body["memberships"]] == [str(org_a.organization.id)]


def test_me_requires_authentication(api_client):
    assert api_client.get(reverse("accounts:me")).status_code in {401, 403}


def test_logout_ends_the_session(api_client, org_a):
    api_client.force_login(org_a.owner)

    assert api_client.post(reverse("accounts:logout")).status_code == 204
    assert api_client.get(reverse("accounts:me")).status_code in {401, 403}
