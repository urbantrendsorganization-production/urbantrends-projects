"""Development settings: verbose, permissive, console email."""
from .base import *  # noqa: F401,F403
from .base import env

DEBUG = True

ALLOWED_HOSTS = ["*"]

# Console backend in dev — verification links print to the runserver log.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Let any localhost port talk to the API during development.
CORS_ALLOW_ALL_ORIGINS = env("CORS_ALLOW_ALL_ORIGINS", default=True)
