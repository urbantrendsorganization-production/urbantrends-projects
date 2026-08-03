"""Org-scoped querysets.

CLAUDE.md §3: "Every tenant-scoped query filters by org. There is no such thing
as a cross-org read outside of admin tooling."

That sentence is only true if something enforces it. A convention that every
view remembers to call `.filter(organization=...)` fails the first time someone
adds a viewset in a hurry, and it fails silently — the query returns other
tenants' rows and nothing complains. So the default queryset on an org-scoped
model refuses to execute at all. You either say which org you mean with
`.for_org(org)`, or you say out loud that you mean all of them with
`.unscoped()`.

`.unscoped()` exists for admin tooling, migrations and system jobs. It is
greppable on purpose: `grep -rn unscoped()` should return a short list that a
reviewer can read in full.
"""

from django.db import models


class CrossTenantQueryError(RuntimeError):
    """Raised when an org-scoped queryset is executed without naming an org."""


_MESSAGE = (
    "{model}.objects was executed without an organization filter. Use "
    "`.for_org(org)` to scope it, or `.unscoped()` if you genuinely mean every "
    "tenant (admin tooling and system jobs only). See CLAUDE.md §3."
)


class OrgScopedQuerySet(models.QuerySet):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._org_scoped = False

    def _clone(self, **kwargs):
        clone = super()._clone(**kwargs)
        clone._org_scoped = self._org_scoped
        return clone

    def _assert_scoped(self):
        if not self._org_scoped:
            raise CrossTenantQueryError(_MESSAGE.format(model=self.model.__name__))

    def for_org(self, organization):
        clone = self.filter(organization=organization)
        clone._org_scoped = True
        return clone

    def unscoped(self):
        """Escape hatch for admin tooling, migrations and system jobs."""
        clone = self._clone()
        clone._org_scoped = True
        return clone

    # Every route from a queryset to the database, closed. `_fetch_all` covers
    # iteration and therefore get/first/last/exists-via-iteration; the rest
    # issue their own SQL and would otherwise slip past.
    def _fetch_all(self):
        self._assert_scoped()
        super()._fetch_all()

    def count(self):
        self._assert_scoped()
        return super().count()

    def exists(self):
        self._assert_scoped()
        return super().exists()

    def aggregate(self, *args, **kwargs):
        self._assert_scoped()
        return super().aggregate(*args, **kwargs)

    def update(self, **kwargs):
        self._assert_scoped()
        return super().update(**kwargs)

    def delete(self):
        self._assert_scoped()
        return super().delete()

    def in_bulk(self, *args, **kwargs):
        self._assert_scoped()
        return super().in_bulk(*args, **kwargs)


class OrgScopedManager(models.Manager.from_queryset(OrgScopedQuerySet)):
    use_in_migrations = False
