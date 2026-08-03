"""LOAD-BEARING. See core/tests/README.md before changing anything here.

CLAUDE.md §3: "Every tenant-scoped query filters by org. There is no such thing
as a cross-org read outside of admin tooling."

Slice 1 has three org-scoped surfaces. Slice 2 adds shops, staff and services;
slice 3 adds appointments; slice 9 adds revenue. All of them inherit their
isolation from the mixin these tests cover, so a regression here is a
regression everywhere.
"""

import pytest
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.loadbearing]


def test_foreign_org_detail_returns_404_not_403(api_client, org_a, org_b):
    """404, not 403.

    A 403 confirms the organization exists. Since the caller supplied the id,
    a 403 turns this endpoint into an oracle for "is this a real org?". 404 is
    the same answer whether the org is absent or merely not yours.
    """
    api_client.force_login(org_a.owner)

    response = api_client.get(reverse("orgs:org-detail", args=[org_b.organization.id]))

    assert response.status_code == 404


def test_foreign_org_member_list_returns_404(api_client, org_a, org_b):
    api_client.force_login(org_a.owner)

    response = api_client.get(reverse("orgs:member-list", args=[org_b.organization.id]))

    assert response.status_code == 404


def test_foreign_org_invite_list_returns_404(api_client, org_a, org_b):
    api_client.force_login(org_a.owner)

    response = api_client.get(reverse("orgs:invite-list", args=[org_b.organization.id]))

    assert response.status_code == 404


def test_org_list_contains_only_my_orgs(api_client, org_a, org_b):
    api_client.force_login(org_a.owner)

    response = api_client.get(reverse("orgs:org-list"))

    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == [str(org_a.organization.id)]


def test_member_list_never_leaks_another_orgs_people(api_client, org_a, org_b):
    """The isolation that matters: not just the 404, but the contents."""
    api_client.force_login(org_a.owner)

    response = api_client.get(reverse("orgs:member-list", args=[org_a.organization.id]))

    phones = {row["user"]["phone"] for row in response.json()}
    assert org_b.owner.phone not in phones
    assert phones == {org_a.owner.phone, org_a.stylist.phone}


def test_membership_detail_of_another_org_is_404_even_with_a_real_id(api_client, org_a, org_b):
    """Both ids are real; the pairing is not. Guards against looking up the
    membership before checking the org."""
    api_client.force_login(org_a.owner)

    response = api_client.get(
        reverse("orgs:member-detail", args=[org_a.organization.id, org_b.owner_membership.id])
    )

    assert response.status_code == 404


def test_inactive_membership_behaves_as_no_membership(api_client, org_a):
    """Deactivation is how a staff member is removed, so it has to actually
    revoke access — not merely hide the row from a list."""
    membership = org_a.stylist_membership
    membership.is_active = False
    membership.save(update_fields=["is_active"])
    api_client.force_login(org_a.stylist)

    assert (
        api_client.get(reverse("orgs:org-detail", args=[org_a.organization.id])).status_code == 404
    )
    assert api_client.get(reverse("orgs:org-list")).json() == []


def test_anonymous_user_gets_401_or_403_never_data(api_client, org_a):
    response = api_client.get(reverse("orgs:member-list", args=[org_a.organization.id]))

    assert response.status_code in {401, 403}
