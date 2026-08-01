import types

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from orgs.models import Membership, Organization, Role


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def make_user(db):
    counter = iter(range(100, 999))

    def _make(full_name="Test Person", phone=None, password="correct-horse-battery", **extra):
        phone = phone or f"+2547120{next(counter):05d}"
        return User.objects.create_user(
            phone=phone, password=password, full_name=full_name, **extra
        )

    return _make


def _build_org(make_user, name, slug, owner_phone, stylist_phone):
    owner = make_user(full_name=f"{name} Owner", phone=owner_phone)
    stylist = make_user(full_name=f"{name} Stylist", phone=stylist_phone)
    organization = Organization.objects.create(name=name, slug=slug, owner=owner)
    owner_membership = Membership.objects.create(
        organization=organization, user=owner, role=Role.OWNER, accepted_at=timezone.now()
    )
    stylist_membership = Membership.objects.create(
        organization=organization, user=stylist, role=Role.STAFF, accepted_at=timezone.now()
    )
    return types.SimpleNamespace(
        organization=organization,
        owner=owner,
        stylist=stylist,
        owner_membership=owner_membership,
        stylist_membership=stylist_membership,
    )


@pytest.fixture
def org_a(make_user):
    """Mint Braids — Kilimani. Owner + one stylist."""
    return _build_org(make_user, "Mint Braids", "mint-braids", "+254712000001", "+254712000002")


@pytest.fixture
def org_b(make_user):
    """A second, unrelated tenant. Its existence is the point: almost every
    isolation bug is invisible in a single-tenant fixture."""
    return _build_org(make_user, "Sharp Cuts", "sharp-cuts", "+254712000003", "+254712000004")
