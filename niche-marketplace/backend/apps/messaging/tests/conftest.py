import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.catalog.models import Category, Listing, ListingStatus

User = get_user_model()


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def seller(db):
    return User.objects.create_user(
        email="seller@example.com", password="pw", is_verified=True,
        display_name="Sam Seller",
    )


@pytest.fixture
def buyer(db):
    return User.objects.create_user(
        email="buyer@example.com", password="pw", is_verified=True,
        display_name="Bea Buyer",
    )


@pytest.fixture
def stranger(db):
    return User.objects.create_user(
        email="stranger@example.com", password="pw", is_verified=True,
    )


@pytest.fixture
def listing(db, seller) -> Listing:
    category = Category.objects.create(name="Phones", slug="phones")
    return Listing.objects.create(
        seller=seller,
        category=category,
        title="iPhone 13",
        description="Clean unit",
        price="45000.00",
        condition="good",
        location="Nairobi",
        status=ListingStatus.ACTIVE,
    )
