import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from rest_framework.test import APIClient

User = get_user_model()

REGISTER_URL = "/api/v1/auth/register/"


@pytest.fixture
def client():
    return APIClient()


@pytest.mark.django_db
def test_register_creates_unverified_user_and_sends_email(client):
    resp = client.post(
        REGISTER_URL,
        {"email": "ann@example.com", "password": "str0ng-pass-9", "display_name": "Ann"},
        format="json",
    )

    assert resp.status_code == 201
    user = User.objects.get(email="ann@example.com")
    assert user.is_verified is False
    assert user.display_name == "Ann"
    assert len(mail.outbox) == 1
    assert "verify-email?token=" in mail.outbox[0].body


@pytest.mark.django_db
def test_register_rejects_duplicate_email(client):
    User.objects.create_user(email="dupe@example.com", password="str0ng-pass-9")

    resp = client.post(
        REGISTER_URL,
        {"email": "dupe@example.com", "password": "another-pass-1"},
        format="json",
    )

    assert resp.status_code == 400


@pytest.mark.django_db
def test_register_rejects_weak_password(client):
    resp = client.post(
        REGISTER_URL,
        {"email": "weak@example.com", "password": "123"},
        format="json",
    )

    assert resp.status_code == 400
    assert not User.objects.filter(email="weak@example.com").exists()
