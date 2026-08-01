from django.conf import settings
from django.db import connection
from django.http import JsonResponse


def _check_database():
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
        # Slice 3 cannot ship without this. Reporting it here means a broken
        # deploy says so on /health/ rather than during a migration.
        cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'btree_gist'")
        has_btree_gist = cursor.fetchone() is not None
    return {"ok": True, "btree_gist": has_btree_gist}


def _check_redis():
    import redis

    client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=1)
    client.ping()
    return {"ok": True}


def health(_request):
    checks = {}
    for name, probe in (("database", _check_database), ("redis", _check_redis)):
        try:
            checks[name] = probe()
        except Exception as exc:  # noqa: BLE001 - health must report, not raise
            checks[name] = {"ok": False, "error": type(exc).__name__}

    healthy = all(check["ok"] for check in checks.values())
    return JsonResponse(
        {"status": "ok" if healthy else "degraded", "checks": checks},
        status=200 if healthy else 503,
    )
