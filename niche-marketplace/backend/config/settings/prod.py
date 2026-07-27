"""Production settings: strict, SMTP email, security headers on."""
from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False

# Must be provided explicitly in prod — no wildcard fallback.
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")

# The app runs behind Caddy, which terminates TLS and forwards the original
# Host/proto so absolute URLs (e.g. media links) come out as https://<domain>.
USE_X_FORWARDED_HOST = True

# Static files (admin + DRF browsable API) are served by WhiteNoise straight
# from the app; Caddy proxies through. Media (user uploads) is served by Caddy
# from a shared volume. WhiteNoise sits directly after SecurityMiddleware.
MIDDLEWARE = [
    *MIDDLEWARE[:2],  # noqa: F405  (CorsMiddleware, SecurityMiddleware)
    "whitenoise.middleware.WhiteNoiseMiddleware",
    *MIDDLEWARE[2:],  # noqa: F405
]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Email is always delivered over SMTP (Resend) in production — never the
# console. Host, credentials and From address are env-driven in base.py.
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

# Security — TLS is terminated at Caddy, which sets X-Forwarded-Proto.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS", default=[])
