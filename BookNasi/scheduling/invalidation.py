"""The one place a cached staff-day is dropped.

The invalidation surface is wide — nine models across two apps can change what
`derive_slots` returns — so the risk is not that somebody forgets a
`cache.delete()`, it is that thirty scattered `cache.delete()` calls drift out of
agreement about what key to build. Everything therefore routes through
`invalidate_staff_days` and `invalidate_shop_days` below, and the receivers at
the bottom are the only subscribers.

`grep -rn "cache.forget" scheduling/` should return this file and nothing else.

## Why signals rather than explicit calls

CLAUDE.md and slice 2 both fix the dependency direction: `scheduling -> shops`,
never back. A `cache.delete()` inside `OpeningHours.save()` would invert it and
make the shops app un-testable without Redis. Signals let this module *listen*
to shops without shops knowing it exists — the import arrow still points one
way, and deleting the whole `scheduling` app would leave slice 2 working.

## Why explicit deletes rather than a generation counter

A generation counter (`INCR` a per-staff integer, fold it into the key) makes a
working-hours change O(1) instead of O(horizon). It also has a failure mode that
disqualifies it here: if Redis evicts the counter under memory pressure it
restarts at a lower number, and *previously invalidated entries become live
again*. A resurrected availability entry is a double-booking waiting to happen.
Deleting real keys has no such mode — a delete either happens or the entry
expires on its own within `cache.TTL_SECONDS`.

The cost is bounded and small: a working-hours edit deletes at most
`HORIZON_DAYS` keys, and a shop-hours edit at most `HORIZON_DAYS × staff`, in
one `delete_many`. For eight stylists over ninety days that is 720 keys in a
single round trip, on an action an owner performs a handful of times a year.
"""

from datetime import date, timedelta

from django.db.models.signals import post_delete, post_save
from django.utils import timezone

from scheduling.availability import local_date
from scheduling.cache import forget_many

#: Far enough to cover any shop's `booking_horizon_days` (capped at 365 by a
#: check constraint) without unpacking each shop's own setting at signal time.
#: Deleting a key that was never there costs nothing.
HORIZON_DAYS = 366


def _days_from_today(count=HORIZON_DAYS):
    today = local_date(timezone.now())
    # Yesterday included: a long appointment started before local midnight is
    # still in yesterday's cached facts.
    return [today + timedelta(days=offset) for offset in range(-1, count)]


def invalidate_staff_days(staff_ids, days=None):
    """The choke point. `days=None` means every cached day in the horizon."""
    staff_ids = [sid for sid in staff_ids if sid is not None]
    if not staff_ids:
        return
    forget_many(staff_ids, days if days is not None else _days_from_today())


def invalidate_shop_days(shop, days=None):
    """Everything at a shop. Used for changes that are not staff-specific:
    opening hours, closures, the buffer, the slot grid."""
    invalidate_staff_days(list(shop.staff.values_list("id", flat=True)), days)


def _as_date(value):
    """Django does not coerce a `DateField` until the row is read back.

    `Leave(starts_on="2026-08-03")` keeps the string on the instance right
    through `post_save`, so a receiver that assumes a `date` raises `TypeError`
    *after* a perfectly good write — turning a valid save into a 500 rather than
    a stale cache entry. Cheap to accept both; expensive not to.
    """
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _dates_covered(starts_on, ends_on):
    """Every EAT date in an inclusive range, for closures and leave."""
    starts_on, ends_on = _as_date(starts_on), _as_date(ends_on)
    span = (ends_on - starts_on).days
    return [starts_on + timedelta(days=offset) for offset in range(span + 1)]


# --- receivers -------------------------------------------------------------
#
# Registered from SchedulingConfig.ready(). Each one answers a single question:
# whose days did this write change?


def on_appointment_write(sender, instance, **kwargs):
    """The only narrow one: an appointment touches exactly one staff-day.

    Both ends of the range, because an appointment that crosses local midnight
    is not expressible today (see availability.py, decision (e)) but a
    reschedule out of one day and into another still touches two.
    """
    days = {local_date(instance.starts_at), local_date(instance.ends_at)}
    invalidate_staff_days([instance.staff_id], sorted(days))


def on_working_hours_write(sender, instance, **kwargs):
    invalidate_staff_days([instance.staff_id])


def on_leave_write(sender, instance, **kwargs):
    invalidate_staff_days([instance.staff_id], _dates_covered(instance.starts_on, instance.ends_on))


def on_staff_write(sender, instance, **kwargs):
    """Deactivating or un-booking a staff member removes them from the shop
    day view, so the shop's other entries are unaffected but theirs must go."""
    invalidate_staff_days([instance.id])


def on_staff_service_write(sender, instance, **kwargs):
    """A duration override changes the slot set for one person only."""
    invalidate_staff_days([instance.staff_id])


def on_opening_hours_write(sender, instance, **kwargs):
    invalidate_shop_days(instance.shop)


def on_closure_write(sender, instance, **kwargs):
    invalidate_shop_days(instance.shop, _dates_covered(instance.starts_on, instance.ends_on))


def on_shop_write(sender, instance, **kwargs):
    """Buffer, slot interval, lead time and horizon all live on Shop, and any
    of them changes every slot at every chair."""
    invalidate_shop_days(instance)


def on_service_write(sender, instance, **kwargs):
    """A service duration change moves the slot set for every staff member who
    offers it — including the ones with no override, who inherit it."""
    staff_ids = list(instance.staff_links.values_list("staff_id", flat=True))
    invalidate_staff_days(staff_ids)


#: `(signal receiver, model path)`. A list rather than decorators so that the
#: full invalidation surface is readable in one screen, which is the only way a
#: reviewer can tell that something is missing from it.
RECEIVERS = [
    (on_appointment_write, "scheduling.Appointment"),
    (on_working_hours_write, "shops.WorkingHours"),
    (on_leave_write, "shops.Leave"),
    (on_staff_write, "shops.Staff"),
    (on_staff_service_write, "shops.StaffService"),
    (on_opening_hours_write, "shops.OpeningHours"),
    (on_closure_write, "shops.ShopClosure"),
    (on_shop_write, "shops.Shop"),
    (on_service_write, "shops.Service"),
]


def connect():
    """Called from `SchedulingConfig.ready()`."""
    for receiver, model in RECEIVERS:
        uid = f"booknasi_avail_{receiver.__name__}"
        post_save.connect(receiver, sender=model, dispatch_uid=f"{uid}_save")
        post_delete.connect(receiver, sender=model, dispatch_uid=f"{uid}_delete")
