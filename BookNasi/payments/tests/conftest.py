"""Fixtures for the payment tests.

Two decisions worth stating, because they shape every test in this package.

**The Daraja seam is an implementation, not a mock.** `FakeDarajaClient` is
selected through `settings.MPESA_CLIENT` exactly as the real one would be, so
`stk.py` and `callbacks.py` run the code path they run in production. A
monkeypatched `push` would test a different program.

**Callback bodies are built from the real envelope.** `stk_callback` produces
the shape Safaricom actually sends, `CallbackMetadata` and all, including the
`PhoneNumber` item — which is the only way a redaction test can mean anything.
A failure body carries no metadata at all, because Safaricom's does not.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from payments.daraja import reset_client
from scheduling.holds import create_hold
from scheduling.tests.conftest import WEDNESDAY, eat


@pytest.fixture(autouse=True)
def eager_celery(settings):
    """`apply_async` and `.delay` run inline. Same trick as the hold tests:
    scheduling is observable, timing is asserted with a moved clock."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True


@pytest.fixture(autouse=True)
def fake_daraja(settings):
    """The process-wide client, reset around every test.

    `get_client` caches — it holds an access token in production — so a client
    left over from a previous test would carry its recorded pushes and its
    armed error into this one.
    """
    settings.MPESA_CLIENT = "payments.daraja.FakeDarajaClient"
    reset_client()
    from payments.daraja import get_client

    yield get_client()
    reset_client()


@pytest.fixture(autouse=True)
def console_messages(settings):
    """Messages land in an in-process list rather than on a gateway."""
    from notifications.providers import get_provider, reset_provider

    settings.MESSAGE_PROVIDER = "notifications.providers.ConsoleProvider"
    reset_provider()
    yield get_provider()
    reset_provider()


@pytest.fixture
def wednesday():
    """The same fixed trading day the availability tests use.

    Anchored to a constant rather than to `today`, for the reason
    `scheduling/tests/conftest.py` gives: a test that says "book at 10:00
    tomorrow" passes for a year and then fails on the day tomorrow is a Sunday,
    and the failure looks like a scheduling bug rather than a fixture bug. That
    module's own `wednesday` fixture is package-scoped, so the constant is
    re-exposed here rather than the fixture being reached for across packages.
    """
    return WEDNESDAY


@pytest.fixture
def held(shop_setup, wednesday):
    """One held slot, two hours before it starts. The ordinary starting point."""
    when = eat(wednesday, 10)
    return create_hold(
        shop=shop_setup.shop,
        service=shop_setup.braids,
        staff=shop_setup.wanjiku,
        starts_at=when,
        phone="0712345678",
        now=when - timedelta(hours=2),
    )


def hold_at(shop_setup, hour, *, phone="0712345678", staff=None, service=None, now=None):
    when = eat(WEDNESDAY, hour)
    return create_hold(
        shop=shop_setup.shop,
        service=service or shop_setup.braids,
        staff=staff or shop_setup.wanjiku,
        starts_at=when,
        phone=phone,
        now=now or (when - timedelta(hours=2)),
    )


#: A receipt in Safaricom's own shape: ten characters, letters and digits.
RECEIPT = "SJ42K19XQ7"


def stk_callback(
    checkout_request_id,
    *,
    result_code=0,
    result_desc=None,
    amount=875,
    receipt=RECEIPT,
    phone=254712345678,
    transaction_date=20260909083000,
    merchant_request_id="MRQ-1",
):
    """A callback body in the envelope Safaricom sends.

    A non-zero `ResultCode` gets **no** `CallbackMetadata` at all, which is what
    the sandbox does and what every defensive read in `parsing.py` is for.
    """
    stk = {
        "MerchantRequestID": merchant_request_id,
        "CheckoutRequestID": checkout_request_id,
        "ResultCode": result_code,
        "ResultDesc": result_desc or ("The service request is processed successfully."),
    }
    if result_code == 0:
        stk["CallbackMetadata"] = {
            "Item": [
                {"Name": "Amount", "Value": amount},
                {"Name": "MpesaReceiptNumber", "Value": receipt},
                {"Name": "TransactionDate", "Value": transaction_date},
                {"Name": "PhoneNumber", "Value": phone},
            ]
        }
    return {"Body": {"stkCallback": stk}}


def push_for(appointment, **kwargs):
    """Send the prompt and return the payment, reloaded."""
    from payments.stk import initiate_push

    return initiate_push(appointment, **kwargs)


def expire_the_hold(appointment, *, now=None):
    """Put the appointment where a late callback finds it: cancelled by the
    sweep, with `hold_released_at` set. Deliberately goes through the real
    release path rather than writing the columns, because the discriminator the
    settlement reads is set by that path and nowhere else."""
    from scheduling.holds import release_hold

    now = now or (appointment.hold_expires_at + timedelta(seconds=1))
    release_hold(appointment, now=now, expired=True)
    appointment.refresh_from_db()
    return appointment


def cancel_deliberately(appointment, *, now=None):
    """The other kind of cancelled: somebody pressed the button."""
    from scheduling.holds import release_hold

    release_hold(appointment, now=now or timezone.now(), expired=False)
    appointment.refresh_from_db()
    return appointment
