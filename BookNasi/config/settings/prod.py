from config.env import MissingSetting, env, env_list

from .base import *  # noqa: F403

DEBUG = False
SECRET_KEY = env("DJANGO_SECRET_KEY", required=True)
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS")

# Three of slice 6's settings default to something that is right for local work
# and silently catastrophic in production. None of them fails loudly on its own,
# so they are made required here rather than left to a deploy checklist:
#
# - `MPESA_CLIENT` defaults to `FakeDarajaClient`, which accepts every push and
#   confirms bookings without any money moving.
# - `MESSAGE_PROVIDER` defaults to `ConsoleProvider`, which sends nothing —
#   every confirmation and reminder goes to a log nobody reads.
# - `MPESA_CALLBACK_TOKEN` defaults to a literal committed in this repository.
#   `payments/views.py` explains that this path segment is the only thing
#   between the callback endpoint and a forged `ResultCode: 0`; falling back to
#   a published value means anyone who can read the repo can confirm a booking.
#
# Live Daraja is already opt-in — the real client is never reached without
# `MPESA_CLIENT` naming it. This closes the other direction: a production deploy
# that forgets one of these must not start.
MPESA_CALLBACK_TOKEN = env("MPESA_CALLBACK_TOKEN", required=True)
MPESA_CLIENT = env("MPESA_CLIENT", required=True)
MESSAGE_PROVIDER = env("MESSAGE_PROVIDER", required=True)

#: The local stand-ins, by import path. Named rather than sniffed for "Fake" so
#: that a real client someone calls `FakeraDaraja` is not refused and a stand-in
#: someone adds later is not quietly allowed.
LOCAL_STAND_INS = {
    "payments.daraja.FakeDarajaClient",
    "notifications.providers.ConsoleProvider",
}

for _name, _value in (
    ("MPESA_CLIENT", MPESA_CLIENT),
    ("MESSAGE_PROVIDER", MESSAGE_PROVIDER),
):
    if _value in LOCAL_STAND_INS:
        raise MissingSetting(
            f"{_name} is set to {_value}, which is a local stand-in and must not "
            "be selected under production settings."
        )

# A till deployment must carry its till number. Without it `daraja.py` refuses
# every push — correctly, because `PartyB` would otherwise be the store number
# and the client's deposit would land somewhere the shop is not looking — but it
# refuses one booking at a time, at the moment a client is being asked for
# money. Failing at boot instead turns a slow bleed into a deploy that does not
# start. See `payments/daraja.py`.
if MPESA["TRANSACTION_TYPE"] == MPESA_TILL and not MPESA["TILL_NUMBER"]:  # noqa: F405
    raise MissingSetting(
        f"MPESA_TILL_NUMBER must be set when MPESA_TRANSACTION_TYPE is {MPESA_TILL}"  # noqa: F405
    )

if MPESA["TRANSACTION_TYPE"] not in (MPESA_PAYBILL, MPESA_TILL):  # noqa: F405
    raise MissingSetting(
        f"MPESA_TRANSACTION_TYPE must be {MPESA_PAYBILL} or {MPESA_TILL}, "  # noqa: F405
        f"got {MPESA['TRANSACTION_TYPE']!r}"  # noqa: F405
    )

# The credentials themselves. `base.py` defaults each to "" so local work needs
# no M-Pesa account at all; production without them is a shop that cannot take
# a deposit, which is the product.
for _key in ("CONSUMER_KEY", "CONSUMER_SECRET", "SHORTCODE", "PASSKEY", "CALLBACK_URL"):
    if not MPESA[_key]:  # noqa: F405
        raise MissingSetting(f"MPESA_{_key} must be set in the environment")

# Caddy terminates TLS and proxies to a container bound to 127.0.0.1.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
