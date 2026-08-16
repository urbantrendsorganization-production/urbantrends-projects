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


#: A Fernet key generated once, here, for the test suite only. Not a secret and
#: not reachable from any deployment: `config/settings/base.py` leaves
#: `MPESA_CREDENTIAL_KEYS` empty and `prod.py` refuses to boot without a real
#: one, so the only way this value is ever used is by running the tests.
#: Committed rather than generated per run so that a failure is reproducible
#: from the same ciphertext.
TEST_CREDENTIAL_KEY = "2026t:0iyRDgKPPXGKa_LVJoaVEjHIH34ozzcE0IN7oIhQAAg="


@pytest.fixture(autouse=True)
def mpesa_environment(settings):
    """The deployment-level M-Pesa configuration every test runs against.

    Two things, and both exist because slice 13 made "which account" a question
    with more than one answer:

    - **A platform shortcode.** `Shop.CollectsVia.PLATFORM` reads
      `settings.MPESA`, and `payments/tills.py` refuses to push when it is
      blank — correctly, since a deployment with no platform till cannot
      collect for a shop that has not connected its own. `base.py` defaults
      these to `""` so local work needs no M-Pesa account, which would leave
      every push in the suite refused.
    - **A credential key**, so `core/secrets.seal` works and a test can create
      a shop with its own till.

    Placeholders throughout. CLAUDE.md §5: nothing real, sandbox included.
    """
    settings.MPESA = {
        **settings.MPESA,
        "CONSUMER_KEY": "platform-placeholder",
        "CONSUMER_SECRET": "platform-placeholder",
        "SHORTCODE": "4000000",
        "PASSKEY": "platform-placeholder",
        "CALLBACK_URL": "https://example.test/api/mpesa/tok/",
    }
    settings.MPESA_CREDENTIAL_KEYS = [TEST_CREDENTIAL_KEY]


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
        CollectsVia,
        DepositMode,
        OpeningHours,
        Service,
        Shop,
        Staff,
        StaffService,
        WorkingHours,
    )

    shop = Shop.objects.create(
        organization=org.organization,
        name=name,
        slug=slug,
        area="Wood Ave",
        # The deployment's own till, which is what every shop collected into
        # before slice 13 and what `shops/migrations/0004` moved them all to.
        # These fixtures predate that slice and their tests are about push
        # mechanics rather than routing, so `settings.MPESA` stays the thing
        # that governs them and nothing about their behaviour changed.
        #
        # A shop on its own credentials is `shops/tests/test_own_till.py` and
        # `payments/tests/test_per_shop_till.py`, which build one deliberately —
        # including the case that matters most, a brand-new shop defaulting to
        # OWN with nothing filled in and therefore unable to take a deposit.
        collects_via=CollectsVia.PLATFORM,
    )
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
