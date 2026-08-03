from pathlib import Path

from config.env import database_config, env, env_list

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = env("DJANGO_SECRET_KEY", "insecure-local-only-do-not-deploy")
DEBUG = False
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", ["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Needed for DateTimeRangeField and ExclusionConstraint — the appointment
    # time range and the no-double-booking constraint, CLAUDE.md §4.
    "django.contrib.postgres",
    "rest_framework",
    "core",
    "accounts",
    "orgs",
    "shops",
    "clients",
    "scheduling",
    "public_api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": database_config(
        env("DATABASE_URL", "postgres://booknasi:booknasi@localhost:5432/booknasi")
    )
}

REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}
}

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_ALWAYS_EAGER = False
CELERY_TIMEZONE = "UTC"

# Slice 5's release sweep. See scheduling/tasks.py for why a Beat sweep exists
# alongside a per-appointment `eta` task: the scheduled task is for timeliness
# and this is for correctness. A lost broker, a redeployed worker or a dropped
# task id costs a minute here instead of a permanently held slot.
#
# Declared in code rather than in django-celery-beat's database scheduler on
# purpose: one periodic task does not justify a dependency, a migration and an
# admin row that can be edited into silence without anyone noticing.
CELERY_BEAT_SCHEDULE = {
    "release-expired-holds": {
        "task": "scheduling.sweep_expired_holds",
        "schedule": 60.0,
        # If Beat was down, run once on recovery rather than replaying every
        # minute it missed. The sweep is idempotent, so the replay would be
        # harmless — just pointless load at the worst possible moment.
        "options": {"expires": 55.0},
    },
}

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# CLAUDE.md §4: store UTC, render EAT. USE_TZ stays on; there is no timezone
# abstraction layer and no per-org timezone field. EAT is a rendering concern.
LANGUAGE_CODE = "en-ke"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
DISPLAY_TIME_ZONE = "Africa/Nairobi"

STATIC_URL = "static/"

REST_FRAMEWORK = {
    # Session auth only. The first-party frontend is same-site, and the public
    # booking API (slice 5) is unauthenticated and shop-scoped by slug, so
    # there is nothing here that needs a token library yet.
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "UNAUTHENTICATED_USER": "django.contrib.auth.models.AnonymousUser",
    "EXCEPTION_HANDLER": "core.exceptions.exception_handler",
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
    # A crude ceiling on the unauthenticated surface, and explicitly **not** the
    # real control on hold abuse — see the long note in `scheduling/abuse.py`.
    # Safaricom and Airtel put large numbers of Kenyan subscribers behind
    # carrier-grade NAT, so a per-IP limit tight enough to stop a determined
    # script would block a neighbourhood on a Saturday morning. The per-phone
    # limits in that module are what actually bound the exposure.
    "DEFAULT_THROTTLE_RATES": {
        "public-read": "240/hour",
        "hold-create": "12/hour",
    },
}

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# Invites are delivered by SMS and typed on a phone. Long enough to survive a
# day off, short enough that a leaked SMS is not a standing key.
STAFF_INVITE_TTL_DAYS = 14

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}
