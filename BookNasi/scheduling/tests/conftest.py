"""Fixtures for the availability tests.

Everything is anchored to a **fixed date** rather than to `today`. A test that
says "book at 10:00 tomorrow" passes for a year and then fails on the day
tomorrow is a Sunday, and the failure looks like a scheduling bug rather than a
fixture bug. `now` is passed into the engine explicitly for the same reason —
see the docstring in `scheduling/availability.py`.
"""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from scheduling.availability import LOCAL_TZ

#: A Wednesday. The `shop_setup` fixture opens Monday-Saturday, so this is an
#: ordinary trading day with nothing special about it.
WEDNESDAY = date(2026, 9, 9)
#: The Sunday of the same week — the fixture shop is shut.
SUNDAY = date(2026, 9, 13)
UTC = ZoneInfo("UTC")


def eat(day, hour, minute=0):
    """An EAT wall-clock moment on `day`, as the UTC instant we store."""
    return datetime.combine(day, time(hour, minute), tzinfo=LOCAL_TZ).astimezone(UTC)


@pytest.fixture
def wednesday():
    return WEDNESDAY


@pytest.fixture
def early(wednesday):
    """A `now` well before the shop opens, so lead time never interferes with a
    test that is about something else."""
    return eat(wednesday, 5, 0)


@pytest.fixture
def clear_cache():
    from django.core.cache import cache

    cache.clear()
    yield cache
    cache.clear()
