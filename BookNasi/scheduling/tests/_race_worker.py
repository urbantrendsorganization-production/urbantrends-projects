"""Worker for the cross-process double-booking test.

A separate importable module because `multiprocessing` uses the `spawn` start
method here, and a spawned child re-imports the target by name rather than
inheriting it. Forking instead would carry the parent's open database
connections into the child, which is its own source of flaky failures — and
would also make the test prove less, since a forked child shares more state with
the parent than two web workers on a Hetzner box ever do.

Nothing in this file is imported by application code.
"""

import os


def try_to_book(barrier, results, *, database_url, payload, through_service_function=False):
    """Configure Django from scratch, then race for the slot.

    Runs in a child process with no inherited connections, so the only thing
    shared with its sibling is Postgres itself. That is the arrangement the
    exclusion constraint actually has to survive in production: two containers,
    two connection pools, no shared memory, no application-level lock available
    to either of them.

    `through_service_function` selects which of the two defences is under test:

    - **False** — a bare INSERT, with no advisory lock. Two of these deadlock
      inside the exclusion check, and the loser's error is `OperationalError`
      rather than `IntegrityError`. This is the path any future caller that
      inserts an appointment without going through `create_appointment` would
      take, and it must still end in SlotTaken.
    - **True** — the real `create_appointment`, advisory lock included. The
      checks are ordered, so the loser gets an ordinary constraint violation.
    """
    os.environ["DATABASE_URL"] = database_url
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
    os.environ.setdefault("DJANGO_SECRET_KEY", "race-worker")

    import django

    django.setup()

    from datetime import datetime, timedelta

    from django.db import connections, transaction

    from scheduling.booking import SlotTaken, SlotUnavailable, slot_taken_on_conflict
    from scheduling.models import Appointment
    from scheduling.statuses import AppointmentStatus, BookingSource

    starts_at = datetime.fromisoformat(payload["starts_at"])
    duration = payload["duration_minutes"]

    try:
        if through_service_function:
            from scheduling.booking import create_appointment
            from shops.models import Service, Staff

            staff = Staff.all_objects.get(pk=payload["staff_id"])
            service = Service.all_objects.get(pk=payload["service_id"])
            # Warm the connection before the barrier so it releases both
            # children into the write, not into a connect.
            with connections["default"].cursor() as cursor:
                cursor.execute("SELECT 1")
            barrier.wait()
            create_appointment(
                staff=staff,
                service=service,
                starts_at=starts_at,
                source=BookingSource.STAFF,
                now=starts_at - timedelta(hours=2),
            )
        else:
            with connections["default"].cursor() as cursor:
                cursor.execute("SELECT 1")
            barrier.wait()

            with slot_taken_on_conflict():
                with transaction.atomic():
                    Appointment(
                        shop_id=payload["shop_id"],
                        organization_id=payload["organization_id"],
                        staff_id=payload["staff_id"],
                        service_id=payload["service_id"],
                        time_range=(starts_at, starts_at + timedelta(minutes=duration)),
                        status=AppointmentStatus.CONFIRMED,
                        source=BookingSource.STAFF,
                        price_snapshot=payload["price"],
                        deposit_snapshot=payload["deposit"],
                        duration_snapshot=duration,
                    ).save()
        results.put("ok")
    except SlotTaken:
        results.put("SlotTaken")
    except SlotUnavailable:
        # The other child committed before this one re-derived. A correct loss,
        # just not the one the constraint arbitrated.
        results.put("SlotUnavailable")
    except Exception as exc:  # noqa: BLE001 — reported, not swallowed
        results.put(f"{type(exc).__name__}: {exc}")
    finally:
        connections.close_all()
