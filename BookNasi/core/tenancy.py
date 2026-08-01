"""Resolving the current organization from a request.

The rule that matters: a user who is not a member of an organization gets
**404, not 403**. A 403 confirms the organization exists, which turns the id
space into something worth probing. Since ids are UUIDs the practical risk is
low, but the habit is what protects slices 2-11, where org ids appear in far
more URLs.
"""

from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied

from orgs.models import Membership, Organization, Role

MANAGING_ROLES = frozenset({Role.OWNER, Role.MANAGER})


def memberships_for(user):
    if not user.is_authenticated:
        return Membership.objects.none()
    return Membership.objects.unscoped().filter(user=user, is_active=True)


def organizations_for(user):
    """Organizations this user may act on. The only entry point for org lookup."""
    if not user.is_authenticated:
        return Organization.objects.none()
    return Organization.objects.filter(id__in=memberships_for(user).values("organization_id"))


class OrgScopedMixin:
    """Resolves `self.organization` from the `org_id` URL kwarg."""

    managing_roles_required = False

    @property
    def organization(self):
        if not hasattr(self, "_organization"):
            self._organization = get_object_or_404(
                organizations_for(self.request.user), pk=self.kwargs["org_id"]
            )
        return self._organization

    @property
    def membership(self):
        if not hasattr(self, "_membership"):
            self._membership = memberships_for(self.request.user).get(
                organization=self.organization
            )
        return self._membership

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        # Touching `self.organization` here means the 404 happens before any
        # handler body runs, so a handler can never see an unresolved org.
        organization = self.organization
        if self.managing_roles_required and self.membership.role not in MANAGING_ROLES:
            raise PermissionDenied("Only an owner or manager can do this.")
        return organization
