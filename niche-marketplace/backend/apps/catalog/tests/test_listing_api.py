"""End-to-end listing API: create → edit → publish → sell, plus permissions."""
import pytest

from apps.catalog.models import Listing, ListingStatus
from apps.catalog.tests.conftest import make_image

LIST_URL = "/api/v1/listings/"


def detail_url(pk):
    return f"/api/v1/listings/{pk}/"


def new_listing_payload(category, **overrides):
    payload = {
        "category": category.pk,
        "title": "iPhone 13",
        "description": "Clean unit",
        "price": "45000.00",
        "condition": "like_new",
        "location": "Nairobi",
        "attributes": {"brand": "Apple", "storage_gb": 128, "network": "Unlocked"},
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
def test_anonymous_cannot_create(api_client, root_category):
    res = api_client.post(LIST_URL, new_listing_payload(root_category), format="json")
    assert res.status_code == 401


@pytest.mark.django_db
def test_unverified_cannot_create(api_client, unverified_user, root_category):
    api_client.force_authenticate(unverified_user)
    res = api_client.post(LIST_URL, new_listing_payload(root_category), format="json")
    assert res.status_code == 403
    assert res.data["code"] == "email_not_verified"


@pytest.mark.django_db
def test_create_starts_as_draft(api_client, verified_user, root_category):
    api_client.force_authenticate(verified_user)
    res = api_client.post(LIST_URL, new_listing_payload(root_category), format="json")
    assert res.status_code == 201, res.data
    assert res.data["status"] == ListingStatus.DRAFT
    assert res.data["seller"]["id"] == verified_user.id
    assert res.data["attributes"]["storage_gb"] == 128


@pytest.mark.django_db
def test_create_rejects_invalid_attributes(api_client, verified_user, root_category):
    api_client.force_authenticate(verified_user)
    payload = new_listing_payload(root_category, attributes={"storage_gb": 128})  # no brand
    res = api_client.post(LIST_URL, payload, format="json")
    assert res.status_code == 400
    assert "brand" in res.data["detail"]["attributes"]


@pytest.mark.django_db
def test_draft_hidden_from_public_but_visible_to_owner(
    api_client, verified_user, other_user, root_category
):
    api_client.force_authenticate(verified_user)
    listing_id = api_client.post(
        LIST_URL, new_listing_payload(root_category), format="json"
    ).data["id"]

    # Public list excludes drafts.
    api_client.force_authenticate(None)
    assert api_client.get(LIST_URL).data["results"] == []

    # A stranger cannot open the draft detail.
    api_client.force_authenticate(other_user)
    assert api_client.get(detail_url(listing_id)).status_code == 403

    # The owner can.
    api_client.force_authenticate(verified_user)
    assert api_client.get(detail_url(listing_id)).status_code == 200


@pytest.mark.django_db
def test_publish_then_sold_flow(api_client, verified_user, root_category):
    api_client.force_authenticate(verified_user)
    listing_id = api_client.post(
        LIST_URL, new_listing_payload(root_category), format="json"
    ).data["id"]

    # Publish.
    res = api_client.post(
        f"{detail_url(listing_id)}transition/", {"status": "active"}, format="json"
    )
    assert res.status_code == 200
    assert res.data["status"] == ListingStatus.ACTIVE

    # Now visible publicly.
    api_client.force_authenticate(None)
    results = api_client.get(LIST_URL).data["results"]
    assert [r["id"] for r in results] == [listing_id]

    # Mark sold.
    api_client.force_authenticate(verified_user)
    res = api_client.post(
        f"{detail_url(listing_id)}transition/", {"status": "sold"}, format="json"
    )
    assert res.data["status"] == ListingStatus.SOLD


@pytest.mark.django_db
def test_illegal_transition_returns_409(api_client, verified_user, root_category):
    api_client.force_authenticate(verified_user)
    listing_id = api_client.post(
        LIST_URL, new_listing_payload(root_category), format="json"
    ).data["id"]
    # draft -> sold is not allowed.
    res = api_client.post(
        f"{detail_url(listing_id)}transition/", {"status": "sold"}, format="json"
    )
    assert res.status_code == 409
    assert res.data["code"] == "invalid_transition"


@pytest.mark.django_db
def test_non_owner_cannot_edit_or_delete(
    api_client, verified_user, other_user, root_category
):
    api_client.force_authenticate(verified_user)
    listing_id = api_client.post(
        LIST_URL, new_listing_payload(root_category), format="json"
    ).data["id"]

    api_client.force_authenticate(other_user)
    assert api_client.patch(
        detail_url(listing_id), {"title": "Hijacked"}, format="json"
    ).status_code == 403
    assert api_client.delete(detail_url(listing_id)).status_code == 403


@pytest.mark.django_db
def test_edit_updates_fields(api_client, verified_user, root_category):
    api_client.force_authenticate(verified_user)
    listing_id = api_client.post(
        LIST_URL, new_listing_payload(root_category), format="json"
    ).data["id"]
    res = api_client.patch(
        detail_url(listing_id), {"title": "iPhone 13 Pro", "price": "50000.00"}, format="json"
    )
    assert res.status_code == 200
    assert res.data["title"] == "iPhone 13 Pro"
    assert res.data["price"] == "50000.00"


@pytest.mark.django_db
def test_soft_delete_hides_listing(api_client, verified_user, root_category):
    api_client.force_authenticate(verified_user)
    listing_id = api_client.post(
        LIST_URL, new_listing_payload(root_category), format="json"
    ).data["id"]

    assert api_client.delete(detail_url(listing_id)).status_code == 204

    listing = Listing.objects.get(pk=listing_id)
    assert listing.is_deleted is True and listing.deleted_at is not None
    # Gone from the owner's view too.
    assert api_client.get(detail_url(listing_id)).status_code == 404


@pytest.mark.django_db
def test_mine_lists_all_own_statuses(api_client, verified_user, other_user, root_category):
    api_client.force_authenticate(verified_user)
    api_client.post(LIST_URL, new_listing_payload(root_category), format="json")
    # A listing owned by someone else must not appear.
    api_client.force_authenticate(other_user)
    api_client.post(LIST_URL, new_listing_payload(root_category, title="Other"), format="json")

    api_client.force_authenticate(verified_user)
    results = api_client.get(f"{LIST_URL}mine/").data["results"]
    assert len(results) == 1
    assert results[0]["seller"]["id"] == verified_user.id


@pytest.mark.django_db
def test_image_upload_generates_thumbnail(
    api_client, settings, tmp_path, verified_user, root_category
):
    settings.MEDIA_ROOT = tmp_path
    api_client.force_authenticate(verified_user)
    listing_id = api_client.post(
        LIST_URL, new_listing_payload(root_category), format="json"
    ).data["id"]

    res = api_client.post(
        f"{detail_url(listing_id)}images/",
        {"images": make_image()},
        format="multipart",
    )
    assert res.status_code == 201
    assert len(res.data) == 1
    # Eager Celery ran the thumbnail task inline.
    assert res.data[0]["thumbnail"]
