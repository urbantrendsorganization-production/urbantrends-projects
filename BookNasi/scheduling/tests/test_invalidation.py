"""Every write that changes availability drops the cached staff-day.

The surface is wide — nine models across two apps — so the test that matters
most is the last one in this file: it walks `invalidation.RECEIVERS` and asserts
that nothing which feeds the engine has been left off it. A new field on Shop or
a new model under Staff should fail that test rather than produce availability
that is quietly a few minutes out of date.

`test_cache.py` proves a missed invalidation would not be catastrophic. This
proves there are not any.
"""

from datetime import time, timedelta

import pytest
from django.core.cache import cache

from scheduling import invalidation
from scheduling.cache import facts_for_staff_day, key_for
from scheduling.models import Appointment
from scheduling.statuses import AppointmentStatus, BookingSource
from scheduling.tests.conftest import eat
from shops.models import Leave, OpeningHours, ShopClosure, StaffService, WorkingHours

pytestmark = pytest.mark.django_db


@pytest.fixture
def warm(shop_setup, wednesday, clear_cache):
    """Both stylists cached for the day under test."""
    facts_for_staff_day(shop_setup.wanjiku, wednesday)
    facts_for_staff_day(shop_setup.grace, wednesday)
    return shop_setup


def cached(staff, day):
    return cache.get(key_for(staff.id, day)) is not None


class TestAppointmentWrites:
    def test_creating_an_appointment_drops_that_staff_day(self, warm, wednesday):
        start = eat(wednesday, 10)
        Appointment.objects.create(
            shop=warm.shop,
            staff=warm.wanjiku,
            service=warm.braids,
            time_range=(start, start + timedelta(hours=1)),
            status=AppointmentStatus.CONFIRMED,
            source=BookingSource.STAFF,
            price_snapshot=3500,
            deposit_snapshot=875,
            duration_snapshot=60,
        )

        assert not cached(warm.wanjiku, wednesday)
        # And nobody else's — an appointment is the one narrow case.
        assert cached(warm.grace, wednesday)

    def test_cancelling_drops_it_again(self, warm, wednesday):
        start = eat(wednesday, 10)
        appointment = Appointment.objects.create(
            shop=warm.shop,
            staff=warm.wanjiku,
            service=warm.braids,
            time_range=(start, start + timedelta(hours=1)),
            status=AppointmentStatus.CONFIRMED,
            source=BookingSource.STAFF,
            price_snapshot=3500,
            deposit_snapshot=875,
            duration_snapshot=60,
        )
        facts_for_staff_day(warm.wanjiku, wednesday)  # re-warm

        appointment.status = AppointmentStatus.CANCELLED
        appointment.save(update_fields=["status"])

        assert not cached(warm.wanjiku, wednesday)

    def test_deleting_drops_it(self, warm, wednesday):
        start = eat(wednesday, 10)
        appointment = Appointment.objects.create(
            shop=warm.shop,
            staff=warm.wanjiku,
            service=warm.braids,
            time_range=(start, start + timedelta(hours=1)),
            status=AppointmentStatus.CONFIRMED,
            source=BookingSource.STAFF,
            price_snapshot=3500,
            deposit_snapshot=875,
            duration_snapshot=60,
        )
        facts_for_staff_day(warm.wanjiku, wednesday)

        appointment.delete()

        assert not cached(warm.wanjiku, wednesday)


class TestConfigurationWrites:
    def test_working_hours_drop_that_staff_member(self, warm, wednesday):
        WorkingHours.objects.for_org(warm.organization).filter(
            staff=warm.wanjiku, weekday=wednesday.weekday()
        ).first().save()

        assert not cached(warm.wanjiku, wednesday)
        assert cached(warm.grace, wednesday)

    def test_leave_drops_only_the_days_it_covers(self, warm, wednesday):
        far = wednesday + timedelta(days=40)
        facts_for_staff_day(warm.wanjiku, far)

        Leave.objects.create(staff=warm.wanjiku, starts_on=wednesday, ends_on=wednesday)

        assert not cached(warm.wanjiku, wednesday)
        assert cached(warm.wanjiku, far)

    def test_a_staff_service_override_drops_that_staff_member(self, warm, wednesday):
        link = StaffService.objects.for_org(warm.organization).filter(staff=warm.wanjiku).first()
        link.duration_override_minutes = 180
        link.save()

        assert not cached(warm.wanjiku, wednesday)

    def test_opening_hours_drop_every_staff_member(self, warm, wednesday):
        row = (
            OpeningHours.objects.for_org(warm.organization)
            .filter(shop=warm.shop, weekday=wednesday.weekday())
            .first()
        )
        row.opens_at = time(7, 0)
        row.save()

        assert not cached(warm.wanjiku, wednesday)
        assert not cached(warm.grace, wednesday)

    def test_a_closure_drops_every_staff_member_for_its_dates(self, warm, wednesday):
        ShopClosure.objects.create(shop=warm.shop, starts_on=wednesday, ends_on=wednesday)

        assert not cached(warm.wanjiku, wednesday)
        assert not cached(warm.grace, wednesday)

    @pytest.mark.parametrize(
        "field,value",
        [
            ("buffer_minutes", 25),
            ("slot_interval_minutes", 30),
            ("min_lead_minutes", 120),
            ("booking_horizon_days", 14),
        ],
    )
    def test_every_scheduling_field_on_shop_drops_the_whole_shop(
        self, warm, wednesday, field, value
    ):
        """Each of these changes every slot at every chair. Parametrised so that
        adding a fifth field and forgetting it here is a one-line failure."""
        setattr(warm.shop, field, value)
        warm.shop.save(update_fields=[field])

        assert not cached(warm.wanjiku, wednesday)
        assert not cached(warm.grace, wednesday)

    def test_a_service_duration_change_drops_everyone_who_offers_it(self, warm, wednesday):
        """Including the stylists with no override, who inherit it."""
        warm.braids.duration_minutes = 200
        warm.braids.save()

        assert not cached(warm.wanjiku, wednesday)
        assert not cached(warm.grace, wednesday)

    def test_deactivating_a_staff_member_drops_them(self, warm, wednesday):
        warm.wanjiku.is_active = False
        warm.wanjiku.save(update_fields=["is_active"])

        assert not cached(warm.wanjiku, wednesday)


