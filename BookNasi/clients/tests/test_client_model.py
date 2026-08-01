"""`Client` belongs to the Organization, not the Shop.

CLAUDE.md §3 calls this one of two shape decisions that are expensive to
reverse: "A regular who visits two branches must be one person with one history.
Never scope `Client` to a `Shop`." Slice 5 builds the booking flow on top of it,
and slice 9's repeat-client rate is meaningless if the same person is two rows.
"""

import pytest
from django.db.utils import IntegrityError

from clients.models import Client
from shops.models import Shop

pytestmark = pytest.mark.django_db


class TestOrgScoping:
    def test_a_client_has_no_shop(self):
        """Structural, not a convention. There is no field to get wrong."""
        assert not hasattr(Client, "shop")
        assert "shop" not in {f.name for f in Client._meta.get_fields()}

    def test_one_person_visiting_two_branches_is_one_record(self, org_a):
        """The reason the FK points at Organization."""
        kilimani = Shop.objects.create(
            organization=org_a.organization, name="Kilimani", slug="mb-kilimani"
        )
        westlands = Shop.objects.create(
            organization=org_a.organization, name="Westlands", slug="mb-westlands"
        )
        client = Client.objects.create(
            organization=org_a.organization, full_name="Amina", phone="0712345678"
        )

        assert kilimani.organization_id == westlands.organization_id == client.organization_id
        assert Client.objects.for_org(org_a.organization).count() == 1

    def test_the_same_number_at_two_organizations_is_two_records(self, org_a, org_b):
        """Two separate controllers under the DPA, and two separate histories.
        Not a bug — deduplicating across tenants would leak one salon's client
        list into another's."""
        Client.objects.create(organization=org_a.organization, phone="0712345678")
        Client.objects.create(organization=org_b.organization, phone="0712345678")

        assert Client.objects.for_org(org_a.organization).count() == 1
        assert Client.objects.for_org(org_b.organization).count() == 1

    def test_the_same_number_twice_in_one_organization_is_refused(self, org_a):
        Client.objects.create(organization=org_a.organization, phone="0712345678")

        with pytest.raises(IntegrityError):
            Client.objects.create(organization=org_a.organization, phone="0712345678")

    def test_another_tenants_client_is_invisible(self, org_a, org_b):
        Client.objects.create(
            organization=org_b.organization, full_name="Theirs", phone="0700000001"
        )

        assert Client.objects.for_org(org_a.organization).count() == 0


class TestPhoneNormalisation:
    @pytest.mark.parametrize(
        "typed", ["0712345678", "712345678", "254712345678", "+254 712 345 678"]
    )
    def test_every_way_of_typing_it_stores_the_same_number(self, org_a, typed):
        """Without this, the same person typing 0712345678 at one branch and
        254712345678 at another becomes two people with half a history each."""
        client = Client.objects.create(organization=org_a.organization, phone=typed)

        assert client.phone == "+254712345678"

    def test_the_uniqueness_constraint_sees_through_the_formatting(self, org_a):
        """The normalisation and the constraint have to agree, or the constraint
        catches nothing."""
        Client.objects.create(organization=org_a.organization, phone="0712345678")

        with pytest.raises(IntegrityError):
            Client.objects.create(organization=org_a.organization, phone="+254 712 345 678")


class TestDisplay:
    def test_a_client_with_no_name_shows_their_number(self, org_a):
        """A walk-in recorded in three taps has a number and nothing else."""
        client = Client.objects.create(organization=org_a.organization, phone="0712345678")

        assert str(client) == "+254712345678"

    def test_a_named_client_shows_their_name(self, org_a):
        client = Client.objects.create(
            organization=org_a.organization, full_name="Amina", phone="0712345678"
        )

        assert str(client) == "Amina"
