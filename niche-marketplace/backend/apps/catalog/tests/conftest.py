import io

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.catalog.models import Category

User = get_user_model()


@pytest.fixture(autouse=True)
def _eager_celery(settings):
    """Run Celery tasks (thumbnail generation) inline during tests."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def verified_user(db):
    return User.objects.create_user(
        email="seller@example.com", password="pw", is_verified=True
    )


@pytest.fixture
def other_user(db):
    return User.objects.create_user(
        email="other@example.com", password="pw", is_verified=True
    )


@pytest.fixture
def unverified_user(db):
    return User.objects.create_user(email="new@example.com", password="pw")


@pytest.fixture
def root_category(db) -> Category:
    """Electronics > Phones with an inherited + own attribute schema."""
    electronics = Category.objects.create(
        name="Electronics",
        slug="electronics",
        attribute_schema=[
            {"key": "brand", "label": "Brand", "type": "string", "required": True},
        ],
    )
    phones = Category.objects.create(
        name="Phones",
        slug="phones",
        parent=electronics,
        attribute_schema=[
            {"key": "storage_gb", "label": "Storage (GB)", "type": "number"},
            {
                "key": "network",
                "label": "Network",
                "type": "enum",
                "options": ["Unlocked", "Locked"],
            },
            {"key": "dual_sim", "label": "Dual SIM", "type": "boolean"},
        ],
    )
    return phones


def make_image(name: str = "photo.png") -> SimpleUploadedFile:
    """A tiny valid PNG for upload tests."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (1200, 800), color=(120, 80, 200)).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")
