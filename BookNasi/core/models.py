import uuid

from django.db import models

from core.managers import OrgScopedManager


class TimeStampedModel(models.Model):
    """UUID primary keys throughout.

    Sequential integer ids leak tenant volume and make org and appointment ids
    guessable from the outside — and slice 5 puts appointment ids in URLs that
    are opened from an SMS by someone with no login.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class OrgScopedModel(TimeStampedModel):
    """Anything that belongs to one tenant. See core/managers.py."""

    organization = models.ForeignKey(
        "orgs.Organization",
        on_delete=models.CASCADE,
        related_name="%(class)ss",
    )

    #: What *Django* uses, and nothing else should.
    #:
    #: Declared **first** on purpose. Django's `_default_manager` is the manager
    #: with the lowest creation counter unless `Meta.default_manager_name` says
    #: otherwise — and that setting does not survive into subclasses, because
    #: every concrete model below defines its own `Meta` for `db_table` and
    #: constraints. Declaration order is the only thing that reliably carries.
    #:
    #: `Model.full_clean()` validates unique constraints through
    #: `_default_manager`, and reverse accessors (`shop.services`) are built
    #: from the same class. Pointing those at the guarded manager makes the
    #: admin, model validation and DRF's relation fields raise
    #: CrossTenantQueryError on perfectly legitimate work.
    #:
    #: Both are safe to leave unguarded. A uniqueness check *must* look across
    #: tenants — a globally unique shop slug is the whole point — and a reverse
    #: accessor is already scoped by the parent row it hangs off, which belongs
    #: to exactly one organization.
    #:
    #: `objects` stays guarded, so `Membership.objects.all()` still raises.
    all_objects = models.Manager()

    #: What application code uses. Refuses to execute unscoped.
    objects = OrgScopedManager()

    class Meta:
        abstract = True


class OrgDerivedModel(OrgScopedModel):
    """Org-scoped, but the org comes from a parent row rather than the request.

    Everything under a Shop carries its own `organization` column. That is a
    denormalisation — it could be reached by joining through shop — and it is
    deliberate: the slice 1 guard only protects models that have the column, so
    without it `OpeningHours.objects.all()` would be an unguarded cross-tenant
    read. One UUID per row buys uniform enforcement and turns every tenant
    query into a filter rather than a join.

    The column is never settable through the API. It is derived here, on every
    save, from whichever parent `org_source` names.
    """

    org_source = None

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        parent = getattr(self, self.org_source, None)
        if parent is not None:
            self.organization = parent.organization
            # Partial saves have to carry the derived column too. Reparenting a
            # row to another shop is not a supported operation, but if it ever
            # happens through a `save(update_fields=["shop"])` the organization
            # must not be left pointing at the old tenant.
            update_fields = kwargs.get("update_fields")
            if update_fields is not None and "organization" not in update_fields:
                kwargs["update_fields"] = [*update_fields, "organization"]
        return super().save(*args, **kwargs)
