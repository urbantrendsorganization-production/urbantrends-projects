from datetime import timedelta
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
    "payments",
    "notifications",
    "reporting",
    "public_api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Slice 10. `/api/public/` only, never credentialed, never reflecting the
    # caller's origin — the whole policy is in `core/cors.py` and it has no
    # settings. High in the list so a preflight is answered before session,
    # CSRF and auth work that a preflight carries nothing for, and so the
    # response phase runs late enough to put the header on error responses that
    # never reached a view. A 429 the browser discards is a 429 the widget
    # reports as "no connection".
    "core.cors.PublicApiCorsMiddleware",
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
    # Slice 6. **A separate mechanism from the hold sweep above**, on its own
    # schedule, because the two answer different questions: that one decides
    # whether a slot goes back on offer, this one decides what happened to
    # money. One job doing both means a slow M-Pesa holds the calendar hostage,
    # or a busy calendar skips a payment. See payments/reconcile.py.
    "reconcile-unresolved-payments": {
        "task": "payments.sweep_unresolved_payments",
        "schedule": 120.0,
        "options": {"expires": 115.0},
    },
    "escalate-stale-payments": {
        "task": "payments.escalate_stale_payments",
        "schedule": 3600.0,
        "options": {"expires": 3500.0},
    },
    # Slice 8. The correctness half of reminders, beside the per-appointment
    # `eta` tasks that provide the timeliness — the same split, for the same
    # reason, as the hold sweep above. Five minutes rather than one: a reminder
    # arriving five minutes late is a reminder, whereas a slot released five
    # minutes late is a slot somebody could not book.
    #
    # It also arms reminders for confirmed bookings that have none, which is
    # what keeps a forgotten call site to a delay instead of a silence.
    "send-due-reminders": {
        "task": "notifications.sweep_due_reminders",
        "schedule": 300.0,
        "options": {"expires": 290.0},
    },
    # Credit that lapsed. Bookkeeping only — `Credit.is_spendable` already reads
    # the timestamp, so this cannot let a client spend money the policy says is
    # gone. Hourly is ample for a 60-day window.
    "expire-lapsed-credits": {
        "task": "payments.expire_lapsed_credits",
        "schedule": 3600.0,
        "options": {"expires": 3500.0},
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
    #
    # One scope per public endpoint, never a shared budget — same note, same
    # reason. Under CGNAT a shared scope lets one client's traffic exhaust the
    # allowance of every stranger on their operator's NAT pool, and the 429
    # surfaces on whichever endpoint they touch next rather than the noisy one.
    "DEFAULT_THROTTLE_RATES": {
        # The reads, split by how hard each is actually used. Availability is
        # re-fetched on every date and stylist change; the shop, service and
        # staff lists are fetched about once per booking.
        "shop-read": "120/hour",
        "service-read": "120/hour",
        "staff-read": "120/hour",
        "availability-read": "600/hour",
        # The polled endpoint. One booking spends ~180 requests here over a
        # three-minute hold plus its grace window, so a shared ceiling meant a
        # single client could exhaust it and a second client behind the same
        # NAT address would be 429'd in the middle of paying — and a 429 there
        # freezes the STK screen with the money already gone.
        "hold-read": "1200/hour",
        "hold-create": "12/hour",
        # Separate from `hold-create` on purpose. Cancelling is free — see
        # `HoldReleaseView` — so the button a client is *meant* to press must
        # not be rate-limited by how many holds they have taken.
        "hold-release": "30/hour",
        # Slice 7's manage surface, split read from write. The read backs a page
        # a client may leave open; the writes are once-per-booking actions. One
        # budget for both would let a forgotten tab spend a client's ability to
        # cancel, which is the action they are least able to postpone.
        "manage-read": "300/hour",
        # One scope per action, not one "write" bucket. A client who has just
        # rescheduled twice must still be able to cancel, and a client whose
        # slot was lost must still be able to re-point — those are three
        # different needs and a shared budget makes the busiest one starve the
        # other two at exactly the wrong moment.
        "manage-cancel": "10/hour",
        "manage-reschedule": "20/hour",
        "payment-repoint": "20/hour",
        # Resend is bounded per appointment in `payments/stk.py`, which is the
        # real control. This is the same crude per-IP ceiling as above, and is
        # loose for the same carrier-grade-NAT reason.
        "stk-resend": "30/hour",
    },
}

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# Invites are delivered by SMS and typed on a phone. Long enough to survive a
# day off, short enough that a leaked SMS is not a standing key.
STAFF_INVITE_TTL_DAYS = 14

# Where the client-facing pages live. Used to build the one link an SMS carries.
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", "http://localhost:3000")

# The origin the frontend is served from is an origin we accept writes from.
#
# Django compares the browser's `Origin` header against the request's host for
# every unsafe method, and rejects a mismatch unless the origin is listed here.
# Behind the dev proxy and behind Caddy the browser's origin is
# `PUBLIC_BASE_URL` while the host Django sees is the container it is bound to,
# so they never match on their own and every authenticated write 403s.
#
# Defaulted from `PUBLIC_BASE_URL` rather than left empty, because those two
# being the same thing is not a coincidence: it is the address we put in every
# SMS and the address the staff app is loaded from. A deployment that overrides
# one and forgets the other is the failure this default removes.
#
# Set the env var to widen it — several shop subdomains, or a wildcard like
# `https://*.booknasi.co.ke`. Listing an origin here is not a CORS grant and
# gives nobody cross-origin *read* access; `core/cors.py` still answers
# `/api/v1/` with no CORS headers at all.
#
# This was empty in every environment but production until slice 11's manual
# walk, where it turned out the staff app could not record a walk-in: the
# suites drive the API directly and a test client sends no `Origin` header, so
# nothing in 1305 tests crossed the one seam where this matters. See
# `core/tests/test_csrf_origin.py`.
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", default=(PUBLIC_BASE_URL,))

