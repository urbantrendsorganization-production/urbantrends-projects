"""The listing status state machine — every allowed and forbidden edge."""
import pytest

from apps.catalog import services
from apps.catalog.models import Listing, ListingStatus
from apps.catalog.services import ListingStateError

STATUSES = [
    ListingStatus.DRAFT,
    ListingStatus.ACTIVE,
    ListingStatus.RESERVED,
    ListingStatus.SOLD,
    ListingStatus.EXPIRED,
]

ALLOWED = {
    (ListingStatus.DRAFT, ListingStatus.ACTIVE),
    (ListingStatus.ACTIVE, ListingStatus.RESERVED),
    (ListingStatus.ACTIVE, ListingStatus.SOLD),
    (ListingStatus.ACTIVE, ListingStatus.EXPIRED),
    (ListingStatus.RESERVED, ListingStatus.ACTIVE),
    (ListingStatus.RESERVED, ListingStatus.SOLD),
    (ListingStatus.EXPIRED, ListingStatus.ACTIVE),
}


def make_listing(seller, category, status):
    return Listing.objects.create(
        seller=seller,
        category=category,
        title="Thing",
        price="100.00",
        condition="good",
        status=status,
    )


@pytest.mark.django_db
@pytest.mark.parametrize("frm", STATUSES)
@pytest.mark.parametrize("to", STATUSES)
def test_every_transition_edge(verified_user, root_category, frm, to):
    listing = make_listing(verified_user, root_category, frm)

    if frm == to:
        # Same-status is an idempotent no-op, never an error.
        assert services.transition_listing(listing, to).status == to
    elif (frm, to) in ALLOWED:
        assert services.transition_listing(listing, to).status == to
    else:
        with pytest.raises(ListingStateError):
            services.transition_listing(listing, to)
        listing.refresh_from_db()
        assert listing.status == frm  # unchanged on failure


@pytest.mark.django_db
def test_publish_stamps_published_at(verified_user, root_category):
    listing = make_listing(verified_user, root_category, ListingStatus.DRAFT)
    assert listing.published_at is None

    services.transition_listing(listing, ListingStatus.ACTIVE)
    listing.refresh_from_db()
    first_published = listing.published_at
    assert first_published is not None

    # Re-activating from reserved keeps the original published_at.
    services.transition_listing(listing, ListingStatus.RESERVED)
    services.transition_listing(listing, ListingStatus.ACTIVE)
    listing.refresh_from_db()
    assert listing.published_at == first_published


@pytest.mark.django_db
def test_sold_is_terminal(verified_user, root_category):
    listing = make_listing(verified_user, root_category, ListingStatus.SOLD)
    for target in (ListingStatus.ACTIVE, ListingStatus.RESERVED, ListingStatus.DRAFT):
        with pytest.raises(ListingStateError):
            services.transition_listing(listing, target)


@pytest.mark.django_db
def test_unknown_status_rejected(verified_user, root_category):
    from rest_framework.exceptions import ValidationError

    listing = make_listing(verified_user, root_category, ListingStatus.ACTIVE)
    with pytest.raises(ValidationError):
        services.transition_listing(listing, "bogus")
