"""Directory search, faceted filters, sorting, and cursor pagination.

These cover the Phase 3 centerpiece: that keyword search hits the FTS index,
every facet narrows correctly, facets combine with AND, the sort orders are
right, the cursor walks pages without dupes, and the feed stays free of N+1s as
volume grows.
"""
import pytest

from apps.catalog import services
from apps.catalog.models import Category, ListingStatus
from apps.catalog.tests.conftest import make_image

LIST_URL = "/api/v1/listings/"


def make_active(seller, category, *, attributes, **fields):
    """Create a listing and publish it, so it shows in the public directory
    (and gets its search vector populated) — the real service path."""
    defaults = dict(
        title="Item", description="", price="1000.00",
        condition="good", location="Nairobi",
    )
    defaults.update(fields)
    listing = services.create_listing(
        seller=seller, category=category, attributes=attributes, **defaults
    )
    return services.transition_listing(listing, ListingStatus.ACTIVE)


@pytest.fixture
def phones(root_category):
    """The Phones category (child of Electronics) from the shared fixture."""
    return root_category


@pytest.fixture
def electronics(phones):
    return phones.parent


# --- keyword search --------------------------------------------------------


@pytest.mark.django_db
def test_search_matches_title(api_client, verified_user, phones):
    make_active(verified_user, phones, title="iPhone 13 Pro Max",
                attributes={"brand": "Apple"})
    make_active(verified_user, phones, title="Samsung Galaxy S22",
                attributes={"brand": "Samsung"})

    results = api_client.get(LIST_URL, {"q": "iphone"}).data["results"]
    assert [r["title"] for r in results] == ["iPhone 13 Pro Max"]


@pytest.mark.django_db
def test_search_matches_description(api_client, verified_user, phones):
    make_active(verified_user, phones, title="Phone A",
                description="cracked screen, for parts", attributes={"brand": "Apple"})
    make_active(verified_user, phones, title="Phone B",
                description="pristine condition", attributes={"brand": "Nokia"})

    results = api_client.get(LIST_URL, {"q": "cracked"}).data["results"]
    assert [r["title"] for r in results] == ["Phone A"]


@pytest.mark.django_db
def test_search_no_match_returns_empty(api_client, verified_user, phones):
    make_active(verified_user, phones, title="iPhone", attributes={"brand": "Apple"})
    assert api_client.get(LIST_URL, {"q": "helicopter"}).data["results"] == []


# --- facet filters ---------------------------------------------------------


@pytest.mark.django_db
def test_category_filter_includes_descendants(
    api_client, verified_user, phones, electronics
):
    laptops = Category.objects.create(
        name="Laptops", slug="laptops", parent=electronics,
        attribute_schema=[],
    )
    make_active(verified_user, phones, title="A phone", attributes={"brand": "Apple"})
    make_active(verified_user, laptops, title="A laptop", attributes={"brand": "Dell"})

    # Filtering by the parent returns listings from both child categories.
    results = api_client.get(LIST_URL, {"category": electronics.pk}).data["results"]
    assert {r["title"] for r in results} == {"A phone", "A laptop"}

    # Filtering by a leaf returns only that leaf's listings.
    only_phone = api_client.get(LIST_URL, {"category": phones.pk}).data["results"]
    assert {r["title"] for r in only_phone} == {"A phone"}


@pytest.mark.django_db
def test_price_range_filter(api_client, verified_user, phones):
    for price in ("1000.00", "5000.00", "9000.00"):
        make_active(verified_user, phones, title=f"P{price}", price=price,
                    attributes={"brand": "Apple"})

    results = api_client.get(
        LIST_URL, {"price_min": "4000", "price_max": "8000"}
    ).data["results"]
    assert {r["price"] for r in results} == {"5000.00"}


@pytest.mark.django_db
def test_condition_multi_filter(api_client, verified_user, phones):
    for cond in ("new", "good", "fair"):
        make_active(verified_user, phones, title=cond, condition=cond,
                    attributes={"brand": "Apple"})

    results = api_client.get(LIST_URL, {"condition": "new,good"}).data["results"]
    assert {r["condition"] for r in results} == {"new", "good"}


@pytest.mark.django_db
def test_location_filter_is_case_insensitive(api_client, verified_user, phones):
    make_active(verified_user, phones, title="In town", location="Nairobi CBD",
                attributes={"brand": "Apple"})
    make_active(verified_user, phones, title="Coast", location="Mombasa",
                attributes={"brand": "Apple"})

    results = api_client.get(LIST_URL, {"location": "nairobi"}).data["results"]
    assert [r["title"] for r in results] == ["In town"]


