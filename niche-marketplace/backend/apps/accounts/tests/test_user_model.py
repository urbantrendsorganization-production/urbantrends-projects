import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.mark.django_db
def test_email_is_the_username_field():
    assert User.USERNAME_FIELD == "email"


@pytest.mark.django_db
def test_create_user_normalises_email_and_hashes_password():
    user = User.objects.create_user(email="Buyer@Example.com", password="s3cret-pass")

    assert user.email == "Buyer@example.com"
    assert user.check_password("s3cret-pass")
    assert user.is_verified is False
    assert user.is_staff is False


@pytest.mark.django_db
def test_create_superuser_has_staff_and_superuser_flags():
    admin = User.objects.create_superuser(email="admin@example.com", password="x")

    assert admin.is_staff is True
    assert admin.is_superuser is True


@pytest.mark.django_db
def test_create_user_requires_email():
    with pytest.raises(ValueError):
        User.objects.create_user(email="", password="x")
