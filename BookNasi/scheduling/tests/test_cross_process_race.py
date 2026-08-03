"""LOAD-BEARING. The same race, across two processes.

`test_concurrency.py` runs two threads in one interpreter. That is a real race —
two connections, Postgres arbitrating — but it shares a process, and a reviewer
is entitled to wonder whether some Python-level accident is doing the work.

Production is two gunicorn workers in a container on a Hetzner box, or two
containers behind Caddy. There is no shared memory between them and no
application-level lock available to either. This test reproduces that: two
`spawn`ed processes, each running `django.setup()` from scratch against the same
test database, released simultaneously into the INSERT by a shared barrier.

It is the strongest available evidence that the guarantee comes from the
database and not from anything in this codebase — which is exactly what
CLAUDE.md §4 asks for when it says not to replace the constraint with a lock or
a queue.

Skipped rather than failed where it cannot run (no `spawn`, no reachable
DATABASE_URL), because a test that cannot execute must not be mistaken for one
that passed.
"""

import multiprocessing
import os
from datetime import timedelta

import pytest
from django.db import connection

from scheduling.models import Appointment
from scheduling.tests._race_worker import try_to_book
from scheduling.tests.conftest import eat

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.loadbearing]

TIMEOUT_SECONDS = 60


def race(shop_setup, when, database_url, *, through_service_function):
    payload = {
        "shop_id": str(shop_setup.shop.id),
        "organization_id": str(shop_setup.organization.id),
        "staff_id": str(shop_setup.wanjiku.id),
        "service_id": str(shop_setup.braids.id),
        "starts_at": when.isoformat(),
        "duration_minutes": shop_setup.braids.duration_minutes,
        "price": shop_setup.braids.price,
        "deposit": shop_setup.braids.deposit_amount,
    }

    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(2, timeout=TIMEOUT_SECONDS)
    results = ctx.Queue()
    processes = [
        ctx.Process(
            target=try_to_book,
            args=(barrier, results),
            kwargs={
                "database_url": database_url,
                "payload": payload,
                "through_service_function": through_service_function,
            },
        )
        for _ in range(2)
    ]

    for process in processes:
        process.start()
    for process in processes:
        process.join(TIMEOUT_SECONDS)
        assert process.exitcode is not None, "child process hung"

    return sorted(results.get(timeout=5) for _ in range(2))


def test_two_processes_cannot_book_the_same_slot(shop_setup, wednesday, database_url):
    """A bare insert from each process, with no advisory lock between them.

    This is the arrangement that first surfaced the deadlock: two exclusion
    checks waiting on each other, resolved by Postgres killing one with SQLSTATE
    40P01 — an `OperationalError`, not an `IntegrityError`. A wrapper that only
    caught `IntegrityError` would have let that reach the client as a 500 at the
    moment they were being asked to pay.

    It must still come out as SlotTaken, because any future caller that inserts
    an appointment without going through `create_appointment` will take this
    path.
    """
    outcomes = race(shop_setup, eat(wednesday, 15), database_url, through_service_function=False)

    assert outcomes == ["SlotTaken", "ok"], outcomes
    assert Appointment.all_objects.filter(staff=shop_setup.wanjiku).count() == 1


def test_the_service_function_survives_the_same_race(shop_setup, wednesday, database_url):
    """The real path, advisory lock included.

    The lock orders the two checks so neither has to wait on the other, and the
    loser gets an ordinary constraint violation rather than a deadlock. Either
    loss is acceptable and both are named — what matters is that exactly one row
    exists and the loser knows why.
    """
    # 10:00, not an afternoon slot: the fixture's braid takes four hours and
    # Wanjiku finishes at 18:00, so anything after 14:00 is refused by the
    # engine before the race can happen — which is correct, and would make this
    # test silently prove nothing.
    outcomes = race(shop_setup, eat(wednesday, 10), database_url, through_service_function=True)

    assert outcomes.count("ok") == 1, outcomes
    assert set(outcomes) <= {"ok", "SlotTaken", "SlotUnavailable"}, outcomes
    assert Appointment.all_objects.filter(staff=shop_setup.wanjiku).count() == 1


@pytest.fixture
def database_url():
    url = _test_database_url()
    if url is None:
        pytest.skip("DATABASE_URL is not set; cannot point a child process at the test database")
    return url


def _test_database_url():
    """The URL of the database this test is *actually* running against.

    pytest-django creates `test_<name>`, so the DATABASE_URL in the environment
    points at the wrong database — the child would connect to a schema with no
    fixtures in it and fail in a way that looks like a scheduling bug. The name
    is taken from the live connection instead.
    """
    raw = os.environ.get("DATABASE_URL")
    if not raw:
        return None
    name = connection.settings_dict["NAME"]
    base, _, _ = raw.rpartition("/")
    return f"{base}/{name}"


def test_the_worker_would_have_reported_a_failure_rather_than_passing_silently():
    """Guards the test above against its own success condition.

    If `try_to_book` ever swallowed an exception and reported "ok", the assertion
    on outcomes would still pass whenever the second child crashed for an
    unrelated reason. The worker puts the exception name on the queue instead,
    so an unexpected failure shows up as a readable string in the assertion
    message rather than as a silent pass.
    """
    import inspect

    source = inspect.getsource(try_to_book)

    assert 'results.put(f"{type(exc).__name__}' in source
    assert "except Exception" in source


def test_the_fixture_slot_is_genuinely_free_first(shop_setup, wednesday):
    """Sanity: the race above is only meaningful if nothing already occupies the
    slot. A fixture change that pre-booked 15:00 would make both children lose
    and the test would still fail loudly — but for the wrong reason."""
    when = eat(wednesday, 15)
    occupied = Appointment.all_objects.filter(
        staff=shop_setup.wanjiku, time_range__overlap=(when, when + timedelta(minutes=240))
    )

    assert not occupied.exists()
