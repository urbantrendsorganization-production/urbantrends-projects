"""LOAD-BEARING. The cache must be a pure optimisation.

The proof is the same shape throughout: run something with the cache, run it
again with Redis emptied underneath, and assert the answers are *identical*. If
these ever need weakening, the cache has stopped being an optimisation and has
become a source of truth — at which point a Redis eviction becomes a
double-booking.

`test_invalidation.py`'s job is that stale entries get dropped. This file's job
is that it would not matter as much as it looks if one did not.
"""

from datetime import time, timedelta

import pytest
from django.core.cache import cache

from scheduling import cache as availability_cache
from scheduling.availability import Policy, derive_slots
from scheduling.cache import facts_for_shop_day, facts_for_staff_day, key_for
from scheduling.loading import gather_shop_day, gather_staff_day
from scheduling.models import Appointment
from scheduling.statuses import AppointmentStatus, BookingSource
from scheduling.tests.conftest import eat
from shops.models import ShopClosure, WorkingHours

pytestmark = [pytest.mark.django_db, pytest.mark.loadbearing]

NO_POLICY = Policy()


def slots(facts, duration, day):
    return derive_slots(facts, duration_minutes=duration, policy=NO_POLICY, now=eat(day, 5))


class TestTheCacheChangesNothing:
    def test_cached_and_uncached_facts_are_equal(self, shop_setup, wednesday, clear_cache):
        uncached = gather_staff_day(shop_setup.wanjiku, wednesday)
        cached = facts_for_staff_day(shop_setup.wanjiku, wednesday)
        again = facts_for_staff_day(shop_setup.wanjiku, wednesday)  # now a hit

        assert cached == uncached
        assert again == uncached

    def test_flushing_redis_mid_run_changes_no_answer(self, shop_setup, wednesday, clear_cache):
        """The test the module docstring is about. Everything derived before the
        flush must survive it byte for byte."""
        before = slots(facts_for_staff_day(shop_setup.wanjiku, wednesday), 60, wednesday)

        cache.clear()

        after = slots(facts_for_staff_day(shop_setup.wanjiku, wednesday), 60, wednesday)
        no_cache = slots(
            facts_for_staff_day(shop_setup.wanjiku, wednesday, use_cache=False), 60, wednesday
        )

        assert before == after == no_cache
        assert before  # and it is not vacuously equal because all three are empty

    def test_a_flush_between_writes_still_gives_the_truth(self, shop_setup, wednesday, clear_cache):
        """The dangerous ordering: warm the cache, write, flush, read. A cache
        that were load-bearing would answer from a pre-write entry here."""
        facts_for_staff_day(shop_setup.wanjiku, wednesday)  # warm

        start = eat(wednesday, 10)
        Appointment.objects.create(
            shop=shop_setup.shop,
            staff=shop_setup.wanjiku,
            service=shop_setup.braids,
            time_range=(start, start + timedelta(hours=1)),
            status=AppointmentStatus.CONFIRMED,
            source=BookingSource.STAFF,
            price_snapshot=3500,
            deposit_snapshot=875,
            duration_snapshot=60,
        )
        cache.clear()

        after = slots(facts_for_staff_day(shop_setup.wanjiku, wednesday), 60, wednesday)

        assert start not in [s.starts_at for s in after]

    def test_a_shop_day_matches_its_uncached_equivalent(self, shop_setup, wednesday, clear_cache):
        everyone = list(shop_setup.shop.staff.filter(is_active=True))

        cached = facts_for_shop_day(shop_setup.shop, wednesday, staff=everyone)
        uncached = gather_shop_day(shop_setup.shop, wednesday, staff=everyone)

        assert cached == uncached

    def test_a_partial_hit_is_completed_correctly(self, shop_setup, wednesday, clear_cache):
        """One stylist warm, one cold. The batch has to fill the gap without
        disturbing the entry it already has."""
        facts_for_staff_day(shop_setup.wanjiku, wednesday)

        both = facts_for_shop_day(shop_setup.shop, wednesday)
        uncached = gather_shop_day(shop_setup.shop, wednesday)

        assert both == uncached
        assert set(both) == {shop_setup.wanjiku.id, shop_setup.grace.id}

    def test_a_closed_day_caches_as_closed_not_as_missing(self, shop_setup, wednesday, clear_cache):
        """A day with no availability is a real answer and must cache like one.
        Storing nothing would make every Sunday a permanent miss."""
        ShopClosure.objects.create(shop=shop_setup.shop, starts_on=wednesday, ends_on=wednesday)
        cache.clear()

        first = facts_for_staff_day(shop_setup.wanjiku, wednesday)
        assert cache.get(key_for(shop_setup.wanjiku.id, wednesday)) is not None

        assert first.window is None
        assert facts_for_staff_day(shop_setup.wanjiku, wednesday).window is None


class TestTheCacheIsActuallyUsed:
    """The other half. A cache that is transparently correct because it never
    stores anything would pass every test above."""

    def test_a_second_read_costs_no_queries(
        self, shop_setup, wednesday, clear_cache, django_assert_num_queries
    ):
        facts_for_staff_day(shop_setup.wanjiku, wednesday)

        with django_assert_num_queries(0):
            facts_for_staff_day(shop_setup.wanjiku, wednesday)

    def test_the_key_is_staff_and_local_date(self, shop_setup, wednesday):
        key = key_for(shop_setup.wanjiku.id, wednesday)

        assert str(shop_setup.wanjiku.id) in key
        assert wednesday.isoformat() in key
        # No service dimension — that is what keeps invalidation tractable.
        assert str(shop_setup.braids.id) not in key

    def test_two_staff_do_not_share_an_entry(self, shop_setup, wednesday):
        assert key_for(shop_setup.wanjiku.id, wednesday) != key_for(shop_setup.grace.id, wednesday)

    def test_two_days_do_not_share_an_entry(self, shop_setup, wednesday):
        assert key_for(shop_setup.wanjiku.id, wednesday) != key_for(
            shop_setup.wanjiku.id, wednesday + timedelta(days=1)
        )

    def test_entries_expire(self, shop_setup, wednesday, clear_cache):
        """The backstop for an invalidation that did not land. Short enough that
        a missed one self-heals in minutes rather than at the next deploy."""
        assert availability_cache.TTL_SECONDS <= 600


