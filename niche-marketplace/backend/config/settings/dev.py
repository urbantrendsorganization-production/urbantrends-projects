"""Development settings: verbose, permissive, console email."""
from .base import *  # noqa: F401,F403
from .base import env

DEBUG = True

ALLOWED_HOSTS = ["*"]

# Email backend is chosen in base.py: real SMTP (Resend) when RESEND_API_KEY is
# set, otherwise the console backend so verification links just print to the
# runserver log. To ignore a configured key and force console, uncomment:
# EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Let any localhost port talk to the API during development.
CORS_ALLOW_ALL_ORIGINS = env("CORS_ALLOW_ALL_ORIGINS", default=True)
