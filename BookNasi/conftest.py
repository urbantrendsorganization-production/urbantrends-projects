import types
from decimal import Decimal

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


def _build_shop(org, slug, name):
    """A shop that resembles the design's Mint Braids: open Mon-Sat, two
    stylists, one long braiding service and one quick service."""
    from datetime import time

    from shops.models import (
        DepositMode,
        OpeningHours,
        Service,
        Shop,
        Staff,
        StaffService,
        WorkingHours,
    )

    shop = Shop.objects.create(organization=org.organization, name=name, slug=slug, area="Wood Ave")
    for weekday in range(0, 6):  # Monday-Saturday
        OpeningHours.objects.create(
            shop=shop, weekday=weekday, opens_at=time(8, 0), closes_at=time(20, 0)
        )

    wanjiku = Staff.objects.create(
        shop=shop, membership=org.owner_membership, display_name="Wanjiku"
    )
    grace = Staff.objects.create(shop=shop, membership=org.stylist_membership, display_name="Grace")
    for staff in (wanjiku, grace):
        for weekday in range(0, 6):
            WorkingHours.objects.create(
                staff=staff, weekday=weekday, starts_at=time(9, 0), ends_at=time(18, 0)
            )

    braids = Service.objects.create(
        shop=shop,
        name="Knotless braids, medium, waist length",
        duration_minutes=240,
        price=3500,
        deposit_mode=DepositMode.PERCENT,
        deposit_value=Decimal("25"),
    )
    shave = Service.objects.create(
        shop=shop,
        name="Beard trim",
        duration_minutes=20,
        price=500,
        deposit_mode=DepositMode.NONE,
        deposit_value=None,
    )
    for staff in (wanjiku, grace):
        for service in (braids, shave):
            StaffService.objects.create(staff=staff, service=service)

    return types.SimpleNamespace(
        organization=org.organization,
        org=org,
        shop=shop,
        wanjiku=wanjiku,
        grace=grace,
        braids=braids,
        shave=shave,
    )


@pytest.fixture
def shop_setup(org_a):
    return _build_shop(org_a, "mint-braids-kilimani", "Mint Braids Kilimani")


@pytest.fixture
def rival_shop(org_b):
    """A fully configured shop belonging to the *other* tenant."""
    return _build_shop(org_b, "sharp-cuts-thika", "Sharp Cuts Thika Road")
