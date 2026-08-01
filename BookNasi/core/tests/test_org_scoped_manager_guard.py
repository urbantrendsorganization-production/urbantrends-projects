"""LOAD-BEARING. See core/tests/README.md before changing anything here.

The guard in core/managers.py is what makes CLAUDE.md §3 enforceable rather
than aspirational. Every route from an org-scoped queryset to the database has
to be closed, because the one that isn't is the one a future slice will reach
for by accident.
"""

import pytest

from core.managers import CrossTenantQueryError
from orgs.models import Membership, StaffInvite

pytestmark = [pytest.mark.django_db, pytest.mark.loadbearing]

# Every model that inherits OrgScopedModel. Slices 2-11 append to this list;
# a new org-scoped model with no entry here is a gap in the guard.
ORG_SCOPED_MODELS = [Membership, StaffInvite]


@pytest.mark.parametrize("model", ORG_SCOPED_MODELS, ids=lambda m: m.__name__)
class TestEveryRouteToTheDatabaseIsClosed:
    """`_fetch_all` covers iteration. These are the ones that issue their own
    SQL and would otherwise slip past it."""

    def test_iteration_is_blocked(self, model):
        with pytest.raises(CrossTenantQueryError):
            list(model.objects.all())

    def test_count_is_blocked(self, model):
        with pytest.raises(CrossTenantQueryError):
            model.objects.count()

    def test_exists_is_blocked(self, model):
        with pytest.raises(CrossTenantQueryError):
            model.objects.exists()

    def test_first_is_blocked(self, model):
        with pytest.raises(CrossTenantQueryError):
            model.objects.first()

    def test_get_is_blocked(self, model):
        with pytest.raises(CrossTenantQueryError):
            model.objects.get(id="00000000-0000-0000-0000-000000000000")

    def test_aggregate_is_blocked(self, model):
        from django.db.models import Count

        with pytest.raises(CrossTenantQueryError):
            model.objects.aggregate(n=Count("id"))

    def test_update_is_blocked(self, model):
        with pytest.raises(CrossTenantQueryError):
            model.objects.update(updated_at=None)

    def test_delete_is_blocked(self, model):
        with pytest.raises(CrossTenantQueryError):
            model.objects.delete()

    def test_in_bulk_is_blocked(self, model):
        with pytest.raises(CrossTenantQueryError):
            model.objects.in_bulk([])

    def test_a_plain_filter_does_not_count_as_scoping(self, model):
        """Filtering by something that isn't the org must not satisfy the guard.

        This is the realistic mistake: `Membership.objects.filter(user=user)`
        looks scoped, reads as scoped, and returns that user's rows across
        every tenant they touch.
        """
        with pytest.raises(CrossTenantQueryError):
            list(model.objects.filter(id="00000000-0000-0000-0000-000000000000"))


class TestScopingSatisfiesTheGuard:
    def test_for_org_permits_execution(self, org_a):
        assert Membership.objects.for_org(org_a.organization).count() == 2

    def test_scoping_survives_further_filtering(self, org_a):
        """`.for_org(...)` then `.filter(...)` must stay scoped — the flag has
        to survive `_clone`, which is where this kind of guard usually breaks.
        """
        from orgs.models import Role

        qs = Membership.objects.for_org(org_a.organization).filter(role=Role.OWNER)
        assert qs.count() == 1
        assert list(qs)[0].user == org_a.owner

    def test_scoping_survives_exclude_and_order_by(self, org_a):
        from orgs.models import Role

        qs = (
            Membership.objects.for_org(org_a.organization)
            .exclude(role=Role.OWNER)
            .order_by("created_at")
        )
        assert [m.user for m in qs] == [org_a.stylist]

    def test_for_org_returns_only_that_org(self, org_a, org_b):
        users = {m.user for m in Membership.objects.for_org(org_a.organization)}
        assert org_b.owner not in users

    def test_unscoped_is_the_explicit_escape_hatch(self, org_a, org_b):
        """`.unscoped()` works, and is greppable. `grep -rn 'unscoped()' --include=*.py`
        should return a list short enough for a reviewer to read in full."""
        assert Membership.objects.unscoped().count() == 4  # both orgs, owner + stylist each


class TestTheGuardCannotBeOptedOutOfByAccident:
    def test_staff_invite_custom_queryset_still_inherits_the_guard(self):
        """StaffInvite overrides `objects` to add `.pending()`. Building that on
        a plain QuerySet would silently remove the guard from this model."""
        from core.managers import OrgScopedQuerySet

        assert isinstance(StaffInvite.objects.all(), OrgScopedQuerySet)
        with pytest.raises(CrossTenantQueryError):
            list(StaffInvite.objects.pending())

    def test_pending_is_still_usable_when_scoped(self, org_a):
        assert StaffInvite.objects.for_org(org_a.organization).pending().count() == 0

    def test_every_org_scoped_model_is_covered_by_this_file(self):
        """Catches a slice that adds an org-scoped model and forgets to list it.

        Without this, a new model in slice 2 or 3 gets no guard coverage and
        nobody notices until it leaks.
        """
        from django.apps import apps

        from core.models import OrgScopedModel

        discovered = {
            model
            for model in apps.get_models()
            if issubclass(model, OrgScopedModel) and not model._meta.abstract
        }
        missing = discovered - set(ORG_SCOPED_MODELS)
        assert not missing, (
            f"{[m.__name__ for m in missing]} inherit OrgScopedModel but are not listed in "
            "ORG_SCOPED_MODELS at the top of this file. Add them."
        )
