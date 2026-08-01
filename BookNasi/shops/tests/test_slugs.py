"""Shop slugs are hostnames in one global namespace.

The booking page is `shopname.booknasi.co.ke`, so this is the one place a tenant
can collide with a tenant it cannot see.
"""

import pytest
from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.urls import reverse

from shops.models import Shop
from shops.slugs import RESERVED_SLUGS, suggest_slug, validate_shop_slug

pytestmark = pytest.mark.django_db


class TestFormat:
    @pytest.mark.parametrize("slug", ["mint-braids", "sharp-cuts-2", "kilimani", "a1"])
    def test_valid_labels_pass(self, slug):
        assert validate_shop_slug(slug) == slug

    def test_case_is_normalised_rather_than_rejected(self):
        """DNS is case-insensitive, so `Kilimani` and `kilimani` are the same
        host. Refusing one would be pedantry, not protection — but the stored
        value has to be canonical or the uniqueness check misses collisions."""
        assert validate_shop_slug("Kilimani") == "kilimani"
        assert validate_shop_slug("  MINT-Braids  ") == "mint-braids"

    def test_a_reserved_slug_is_caught_after_normalisation(self):
        """`ADMIN` must not slip past the reserved list on a capital letter."""
        with pytest.raises(ValidationError):
            validate_shop_slug("ADMIN")

    @pytest.mark.parametrize(
        "slug",
        [
            "",
            "a",  # single character, reserved for the platform
            "-leading",
            "trailing-",
            "under_score",
            "has space",
            "emoji-💇",
            "x" * 64,  # over the DNS label limit
            "xn--80ak6aa92e",  # punycode: could render as another shop's name
        ],
    )
    def test_invalid_labels_are_refused(self, slug):
        with pytest.raises(ValidationError):
            validate_shop_slug(slug)


class TestReserved:
    @pytest.mark.parametrize("slug", ["www", "api", "admin", "app", "mail", "staging"])
    def test_the_obvious_ones_are_refused(self, slug):
        with pytest.raises(ValidationError):
            validate_shop_slug(slug)

    @pytest.mark.parametrize("slug", ["mpesa", "pay", "checkout", "callback", "billing"])
    def test_payment_labels_are_refused(self, slug):
        """`mpesa.booknasi.co.ke` in the hands of a tenant is a phishing page
        with a valid certificate."""
        with pytest.raises(ValidationError):
            validate_shop_slug(slug)

    @pytest.mark.parametrize("slug", ["login", "signup", "auth", "account"])
    def test_auth_labels_are_refused(self, slug):
        with pytest.raises(ValidationError):
            validate_shop_slug(slug)

    def test_the_error_suggests_a_way_forward(self):
        with pytest.raises(ValidationError) as excinfo:
            validate_shop_slug("admin")

        assert "admin-salon" in str(excinfo.value)

    def test_the_reserved_list_is_not_trivially_small(self):
        assert len(RESERVED_SLUGS) > 100


class TestGlobalUniqueness:
    def test_two_organizations_cannot_share_a_slug(self, org_a, org_b):
        """Not per-org. This is the one cross-tenant collision in the product,
        and it is inherent to shipping subdomains."""
        Shop.objects.create(organization=org_a.organization, name="Kilimani", slug="kilimani")

        with pytest.raises(IntegrityError):
            Shop.objects.create(organization=org_b.organization, name="Kilimani", slug="kilimani")

    def test_the_api_refuses_a_taken_slug_rather_than_suffixing_it(self, api_client, org_a, org_b):
        """Silently handing back `kilimani-2.booknasi.co.ke` is a support call:
        the slug is the address they are about to put on WhatsApp."""
        Shop.objects.create(organization=org_b.organization, name="Kilimani", slug="kilimani")
        api_client.force_login(org_a.owner)

        response = api_client.post(
            reverse("shops:shop-list", args=[org_a.organization.id]),
            {"name": "Kilimani", "slug": "kilimani"},
            format="json",
        )

        assert response.status_code == 400
        assert "already taken" in str(response.json()["slug"]).lower()

    def test_the_error_does_not_reveal_who_holds_it(self, api_client, org_a, org_b):
        """A collision has to be reported, but not attributed — the holder is
        another tenant this user cannot otherwise see."""
        Shop.objects.create(organization=org_b.organization, name="Kilimani", slug="kilimani")
        api_client.force_login(org_a.owner)

        response = api_client.post(
            reverse("shops:shop-list", args=[org_a.organization.id]),
            {"name": "Kilimani", "slug": "kilimani"},
            format="json",
        )

        body = str(response.json()).lower()
        assert "sharp cuts" not in body
        assert str(org_b.organization.id) not in body

    def test_a_reserved_slug_is_refused_by_the_api(self, api_client, org_a):
        api_client.force_login(org_a.owner)

        response = api_client.post(
            reverse("shops:shop-list", args=[org_a.organization.id]),
            {"name": "Admin", "slug": "admin"},
            format="json",
        )

        assert response.status_code == 400


class TestSuggestion:
    def test_a_name_becomes_a_usable_label(self):
        assert suggest_slug("Mint Braids Kilimani") == "mint-braids-kilimani"

    def test_a_taken_suggestion_is_stepped_past(self):
        assert suggest_slug("Kilimani", taken={"kilimani"}) == "kilimani-2"

    def test_a_reserved_suggestion_is_stepped_past(self):
        assert suggest_slug("Admin") == "admin-2"

    def test_omitting_the_slug_at_create_time_derives_one(self, api_client, org_a):
        """Deriving is fine when the owner did not choose; overriding a slug
        they *did* choose is not."""
        api_client.force_login(org_a.owner)

        response = api_client.post(
            reverse("shops:shop-list", args=[org_a.organization.id]),
            {"name": "Mint Braids Westlands"},
            format="json",
        )

        assert response.status_code == 201
        assert response.json()["slug"] == "mint-braids-westlands"


class TestAvailabilityEndpoint:
    def test_it_reports_a_free_slug_with_its_url(self, api_client, org_a):
        """The design shows the booking URL from step one of onboarding, so it
        has to be checkable before the shop exists."""
        api_client.force_login(org_a.owner)

        response = api_client.get(
            reverse("shops:slug-check", args=[org_a.organization.id]), {"slug": "brand-new-shop"}
        )

        assert response.json() == {
            "slug": "brand-new-shop",
            "available": True,
            "url": "https://brand-new-shop.booknasi.co.ke",
        }

    def test_it_reports_a_taken_slug_with_a_suggestion(self, api_client, org_a, rival_shop):
        api_client.force_login(org_a.owner)

        response = api_client.get(
            reverse("shops:slug-check", args=[org_a.organization.id]),
            {"slug": rival_shop.shop.slug},
        )

        body = response.json()
        assert body["available"] is False
        assert body["suggestion"]

    def test_it_reports_a_reserved_slug_with_the_reason(self, api_client, org_a):
        api_client.force_login(org_a.owner)

        response = api_client.get(
            reverse("shops:slug-check", args=[org_a.organization.id]), {"slug": "api"}
        )

        assert response.json()["available"] is False
        assert "reserved" in response.json()["reason"].lower()
