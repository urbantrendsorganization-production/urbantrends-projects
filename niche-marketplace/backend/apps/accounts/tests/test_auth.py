import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

User = get_user_model()

LOGIN_URL = "/api/v1/auth/login/"
REFRESH_URL = "/api/v1/auth/refresh/"


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def user(db):
    return User.objects.create_user(email="log@example.com", password="str0ng-pass-9")


@pytest.mark.django_db
def test_login_returns_access_and_refresh(client, user):
    resp = client.post(
        LOGIN_URL, {"email": user.email, "password": "str0ng-pass-9"}, format="json"
    )

    assert resp.status_code == 200
    body = resp.json()
    assert "access" in body and "refresh" in body


@pytest.mark.django_db
def test_login_rejects_wrong_password(client, user):
    resp = client.post(
        LOGIN_URL, {"email": user.email, "password": "wrong"}, format="json"
    )

    assert resp.status_code == 401


@pytest.mark.django_db
def test_refresh_rotates_tokens(client, user):
    login = client.post(
        LOGIN_URL, {"email": user.email, "password": "str0ng-pass-9"}, format="json"
    ).json()

    resp = client.post(REFRESH_URL, {"refresh": login["refresh"]}, format="json")

    assert resp.status_code == 200
    body = resp.json()
    assert "access" in body
    # Rotation is enabled, so a fresh refresh token is issued too.
    assert body["refresh"] != login["refresh"]
