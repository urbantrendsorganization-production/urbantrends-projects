"""Shared with the payment tests, deliberately.

The messaging fixtures — an eager broker, a fake Daraja, a console provider —
are defined once in `payments/tests/conftest.py` and re-exported here rather
than copied. Two sets of fixtures that happen to agree today is how a test
suite starts asserting different things about the same code.
"""

from payments.tests.conftest import (  # noqa: F401 — re-exported fixtures
    console_messages,
    eager_celery,
    fake_daraja,
    held,
    wednesday,
)
