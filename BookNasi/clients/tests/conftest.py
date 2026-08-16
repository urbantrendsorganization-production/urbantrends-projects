"""A client with something to erase.

`payments/tests/conftest.py` has a `held` fixture, but a conftest is scoped to
its own package — reaching across would couple this suite to that one's
scaffolding. The hold is rebuilt here from the same shared helpers instead,
which is what `payments` itself does with `scheduling`'s.
"""

from datetime import timedelta

import pytest

from scheduling.holds import create_hold
from scheduling.tests.conftest import WEDNESDAY, eat


@pytest.fixture(autouse=True)
def eager_celery(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True


@pytest.fixture(autouse=True)
def console_messages(settings):
    """No gateway. Erasure revokes tokens, and revocation can notify."""
    from notifications.providers import reset_provider

    settings.MESSAGE_PROVIDER = "notifications.providers.ConsoleProvider"
    reset_provider()
    yield
    reset_provider()


@pytest.fixture
def held(shop_setup):
    when = eat(WEDNESDAY, 10)
    return create_hold(
        shop=shop_setup.shop,
        service=shop_setup.braids,
        staff=shop_setup.wanjiku,
        starts_at=when,
        phone="0712345678",
        now=when - timedelta(hours=2),
    )


@pytest.fixture(autouse=True)
def clear_throttles():
    """Throttle counters live in the cache and outlive a test.

    The public manage endpoints are per-IP throttled, and every test here comes
    from the same address — so the fourth `forget-me` in a class would be a 429
    rather than the thing under test, and the failure would look like a bug in
    the view. `scheduling/tests/conftest.py` has the same fixture for the same
    reason; it is autouse here because every test in this package that touches
    the public API needs it.
    """
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()
