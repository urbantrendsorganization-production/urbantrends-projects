import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

User = get_user_model()

ME_URL = "/api/v1/users/me/"


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        email="me@example.com", password="str0ng-pass-9", display_name="Mia"
    )


@pytest.mark.django_db
def test_me_requires_authentication(client):
    assert client.get(ME_URL).status_code == 401


@pytest.mark.django_db
def test_me_returns_own_profile(client, user):
    client.force_authenticate(user)

    body = client.get(ME_URL).json()

    assert body["email"] == "me@example.com"
    assert body["display_name"] == "Mia"
    assert body["is_verified"] is False
    assert "joined_at" in body


@pytest.mark.django_db
def test_me_can_update_editable_fields(client, user):
    client.force_authenticate(user)

    resp = client.patch(
        ME_URL,
        {"display_name": "Mia R.", "location": "Nairobi", "email": "hacker@evil.com"},
        format="json",
    )

    assert resp.status_code == 200
    user.refresh_from_db()
    assert user.display_name == "Mia R."
    assert user.location == "Nairobi"
    # Email is read-only and must not change.
    assert user.email == "me@example.com"


@pytest.mark.django_db
def test_public_profile_hides_private_fields(client, user):
    resp = client.get(f"/api/v1/users/{user.id}/")

    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Mia"
    assert "email" not in body
    assert "phone" not in body
    assert "is_verified" not in body


@pytest.mark.django_db
def test_public_profile_404_for_unknown_user(client):
    assert client.get("/api/v1/users/999999/").status_code == 404
