"""LOAD-BEARING. See core/tests/README.md before changing anything here.

The guard in core/managers.py is what makes CLAUDE.md §3 enforceable rather
than aspirational. Every route from an org-scoped queryset to the database has
to be closed, because the one that isn't is the one a future slice will reach
for by accident.
"""

import pytest

from clients.models import Client
from core.managers import CrossTenantQueryError
from notifications.models import Message
from orgs.models import Membership, StaffInvite
from payments.models import Credit, CreditRedemption, Payment, PaymentMove
from scheduling.models import Appointment
from shops.models import (
    Leave,
    OpeningHours,
    Service,
    Shop,
    ShopClosure,
    Staff,
    StaffService,
    WorkingHours,
)

pytestmark = [pytest.mark.django_db, pytest.mark.loadbearing]

# Every model that inherits OrgScopedModel. Slices 2-11 append to this list;
# a new org-scoped model with no entry here is a gap in the guard, and
# `test_every_org_scoped_model_is_covered_by_this_file` at the bottom fails
# until it is added.
ORG_SCOPED_MODELS = [
    # slice 1
    Membership,
    StaffInvite,
    # slice 2
    Shop,
    OpeningHours,
    ShopClosure,
    Staff,
    WorkingHours,
    Leave,
    Service,
    StaffService,
    # slice 3
    Client,
    Appointment,
    # slice 6. `MpesaCallback` is deliberately absent: it is not org-scoped,
    # because an unmatched callback belongs to no tenant. See its docstring.
    Payment,
    PaymentMove,
    Message,
    # slice 7. Credit is a shop's liability to one client, and a redemption is
    # where it went — both carry money and both are org-derived, so both are
    # exactly the kind of row a cross-tenant read must never reach.
    Credit,
    CreditRedemption,
]


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


@pytest.mark.parametrize("model", ORG_SCOPED_MODELS, ids=lambda m: m.__name__)
class TestTheUnguardedDefaultManager:
    """`all_objects` exists because Django's own machinery needs it.

    `Model.full_clean()` validates unique constraints through `_default_manager`,
    and reverse accessors are built from the same class, so pointing those at the
    guarded manager makes the admin and model validation raise on legitimate
    work. The important thing is that this did not quietly unguard `objects`.
    """

    def test_objects_is_still_the_guarded_one(self, model):
        with pytest.raises(CrossTenantQueryError):
            list(model.objects.all())

    def test_all_objects_is_the_unguarded_one(self, model):
        assert model.all_objects.count() >= 0

    def test_django_resolves_internals_through_the_unguarded_manager(self, model):
        assert model._meta.default_manager.name == "all_objects"

    def test_application_code_never_uses_all_objects(self, model):
        """`all_objects` is for Django, `.unscoped()` is for us. Keeping
        application code on one spelling means `grep -rn 'unscoped()'` still
        returns the complete list of deliberate cross-tenant reads.

        Parsed rather than grepped. A regex over the source flags the *prose* —
        every docstring in shops/integrity.py that explains why the bypass is
        closed reads as a use of it — and a test that cannot tell code from a
        comment about code gets weakened until it means nothing.
        """
        import ast
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[2]
        offenders = []
        for path in root.glob("*/*.py"):
            if "test" in path.name or path.parts[-2] in {"migrations", "tests"}:
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                # `Model.all_objects...` — attribute *access*. An assignment
                # target (`all_objects = Manager()`) is a Name, and
                # `Meta.default_manager_name = "all_objects"` is a string; both
                # are how it is wired up rather than a query through it.
                if isinstance(node, ast.Attribute) and node.attr == "all_objects":
                    offenders.append(f"{path.relative_to(root)}:{node.lineno}")
        assert not offenders, f"use .unscoped() instead of .all_objects in {offenders}"


class TestFullCleanStillWorks:
    """The regression that motivated `all_objects`: model validation performs a
    uniqueness query, which the guard was refusing to run."""

    def test_full_clean_on_an_org_scoped_model_does_not_raise_the_guard(self, shop_setup):
        from shops.models import Service

        service = Service.all_objects.get(pk=shop_setup.braids.pk)
        service.full_clean()  # must not raise CrossTenantQueryError

    def test_full_clean_still_reports_real_validation_errors(self, shop_setup):
        from django.core.exceptions import ValidationError

        from shops.models import StaffService

        link = StaffService.objects.for_org(shop_setup.organization).first()
        link.duration_override_minutes = 0

        with pytest.raises(ValidationError):
            link.full_clean()


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
