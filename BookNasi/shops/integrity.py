"""Keeping `Service.deposit_amount` honest on the paths that skip `save()`.

`Service.save()` recomputes the stored deposit from `shops.money.deposit_amount`
every time. Three ORM paths never call it:

- `QuerySet.update()` — issues SQL directly
- `QuerySet.bulk_update()` — issues SQL directly
- `QuerySet.bulk_create()` — inserts whatever is on the instance

A `Service.objects.for_org(org).update(price=6000)` therefore leaves the row
advertising the old deposit. The failure is quiet and expensive in exactly one
direction: the public API shows one figure, slice 6 pushes that same stale
figure to M-Pesa, and the shop under-collects on every booking until somebody
notices. The 12-combination bookability test cannot catch it, because that test
goes through `save()` like all correct code does.

Two nets, deliberately different in kind:

1. **This mixin**, which makes the bypass either impossible or correct.
2. **A check constraint** (`service_deposit_amount_within_price`, in
   `shops/models.py`), which catches the subset the database can see on its own
   — a deposit larger than the price, or a non-zero deposit on a `none` mode
   service. It cannot catch a percentage that has merely drifted, because
   expressing the rounding rule in SQL would be a second implementation of the
   money arithmetic, which is the thing `shops/money.py` exists to prevent.

Where the two paths differ:

- `bulk_create` and `bulk_update` **recompute**, exactly as `save()` does,
  extending `fields` the way `save()` extends `update_fields`. The rows are in
  memory, so there is nothing to refuse.
- `update()` **refuses**. A single SQL statement cannot round half-up, apply the
  shop floor and clamp to price without restating all of it in SQL. Refusing is
  the honest answer; the error names the alternative.
"""

from contextvars import ContextVar

from django.db import models

from shops.money import deposit_amount

#: Django implements `bulk_update()` in terms of `.update()`, so the refusal
#: below would fire on our own recomputed write. This marks the short window
#: inside `bulk_update` where the values have already been put right and the
#: generated SQL may pass. A ContextVar rather than an instance attribute
#: because `bulk_update` re-derives its own queryset internally, and rather than
#: a module global because the concurrency tests in slice 3 run real threads.
_already_recomputed = ContextVar("booknasi_deposit_recomputed", default=False)

#: Change any of these and the stored deposit is no longer what the one function
#: would return.
DEPOSIT_INPUTS = frozenset({"price", "deposit_mode", "deposit_value"})
DEPOSIT_OUTPUT = "deposit_amount"


class StaleDepositError(RuntimeError):
    """A bulk write would have left `Service.deposit_amount` disagreeing with
    `shops.money.deposit_amount`."""


def recompute_deposit(service):
    """The one recomputation, used by every path that is not `save()`.

    Reads the shop's floor, so it needs `service.shop` — already in memory on
    anything built for `bulk_create`, and one query otherwise.
    """
    service.deposit_amount = deposit_amount(
        mode=service.deposit_mode,
        value=service.deposit_value,
        price=service.price,
        minimum=service.shop.min_deposit_amount,
    )
    return service


class DepositIntegrityMixin:
    """Mixed into both of Service's querysets — the guarded `objects` and the
    unguarded `all_objects`. Leaving it off `all_objects` would leave the whole
    bypass open through the manager Django's own internals use.

    A plain mixin rather than a `QuerySet` subclass so the MRO stays obvious
    when it is combined with `OrgScopedQuerySet`.
    """

    def update(self, **kwargs):
        touched = (DEPOSIT_INPUTS | {DEPOSIT_OUTPUT}) & set(kwargs)
        if touched and not _already_recomputed.get():
            raise StaleDepositError(
                f"update() cannot set {sorted(touched)} on Service: the stored deposit is "
                "computed by shops.money.deposit_amount and a single SQL statement cannot "
                "reproduce its rounding, floor and clamp. Load the rows and save() them, or "
                "use bulk_update(), which recomputes."
            )
        return super().update(**kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        fields = list(fields)
        if DEPOSIT_OUTPUT in fields:
            raise StaleDepositError(
                "deposit_amount is derived and never written directly. Set price, deposit_mode "
                "or deposit_value and it will be recomputed."
            )
        if DEPOSIT_INPUTS & set(fields):
            objs = [recompute_deposit(obj) for obj in objs]
            # Mirrors what save() does to update_fields: the derived column has
            # to travel with the inputs or the write is only half applied.
            fields.append(DEPOSIT_OUTPUT)
        token = _already_recomputed.set(True)
        try:
            return super().bulk_update(objs, fields, **kwargs)
        finally:
            _already_recomputed.reset(token)

    def bulk_create(self, objs, *args, **kwargs):
        objs = [recompute_deposit(obj) for obj in objs]
        return super().bulk_create(objs, *args, **kwargs)


class UnguardedServiceQuerySet(DepositIntegrityMixin, models.QuerySet):
    """What `Service.all_objects` returns. No tenancy guard — that is the point
    of `all_objects`, see core/models.py — but the deposit guard still applies,
    because a stale deposit is wrong for every tenant equally."""
