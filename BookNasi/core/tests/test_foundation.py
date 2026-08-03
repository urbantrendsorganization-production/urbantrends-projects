"""Foundation checks: the things slice 3 and beyond assume are already true."""

import pytest
from django.db import connection
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_btree_gist_is_installed():
    """Slice 3's exclusion constraint on `appointments` cannot be created
    without it, and creating an extension needs elevated database privileges.
    Failing here, in the foundation slice, is far cheaper than failing during a
    production migration of the riskiest module in the repo. CLAUDE.md §4."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'btree_gist'")
        assert cursor.fetchone() is not None


def test_the_database_is_postgresql():
    """Not a style preference. The availability engine needs an exclusion
    constraint over a range type, which no other backend provides."""
    assert connection.vendor == "postgresql"


def test_health_reports_database_and_redis(client):
    response = client.get(reverse("health"))

    body = response.json()
    assert body["checks"]["database"]["ok"] is True
    assert body["checks"]["database"]["btree_gist"] is True
    assert "redis" in body["checks"]


def test_uuid_primary_keys_everywhere(org_a):
    """Sequential ids leak tenant volume, and slice 5 puts appointment ids in
    URLs opened from an SMS by someone with no login."""
    import uuid

    assert isinstance(org_a.organization.id, uuid.UUID)
    assert isinstance(org_a.owner.id, uuid.UUID)
    assert isinstance(org_a.owner_membership.id, uuid.UUID)


def test_times_are_stored_in_utc(org_a):
    """CLAUDE.md §4: store UTC, render EAT, no timezone abstraction layer."""
    from django.conf import settings

    assert settings.TIME_ZONE == "UTC"
    assert settings.USE_TZ is True
    assert org_a.organization.created_at.utcoffset().total_seconds() == 0
