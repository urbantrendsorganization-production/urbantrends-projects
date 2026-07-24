"""
Base settings shared by every environment.

Environment-specific modules (``dev``, ``prod``) import ``*`` from here and
override only what differs. Anything that reads from the environment is wired
through ``django-environ`` so the same image behaves differently per deploy.
"""
from datetime import timedelta
from pathlib import Path

import environ

# backend/config/settings/base.py -> backend/
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CORS_ALLOWED_ORIGINS=(list, ["http://localhost:3000"]),
)

# Read a .env file if present (dev convenience; prod injects real env vars).
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="insecure-dev-key-change-me")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")

# Applications ---------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
]

LOCAL_APPS = [
    "apps.accounts",
    "apps.catalog",
    "apps.core",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

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

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Database -------------------------------------------------------------------
# Prefer a single DATABASE_URL; fall back to discrete POSTGRES_* vars so the
# same settings work with docker-compose's service env.
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://{user}:{password}@{host}:{port}/{name}".format(
            user=env("POSTGRES_USER", default="marketplace"),
            password=env("POSTGRES_PASSWORD", default="marketplace"),
            host=env("POSTGRES_HOST", default="localhost"),
            port=env("POSTGRES_PORT", default="5432"),
            name=env("POSTGRES_DB", default="marketplace"),
        ),
    )
}

# Cache / Celery broker ------------------------------------------------------
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=REDIS_URL)
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = "UTC"

# Auth -----------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# DRF ------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 20,
    # Consistent error envelope: {"detail": ..., "code": ...}
    "EXCEPTION_HANDLER": "apps.core.exceptions.envelope_exception_handler",
}

# JWT ------------------------------------------------------------------------
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    # Rotate refresh tokens and blacklist the old one on every refresh.
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
}

# Email / verification -------------------------------------------------------
# Transactional email (verification links) is sent through Django's email
# backend. We deliver via Resend over SMTP: the username is the literal string
# "resend" and the password is the Resend API key. Defaults point at Resend so
# the only secret needed is RESEND_API_KEY.
RESEND_API_KEY = env("RESEND_API_KEY", default="")

EMAIL_HOST = env("EMAIL_HOST", default="smtp.resend.com")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="resend")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default=RESEND_API_KEY)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)

# Use real SMTP delivery whenever an API key is configured; otherwise fall back
# to the console backend so dev works offline. prod.py forces SMTP regardless.
EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default=(
        "django.core.mail.backends.smtp.EmailBackend"
        if RESEND_API_KEY
        else "django.core.mail.backends.console.EmailBackend"
    ),
)

# From address — must be a Resend-verified sender. Accepts a bare address or
# "Name <addr>". EMAIL_NAME is an accepted alias for DEFAULT_FROM_EMAIL.
DEFAULT_FROM_EMAIL = env(
    "DEFAULT_FROM_EMAIL",
    default=env("EMAIL_NAME", default="no-reply@marketplace.local"),
)

# Public base URL of the frontend; verification links point here.
FRONTEND_URL = env("FRONTEND_URL", default="http://localhost:3000")
# How long a verification link stays valid, in seconds (default 24h).
EMAIL_VERIFICATION_TIMEOUT = env.int("EMAIL_VERIFICATION_TIMEOUT", default=60 * 60 * 24)

# I18N / TZ ------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static / media -------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# CORS -----------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")
