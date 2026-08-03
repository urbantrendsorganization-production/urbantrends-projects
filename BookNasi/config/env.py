"""Environment reading.

Deliberately hand-rolled rather than pulling in django-environ or dj-database-url:
CLAUDE.md §11 says not to add a dependency for something the stdlib already does,
and this is forty lines of urllib.parse.
"""

import os
from urllib.parse import unquote, urlparse


class MissingSetting(RuntimeError):
    pass


def env(name, default=None, *, required=False):
    value = os.environ.get(name, default)
    if required and not value:
        raise MissingSetting(f"{name} must be set in the environment")
    return value


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=()):
    value = os.environ.get(name)
    if not value:
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]


def database_config(url):
    """Turn a postgres:// URL into Django's DATABASES['default'] dict."""
    parts = urlparse(url)
    if parts.scheme not in {"postgres", "postgresql"}:
        raise MissingSetting(
            f"DATABASE_URL must be a postgres:// URL (got {parts.scheme or 'nothing'}). "
            "BookNasi requires PostgreSQL — the availability engine depends on btree_gist "
            "and an exclusion constraint that no other backend provides."
        )
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parts.path.lstrip("/")),
        "USER": unquote(parts.username or ""),
        "PASSWORD": unquote(parts.password or ""),
        "HOST": parts.hostname or "",
        "PORT": str(parts.port or 5432),
        "CONN_MAX_AGE": 60,
    }
