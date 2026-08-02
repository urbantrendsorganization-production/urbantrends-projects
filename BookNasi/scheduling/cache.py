"""Redis in front of `loading.py`. A pure optimisation, and testably so.

The cache holds **facts, not slots** — a `StaffDayFacts` per `(staff_id, EAT
date)`, with no service dimension. Two reasons, and the second is the important
one:

1. The expensive part is the six queries, not the arithmetic. Deriving slots
   from cached facts is a loop over a few dozen datetimes.
2. Keying on `(staff_id, date)` alone is what makes invalidation tractable. If
   the cache held finished slot lists it would need a service dimension, and
   every working-hours edit would have to fan out across every service that
   staff member offers — a set nothing tracks and nothing bounds. Slice 4's day
   view would then be the thing that discovers the miss.

## Correctness

Everything here is allowed to fail. A Redis outage, a missed invalidation, a
serialisation change — all of them degrade to a recomputation, never to a wrong
answer. Two things enforce that:

- `TTL` is short. Anything the choke point in `invalidation.py` somehow misses
  self-heals within five minutes rather than lasting until the next deploy.
- `KEY_VERSION` is in every key. Changing the shape of `StaffDayFacts` means
  bumping it, and the old entries become unreachable rather than
  mis-deserialised.

There is a test that flushes Redis mid-run and asserts the results are identical
either side of the flush. If that test ever needs weakening, the cache has
stopped being an optimisation and has become a source of truth.

## Under a stampede

A shop's WhatsApp link goes out and forty people open the same shop-day at once.
Without protection that is forty concurrent derivations of the same facts —
survivable (six indexed queries each) but wasteful, and it lands on the database
at exactly the moment the shop is most visible.

So reads are **single-flight**: the first caller takes a short lock with
`cache.add()` and computes; the others poll briefly for the winner's result and
then *give up waiting and compute it themselves*. The lock is an optimisation on
top of an optimisation, never a gate. Concretely:

- The winner dying mid-derivation costs the others `POLL_BUDGET` of waiting, not
  a deadlock — the lock also expires on its own.
- Redis being down makes `cache.add` fail, every caller computes, and the answer
  is still right.
- Nobody ever blocks indefinitely, so a slow query cannot turn into a queue of
  stalled web workers.

Because the entry is service-independent, all forty of those requests share one
key even when they are looking at different services — the stampede window is
narrower than it first appears.
"""

import time as time_module

from django.core.cache import cache

from scheduling.availability import local_date
from scheduling.loading import gather_shop_day

#: Bump when the shape of StaffDayFacts changes. v2: slice 4 gave each busy
#: interval an `is_active` flag, so entries written by slice 3 would unpickle
#: into a shape the collision resolver reads wrongly. A version bump is a clean
#: miss; leaving it at v1 would have been a silent five-minute window of
#: availability derived from the wrong facts on every deployed process.
KEY_VERSION = "v2"
#: Short by design — the backstop for an invalidation that did not land.
TTL_SECONDS = 300
LOCK_TTL_SECONDS = 10
#: How long a loser waits for the winner before computing it itself.
POLL_BUDGET_SECONDS = 1.5
POLL_INTERVAL_SECONDS = 0.05


def key_for(staff_id, day):
    """`(staff_id, local_date)`, exactly as specified.

    `day` is an EAT calendar date, and `availability.local_date` is the only
    function that maps an instant onto one — so the key and the engine cannot
    disagree about where a staff-day starts. See decision (e) in
    `availability.py`.
    """
    return f"bn:avail:{KEY_VERSION}:{staff_id}:{day.isoformat()}"


def _lock_key(staff_id, day):
    return f"{key_for(staff_id, day)}:lock"


def facts_for_shop_day(shop, day, *, staff=None, use_cache=True):
    """`{staff_id: StaffDayFacts}`, from cache where possible.

    Missing entries are computed in one batch — `gather_shop_day` costs the same
    six queries for eight staff as for one, so a partial miss is not worth
    splitting.
    """
    staff_rows = list(staff) if staff is not None else list(shop.staff.filter(is_active=True))
    if not use_cache:
        return gather_shop_day(shop, day, staff=staff_rows)

    keys = {row.id: key_for(row.id, day) for row in staff_rows}
    cached = cache.get_many(list(keys.values()))
    found = {sid: cached[k] for sid, k in keys.items() if k in cached}
    missing = [row for row in staff_rows if row.id not in found]
    if not missing:
        return found

    computed = _compute_with_single_flight(shop, day, missing, keys, found)
    return {**found, **computed}


def _compute_with_single_flight(shop, day, missing, keys, already_found):
    """Derive the missing entries, avoiding a herd where it is cheap to do so.

    Deliberately not a correctness mechanism — see the module docstring. Every
    branch here ends in a real answer.
    """
    lock_keys = [_lock_key(row.id, day) for row in missing]
    # One `add` per missing staff member; whoever wins any of them computes the
    # batch. `add` is atomic in the Redis backend and returns False when the key
    # already exists.
    won = any(cache.add(lock, "1", LOCK_TTL_SECONDS) for lock in lock_keys)

    if not won:
        waited = 0.0
        while waited < POLL_BUDGET_SECONDS:
            time_module.sleep(POLL_INTERVAL_SECONDS)
            waited += POLL_INTERVAL_SECONDS
            cached = cache.get_many([keys[row.id] for row in missing])
            if len(cached) == len(missing):
                return {row.id: cached[keys[row.id]] for row in missing}
        # The winner is slow, or died. Compute it ourselves rather than wait
        # any longer: a stalled request is worse than a duplicated query.

    computed = gather_shop_day(shop, day, staff=missing)
    cache.set_many({keys[sid]: facts for sid, facts in computed.items()}, TTL_SECONDS)
    for lock in lock_keys:
        cache.delete(lock)
    return computed


def facts_for_staff_day(staff, day, *, use_cache=True):
    return facts_for_shop_day(staff.shop, day, staff=[staff], use_cache=use_cache)[staff.id]


def forget(staff_id, day):
    """Drop one staff-day. **Call this through `invalidation.py`, never here.**

    Kept private-by-convention rather than private-by-underscore because the
    invalidation module needs it and nothing else does; a `grep` for
    `cache.forget` should return that one caller.
    """
    cache.delete(key_for(staff_id, day))


def forget_many(staff_ids, days):
    keys = [key_for(staff_id, day) for staff_id in staff_ids for day in days]
    if keys:
        cache.delete_many(keys)


__all__ = [
    "facts_for_shop_day",
    "facts_for_staff_day",
    "forget",
    "forget_many",
    "key_for",
    "local_date",
]