class TestUnderAStampede:
    #: `transaction=True` because the reader threads open their own connections.
    #: Under the default non-transactional fixture the shop lives in the main
    #: thread's uncommitted transaction and every other thread would derive an
    #: empty day — a green test that proved nothing.
    @pytest.mark.django_db(transaction=True)
    def test_forty_concurrent_readers_all_get_the_same_answer(
        self, shop_setup, wednesday, clear_cache
    ):
        """A shop's WhatsApp link goes out and everyone opens the same day.

        The single-flight lock is an optimisation on top of an optimisation: the
        assertion here is not that only one thread queried, it is that all forty
        got the right answer. A caller that gives up waiting and computes for
        itself is a correct outcome, and the design prefers it to a stalled
        request.
        """
        import threading

        from django.db import connections

        expected = gather_staff_day(shop_setup.wanjiku, wednesday)
        cache.clear()

        results = []
        barrier = threading.Barrier(40)

        def read():
            try:
                barrier.wait()
                results.append(facts_for_staff_day(shop_setup.wanjiku, wednesday))
            finally:
                connections.close_all()

        threads = [threading.Thread(target=read) for _ in range(40)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert len(results) == 40
        assert all(facts == expected for facts in results)

    def test_a_reader_never_blocks_indefinitely(self, shop_setup, wednesday, clear_cache):
        """A held lock whose owner never finishes must not stall a request. The
        poll budget is bounded and the caller falls through to computing it."""
        from scheduling.cache import _lock_key

        cache.add(_lock_key(shop_setup.wanjiku.id, wednesday), "1", 60)

        facts = facts_for_staff_day(shop_setup.wanjiku, wednesday)

        assert facts == gather_staff_day(shop_setup.wanjiku, wednesday)
        assert availability_cache.POLL_BUDGET_SECONDS <= 3

    def test_a_dead_lock_holder_does_not_poison_the_key(self, shop_setup, wednesday, clear_cache):
        """The lock has its own TTL, so a process that died mid-derivation costs
        one poll budget rather than a permanently unreadable staff-day."""
        assert availability_cache.LOCK_TTL_SECONDS <= 30


class TestCacheFailureDegradesToTheTruth:
    def test_a_cache_that_raises_on_read_still_answers(
        self, shop_setup, wednesday, clear_cache, monkeypatch
    ):
        """Redis being unreachable must be a latency event, not an outage.

        Not currently handled inside `cache.py` — Django's Redis backend raises
        rather than swallowing — so this test documents the actual behaviour
        rather than asserting a graceful path that does not exist. It is here so
        that the day someone adds `IGNORE_EXCEPTIONS`, the change shows up as
        this test flipping rather than as a silent behaviour change.
        """
        from django.core.cache.backends.base import CacheKeyWarning  # noqa: F401

        def boom(*args, **kwargs):
            raise ConnectionError("redis is down")

        monkeypatch.setattr(cache, "get_many", boom)

        with pytest.raises(ConnectionError):
            facts_for_staff_day(shop_setup.wanjiku, wednesday)

        # ... and the bypass is always available and always correct.
        assert facts_for_staff_day(
            shop_setup.wanjiku, wednesday, use_cache=False
        ) == gather_staff_day(shop_setup.wanjiku, wednesday)


class TestFactsSurviveTheRoundTrip:
    def test_every_field_comes_back_intact(self, shop_setup, wednesday, clear_cache):
        """Serialisation is the quiet failure: a field that does not survive the
        round trip produces availability that is wrong only after a cache hit,
        which is exactly the bug that never reproduces locally."""
        WorkingHours.objects.for_org(shop_setup.organization).filter(
            staff=shop_setup.wanjiku, weekday=wednesday.weekday()
        ).update(starts_at=time(9, 30), ends_at=time(17, 30))
        cache.clear()

        direct = gather_staff_day(shop_setup.wanjiku, wednesday)
        facts_for_staff_day(shop_setup.wanjiku, wednesday)
        round_tripped = facts_for_staff_day(shop_setup.wanjiku, wednesday)

        assert round_tripped == direct
        assert round_tripped.staff_window == direct.staff_window
        assert round_tripped.buffer_minutes == direct.buffer_minutes
        assert round_tripped.slot_interval_minutes == direct.slot_interval_minutes
        assert round_tripped.day == direct.day

    def test_busy_intervals_survive(self, shop_setup, wednesday, clear_cache):
        start = eat(wednesday, 11)
        Appointment.objects.create(
            shop=shop_setup.shop,
            staff=shop_setup.wanjiku,
            service=shop_setup.braids,
            time_range=(start, start + timedelta(hours=2)),
            status=AppointmentStatus.CONFIRMED,
            source=BookingSource.STAFF,
            price_snapshot=3500,
            deposit_snapshot=875,
            duration_snapshot=120,
        )
        cache.clear()

        facts_for_staff_day(shop_setup.wanjiku, wednesday)
        hit = facts_for_staff_day(shop_setup.wanjiku, wednesday)

        assert len(hit.busy) == 1
        assert hit.busy[0].starts_at == start