@pytest.mark.django_db
def test_attribute_filter(api_client, verified_user, phones):
    make_active(verified_user, phones, title="Apple one", attributes={"brand": "Apple"})
    make_active(verified_user, phones, title="Sammy", attributes={"brand": "Samsung"})

    results = api_client.get(
        LIST_URL, {"category": phones.pk, "attr_brand": "Apple"}
    ).data["results"]
    assert [r["title"] for r in results] == ["Apple one"]


@pytest.mark.django_db
def test_numeric_attribute_filter_coerces_type(api_client, verified_user, phones):
    make_active(verified_user, phones, title="256GB",
                attributes={"brand": "Apple", "storage_gb": 256})
    make_active(verified_user, phones, title="64GB",
                attributes={"brand": "Apple", "storage_gb": 64})

    # The query value arrives as a string but must match the stored number.
    results = api_client.get(
        LIST_URL, {"category": phones.pk, "attr_storage_gb": "256"}
    ).data["results"]
    assert [r["title"] for r in results] == ["256GB"]


@pytest.mark.django_db
def test_filters_combine_with_and(api_client, verified_user, phones):
    make_active(verified_user, phones, title="match", price="5000.00",
                condition="good", attributes={"brand": "Apple"})
    make_active(verified_user, phones, title="wrong price", price="50000.00",
                condition="good", attributes={"brand": "Apple"})
    make_active(verified_user, phones, title="wrong cond", price="5000.00",
                condition="fair", attributes={"brand": "Apple"})

    results = api_client.get(LIST_URL, {
        "category": phones.pk, "price_max": "10000",
        "condition": "good", "attr_brand": "Apple",
    }).data["results"]
    assert [r["title"] for r in results] == ["match"]


# --- sorting ---------------------------------------------------------------


@pytest.mark.django_db
def test_sort_price_ascending_and_descending(api_client, verified_user, phones):
    for price in ("3000.00", "1000.00", "2000.00"):
        make_active(verified_user, phones, title=price, price=price,
                    attributes={"brand": "Apple"})

    asc = api_client.get(LIST_URL, {"sort": "price_asc"}).data["results"]
    assert [r["price"] for r in asc] == ["1000.00", "2000.00", "3000.00"]

    desc = api_client.get(LIST_URL, {"sort": "price_desc"}).data["results"]
    assert [r["price"] for r in desc] == ["3000.00", "2000.00", "1000.00"]


# --- cursor pagination -----------------------------------------------------


@pytest.mark.django_db
def test_cursor_pagination_walks_all_without_duplicates(
    api_client, verified_user, phones
):
    # More than one page (page_size = 24).
    for i in range(30):
        make_active(verified_user, phones, title=f"L{i}", price=f"{1000 + i}.00",
                    attributes={"brand": "Apple"})

    seen, url = [], LIST_URL + "?sort=price_asc"
    pages = 0
    while url and pages < 10:
        data = api_client.get(url).data
        seen += [r["id"] for r in data["results"]]
        url = data["next"]
        pages += 1

    assert pages == 2
    assert len(seen) == 30
    assert len(set(seen)) == 30  # no repeats across the cursor boundary


# --- performance -----------------------------------------------------------


@pytest.mark.django_db
def test_directory_has_no_n_plus_one(
    api_client, django_assert_max_num_queries, verified_user, other_user, phones,
    settings, tmp_path,
):
    """Query count for the feed must not grow with the number of listings or
    their images — select_related/prefetch_related keep it flat."""
    settings.MEDIA_ROOT = tmp_path

    def seed(n, seller):
        for i in range(n):
            listing = make_active(
                seller, phones, title=f"Item {i}", attributes={"brand": "Apple"}
            )
            services.add_image(listing, make_image())

    seed(3, verified_user)
    with django_assert_max_num_queries(6) as captured:
        first = api_client.get(LIST_URL).data
    baseline = len(captured.captured_queries)

    seed(10, other_user)
    with django_assert_max_num_queries(baseline) as captured:
        second = api_client.get(LIST_URL).data

    # Same number of queries despite far more rows/images → no N+1.
    assert len(captured.captured_queries) == baseline
    assert len(first["results"]) == 3
    assert len(second["results"]) == 13
