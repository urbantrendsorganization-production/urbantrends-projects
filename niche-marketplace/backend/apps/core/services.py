"""Core service layer. Views stay thin and delegate here."""
import redis
from django.conf import settings
from django.db import connection


def _check_database() -> bool:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return True
    except Exception:
        return False


def _check_redis() -> bool:
    try:
        client = redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        return bool(client.ping())
    except Exception:
        return False


def get_health() -> dict:
    """Report liveness of the API and its backing services.

    The service is considered healthy as long as the database is reachable;
    Redis being down is reported but does not fail the check on its own.
    """
    database_ok = _check_database()
    redis_ok = _check_redis()
    return {
        "status": "ok" if database_ok else "degraded",
        "version": "0.1.0",
        "services": {
            "database": "up" if database_ok else "down",
            "redis": "up" if redis_ok else "down",
        },
    }
