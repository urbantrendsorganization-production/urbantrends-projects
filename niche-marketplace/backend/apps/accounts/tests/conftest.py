import pytest


@pytest.fixture(autouse=True)
def _locmem_email(settings):
    """Capture outgoing mail in ``mail.outbox`` for assertions."""
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
