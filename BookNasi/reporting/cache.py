"""A short TTL over the aggregates, and nothing over today.

The design is explicit that the owner view wants "cached aggregates — no
realtime requirement", and it is right: a 90-day report is a scan over every
appointment and payment in the range, an owner refreshes it a handful of times
a week, and none of the numbers on it change meaningfully inside five minutes.

## Why a TTL and not invalidation

`scheduling/cache.py` invalidates precisely, because a stale availability read
sells a slot twice. Nothing here can be sold twice. The worst a stale report can
do is show a revenue figure that is one haircut behind, which is a cost of zero,
and the alternative — hooking every appointment, payment, credit and transition
so they can invalidate a range they may or may not fall inside — is a large
amount of machinery whose failure mode (a *missed* invalidation) looks exactly
like the TTL expiring anyway.

## Why today is outside it

The load meters are what an owner opens the page for on a Saturday morning, and
"how full is Thika Road right now" is the one question on this screen where five
minutes is visible. It is also the cheapest thing here: one aggregate and a
weekly-pattern read per shop. So it is recomputed on every request, and the
range aggregates are not.

## What the key has to contain

Everything that changes an answer: the organization, the exact set of shops in
scope, and both dates. Not the user — two managers of the same organization
looking at the same range must not be able to see different numbers, and a
per-user key would hide that if they ever could.
"""

from dataclasses import replace

from django.core.cache import cache

from reporting import metrics

#: Five minutes, matching `scheduling/cache.py`'s TTL. Same reasoning as there:
#: short enough that a stale read is never interesting, long enough that a
#: refresh-happy owner is not re-running a 90-day scan every few seconds.
TTL_SECONDS = 300

#: Bump this whenever the shape of `Report` or anything nested in it changes.
#:
#: Entries are pickled dataclasses, so a deploy that adds a field leaves five
#: minutes of cached objects that unpickle into the new class *without* it, and
#: the first read of that attribute is an AttributeError — a 500 on the owner
#: dashboard for exactly as long as the TTL, immediately after a release, which
#: is the worst possible time to be debugging a cache. A new key namespace makes
#: that impossible: the old entries are simply never read again.
VERSION = 1


def key_for(organization, shop_ids, period):
    shops = ",".join(sorted(str(shop_id) for shop_id in shop_ids))
    return (
        f"report:v{VERSION}:{organization.id}:{shops}:"
        f"{period.starts_on.isoformat()}:{period.ends_on.isoformat()}"
    )


def report_for(*, organization, shops, period, now, today_shops=None, use_cache=True):
    """The whole dashboard: cached aggregates, fresh load meters.

    `shops` is what the aggregates cover — narrowed by `?shop=` when one is
    selected. `today_shops` is every branch, because the load meters double as
    the shop switcher.
    """
    key = key_for(organization, [shop.id for shop in shops], period)
    aggregates = cache.get(key) if use_cache else None
    if aggregates is None:
        # Built without `today`, so a cached entry cannot serve a stale load
        # meter even if this module is later asked to return the cached object
        # directly.
        aggregates = metrics.build_report(
            organization=organization, shops=shops, period=period, now=now, include_today=False
        )
        if use_cache:
            cache.set(key, aggregates, TTL_SECONDS)

    return replace(aggregates, today=metrics.today_for(organization, today_shops or shops, now))