class TestTheChokePoint:
    def test_nothing_calls_the_cache_directly(self):
        """`grep` has to return this module and nothing else, or the key format
        starts drifting between callers."""
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parents[2]
        pattern = re.compile(r"\bforget(_many)?\(")
        offenders = []
        for path in (root / "scheduling").rglob("*.py"):
            if path.name in {"cache.py", "invalidation.py"} or "tests" in path.parts:
                continue
            if pattern.search(path.read_text()):
                offenders.append(str(path.relative_to(root)))

        assert not offenders, f"route invalidation through invalidation.py, not {offenders}"

    def test_every_model_the_engine_reads_has_a_receiver(self):
        """The one that catches a future slice.

        The loader reads these models; if a write to one of them cannot drop the
        cache, availability goes stale in a way nobody notices until a client is
        offered a slot that a stylist is on leave for.
        """
        registered = {model for _, model in invalidation.RECEIVERS}
        required = {
            "scheduling.Appointment",
            "shops.OpeningHours",
            "shops.ShopClosure",
            "shops.WorkingHours",
            "shops.Leave",
            "shops.Staff",
            "shops.Service",
            "shops.StaffService",
            "shops.Shop",
        }

        missing = required - registered
        assert not missing, f"{sorted(missing)} feed the engine but cannot invalidate it"

    def test_the_receiver_list_covers_what_the_loader_imports(self):
        """Cross-check from the other direction: anything `loading.py` queries
        should appear above. Catches a new model added to the loader without a
        receiver."""
        import inspect

        from scheduling import loading

        source = inspect.getsource(loading)
        registered = {model.split(".")[-1] for _, model in invalidation.RECEIVERS}

        for name in ("OpeningHours", "ShopClosure", "WorkingHours", "Leave", "Staff"):
            if f"{name}.objects" in source or f"{name}," in source:
                assert name in registered, f"{name} is read by the loader but never invalidated"

    def test_receivers_are_connected_once(self):
        """`dispatch_uid` on every connection, so an app reloaded in a test run
        or a management command does not fire each receiver twice."""
        import inspect

        source = inspect.getsource(invalidation.connect)

        assert "dispatch_uid" in source
        assert source.count("dispatch_uid") >= 2  # save and delete


class TestInvalidationIsBounded:
    def test_a_shop_wide_drop_is_one_round_trip(self, warm, wednesday, monkeypatch):
        """`delete_many`, not a loop of `delete`. A shop-hours change on eight
        stylists over a year is 2,928 keys; as individual round trips that is a
        visible stall on an owner's settings save."""
        calls = []
        original = cache.delete_many
        monkeypatch.setattr(
            cache, "delete_many", lambda keys: calls.append(len(keys)) or original(keys)
        )

        invalidation.invalidate_shop_days(warm.shop)

        assert len(calls) == 1

    def test_the_horizon_is_bounded(self):
        """Not unbounded, and not so short that a booking a year out survives a
        working-hours change."""
        assert 300 <= invalidation.HORIZON_DAYS <= 400

    def test_an_empty_staff_list_does_nothing(self, warm):
        """A shop with no staff yet must not blow up an owner's first save."""
        invalidation.invalidate_staff_days([])
        invalidation.invalidate_staff_days([None])


class TestReceiversSurviveUncoercedValues:
    """A receiver that raises turns a good write into a 500.

    Django leaves a string on a `DateField` until the row is read back, so
    `Leave(starts_on="2026-08-03")` reaches `post_save` with a `str`. That is
    ordinary in fixtures, management commands and `loaddata`, and it must not be
    the thing that breaks saving a stylist's leave.
    """

    def test_leave_saved_with_string_dates(self, warm, wednesday):
        Leave.objects.create(
            staff=warm.wanjiku,
            starts_on=wednesday.isoformat(),
            ends_on=wednesday.isoformat(),
        )

        assert not cached(warm.wanjiku, wednesday)

    def test_a_closure_saved_with_string_dates(self, warm, wednesday):
        ShopClosure.objects.create(
            shop=warm.shop, starts_on=wednesday.isoformat(), ends_on=wednesday.isoformat()
        )

        assert not cached(warm.wanjiku, wednesday)
        assert not cached(warm.grace, wednesday)