# --------------------------------------------------------------- slice 6

# Safaricom Daraja. Nothing real here and nothing real in `.env.example` —
# CLAUDE.md §5 and §11. A sandbox shortcode is still a credential.
#: The two STK transaction types Daraja offers, and the only two that exist.
#: Named rather than free text because the string goes straight into the push
#: body, and a typo there is a rejection at Safaricom with a code nobody reads.
MPESA_PAYBILL = "CustomerPayBillOnline"
MPESA_TILL = "CustomerBuyGoodsOnline"

MPESA = {
    "BASE_URL": env("MPESA_BASE_URL", "https://sandbox.safaricom.co.ke"),
    "CONSUMER_KEY": env("MPESA_CONSUMER_KEY", ""),
    "CONSUMER_SECRET": env("MPESA_CONSUMER_SECRET", ""),
    # Paybill: the paybill number. Till: the **store / head office** number,
    # which is *not* the till number. The password is derived from this one in
    # both cases, which is why the two are separate settings rather than one
    # "shortcode" that means different things depending on the mode.
    "SHORTCODE": env("MPESA_SHORTCODE", ""),
    "PASSKEY": env("MPESA_PASSKEY", ""),
    "CALLBACK_URL": env("MPESA_CALLBACK_URL", ""),
    "TIMEOUT_SECONDS": int(env("MPESA_TIMEOUT_SECONDS", "20")),
    # Paybill by default. A till deployment sets both of these; a paybill one
    # sets neither, and the default keeps every existing deployment working.
    "TRANSACTION_TYPE": env("MPESA_TRANSACTION_TYPE", MPESA_PAYBILL),
    # Where the money actually lands under `CustomerBuyGoodsOnline`. Unused for
    # paybill, and `daraja.py` refuses to push without it when the type says
    # till — a `PartyB` of the store number would send the client's deposit to
    # the wrong place, quietly and successfully.
    "TILL_NUMBER": env("MPESA_TILL_NUMBER", ""),
}
# The real client is opt-in. Local work and every test run against
# `FakeDarajaClient`, which implements the same two methods — the seam is at the
# interface rather than inside the code under test, so `stk.py` and
# `callbacks.py` are exercised exactly as they run in production.
MPESA_CLIENT = env("MPESA_CLIENT", "payments.daraja.FakeDarajaClient")
# A secret path segment on the callback URL. Safaricom does not sign callbacks
# and does not offer mutual TLS, so without this the endpoint that confirms
# bookings is a public POST anyone can forge. Configured once with the shortcode.
MPESA_CALLBACK_TOKEN = env("MPESA_CALLBACK_TOKEN", "local-callback-token")

# Invariant 4 (CLAUDE.md §10): the USSD fallback line, as a constant rather than
# a string in a view. It ships in `packages/tokens` for the client; this is the
# copy the API puts in a refusal message.
USSD_FALLBACK = "*334#"

# The grace window. A hold whose STK push is unanswered survives its TTL by this
# much and no longer — see `scheduling/holds.hold_is_releasable`. It is the
# mechanism that makes `slotLost` rare instead of routine, and it is bounded by
# derivation rather than by a column, so nothing can extend it.
HOLD_GRACE_MINUTES = int(env("HOLD_GRACE_MINUTES", "2"))

# Reconciliation. We do not wait to be told what happened to a payment; we ask.
PAYMENT_QUERY_AFTER = timedelta(seconds=int(env("PAYMENT_QUERY_AFTER_SECONDS", "90")))
PAYMENT_QUERY_MAX_ATTEMPTS = int(env("PAYMENT_QUERY_MAX_ATTEMPTS", "4"))
PAYMENT_SWEEP_BATCH = int(env("PAYMENT_SWEEP_BATCH", "200"))
PAYMENT_ESCALATE_AFTER = timedelta(hours=int(env("PAYMENT_ESCALATE_AFTER_HOURS", "24")))

# Resend, bounded. Safaricom's own prompt lives about a minute, so anything
# faster than that just puts two prompts on one phone.
STK_RESEND_MAX = int(env("STK_RESEND_MAX", "2"))
STK_RESEND_MIN_INTERVAL_SECONDS = int(env("STK_RESEND_MIN_INTERVAL_SECONDS", "45"))

# Messaging. SMS first, behind the provider interface — CLAUDE.md §6 and §12.
# The console provider is the default because there is no gateway account yet;
# swapping it is one line here, which is the claim the interface is making.
MESSAGE_PROVIDER = env("MESSAGE_PROVIDER", "notifications.providers.ConsoleProvider")
SMS = {
    "API_KEY": env("SMS_API_KEY", ""),
    "SENDER_ID": env("SMS_SENDER_ID", "BOOKNASI"),
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}
