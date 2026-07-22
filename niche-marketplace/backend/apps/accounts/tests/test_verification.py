import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from rest_framework.test import APIClient

from apps.accounts import services

User = get_user_model()

VERIFY_URL = "/api/v1/auth/verify-email/"
RESEND_URL = "/api/v1/auth/resend-verification/"


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def user(db):
    return User.objects.create_user(email="v@example.com", password="str0ng-pass-9")


@pytest.mark.django_db
def test_valid_token_marks_user_verified(client, user):
    token = services._make_token(user)

    resp = client.post(VERIFY_URL, {"token": token}, format="json")

    assert resp.status_code == 200
    user.refresh_from_db()
    assert user.is_verified is True


@pytest.mark.django_db
def test_expired_token_is_rejected(client, user, settings):
    settings.EMAIL_VERIFICATION_TIMEOUT = -1  # anything is already expired
    token = services._make_token(user)

    resp = client.post(VERIFY_URL, {"token": token}, format="json")

    assert resp.status_code == 400
    assert resp.json()["code"] == "token_expired"
    user.refresh_from_db()
    assert user.is_verified is False


@pytest.mark.django_db
def test_tampered_token_is_rejected(client, user):
    token = services._make_token(user) + "tampered"

    resp = client.post(VERIFY_URL, {"token": token}, format="json")

    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_token"


@pytest.mark.django_db
def test_resend_emails_unverified_user(client, user):
    resp = client.post(RESEND_URL, {"email": user.email}, format="json")

    assert resp.status_code == 200
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_resend_is_silent_for_verified_user(client, user):
    user.is_verified = True
    user.save(update_fields=["is_verified"])

    resp = client.post(RESEND_URL, {"email": user.email}, format="json")

    assert resp.status_code == 200
    assert len(mail.outbox) == 0
