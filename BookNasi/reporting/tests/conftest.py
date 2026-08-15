"""Fixtures for the dashboard tests.

Appointments are written with `Appointment.objects.create` rather than through
`booking.create_appointment`. That is deliberate and is the one place in this
repo where doing so is right: these tests are about **how finished rows are
counted**, and every status they need — completed, no-show, a booking left
unresolved for a fortnight — is one the booking path cannot produce directly.
Driving each through a hold, a payment and three transitions would make a
counting test into an integration test and would hide the arithmetic it is
checking.

Everything is anchored to a fixed date, for the reason
`scheduling/tests/conftest.py` gives.
"""

from datetime import date, timedelta

import pytest

from scheduling.models import Appointment
from scheduling.statuses import AppointmentStatus, BookingSource
from scheduling.tests.conftest import eat

#: A Wednesday, well clear of the availability tests' own so nothing collides
#: if a fixture is ever shared. The shop opens Monday-Saturday.
REPORT_WEDNESDAY = date(2026, 6, 10)

#: `now` for the report: 18:00 EAT on the Friday after that week. Everything the
#: tests book on or before Thursday is therefore in the past, which is what
#: makes `unresolved` observable.
REPORT_NOW = eat(date(2026, 6, 12), 18)


@pytest.fixture
def report_period():
    """The fortnight ending the day before `REPORT_NOW`'s week runs out."""
    from reporting.period import Period

    return Period(REPORT_WEDNESDAY - timedelta(days=6), REPORT_WEDNESDAY + timedelta(days=3))


@pytest.fixture
def now():
    return REPORT_NOW


@pytest.fixture
def record(shop_setup):
    """Write one finished appointment, at an hour of the day nothing else uses.

    `hour` is the caller's way of keeping two bookings for the same stylist off
    each other — the exclusion constraint is live in these tests, as it is
    everywhere.
    """

    def _record(
        *,
        staff=None,
        day=REPORT_WEDNESDAY,
        hour=10,
        minutes=60,
        status=AppointmentStatus.COMPLETED,
        price=3500,
        #: 25 %, the pre-fill §12 gives service creation. Derived from `price`
        #: rather than fixed so a cheap service does not trip the
        #: `appointment_deposit_within_price` check constraint.
        deposit=None,
        source=BookingSource.ONLINE,
        client=None,
        was_shortened=False,
        service=None,
    ):
        starts_at = eat(day, hour)
        return Appointment.objects.create(
            shop=shop_setup.shop,
            staff=staff or shop_setup.wanjiku,
            service=service or shop_setup.braids,
            client=client,
            time_range=(starts_at, starts_at + timedelta(minutes=minutes)),
            status=status,
            source=source,
            price_snapshot=price,
            deposit_snapshot=price // 4 if deposit is None else deposit,
            duration_snapshot=minutes,
            was_shortened=was_shortened,
        )

    return _record


@pytest.fixture
def paid(shop_setup):
    """Attach a succeeded M-Pesa payment to a booking.

    Built directly for the same reason the appointments are: the report reads
    `Payment.state` and `Payment.amount`, and pushing each one through Daraja
    and a callback would test slice 6 again rather than slice 9.
    """
    from payments.models import Payment
    from payments.states import PaymentState

    counter = iter(range(1000, 9999))

    def _paid(appointment, amount=875, state=PaymentState.SUCCEEDED, **extra):
        sequence = next(counter)
        return Payment.objects.create(
            appointment=appointment,
            state=state,
            amount=amount,
            phone="+254712000999",
            checkout_request_id=f"ws_CO_{sequence}",
            mpesa_receipt=f"REC{sequence}" if state == PaymentState.SUCCEEDED else "",
            support_code=f"BK-T{sequence}",
            **extra,
        )

    return _paid


@pytest.fixture
def client_row(shop_setup):
    from clients.models import Client

    counter = iter(range(100, 999))

    def _client(name="Amina"):
        return Client.objects.create(
            organization=shop_setup.organization,
            full_name=name,
            phone=f"+2547333{next(counter):05d}",
        )

    return _client


@pytest.fixture(autouse=True)
def no_report_cache(settings):
    """The dashboard caches aggregates for five minutes. A test that wrote a
    booking and then read a cached total from the test before it would fail in
    a way that looks like an arithmetic bug."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()
