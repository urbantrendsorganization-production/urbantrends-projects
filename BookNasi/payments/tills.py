"""Which M-Pesa account a given booking's deposit is pushed to.

Before slice 13 there was one answer for the whole process: `settings.MPESA`,
read once, wrapped in one cached `DarajaClient`. CLAUDE.md §1 makes that wrong
for the SaaS front door — a salon's deposits must land in the salon's account —
so the answer is now per shop, and this module is where the shop becomes a
config dict.

## The config dict is the same shape as `settings.MPESA`

Deliberately. `DarajaClient` already takes its config as a constructor argument
and reads it through `self.config[...]`, so per-shop credentials needed no
change to the code that talks to Safaricom at all. The seam was already in the
right place; this module just supplies a different dict.

## What stays deployment-level, and why that is not an oversight

`BASE_URL`, `CALLBACK_URL`, `TIMEOUT_SECONDS` and the callback token are the
same for every shop:

- **The callback URL.** `payments/callbacks.py` finds a payment by
  `CheckoutRequestID`, which Safaricom makes unique across its whole platform
  and which carries no shortcode. One endpoint therefore serves any number of
  tills, and a per-shop callback URL would be a second way to get the same
  answer plus a new way for one shop's URL to be wrong.
- **The base URL.** Sandbox or production is a property of the deployment. A
  shop pointing at a different Daraja from the rest of the platform is not a
  feature, it is a misconfiguration with a longer name.

## Caching

One `DarajaClient` per credential set, keyed by shop, because the client holds
an OAuth token worth reusing — minting one per push doubles the round trips on
the leg where the whole latency budget lives. The cache key includes the
credentials themselves, so an owner who corrects a mistyped passkey gets a new
client on the next push rather than an old one holding a token minted with the
wrong consumer key.
"""

import logging

from django.conf import settings

from core import mpesa, secrets
from payments.daraja import DarajaMisconfigured, build_client

logger = logging.getLogger(__name__)


class ShopCannotCollect(DarajaMisconfigured):
    """This shop has no account for a deposit to land in.

    A `DarajaMisconfigured` on purpose: `payments/stk.py` already treats that as
    "no push was attempted and none should be retried", marks the payment
    `PUSH_FAILED` rather than `UNKNOWN`, and keeps it out of the reconciliation
    sweep — which is exactly right here. Nothing moved and nothing will until a
    person changes a setting, so a schedule would only be wrong repeatedly.
    """


def config_for(shop):
    """The `settings.MPESA`-shaped dict this shop's pushes should use.

    Raises `ShopCannotCollect` rather than falling back. The fallback is the
    whole defect: a shop half-way through connecting its own till would collect
    a real client's deposit into the platform account, successfully, with every
    screen reporting a healthy booking and the money in somebody else's bank.
    """
    from shops.models import CollectsVia

    if shop.collects_via == CollectsVia.PLATFORM:
        return _platform_config(shop)
    return _own_config(shop)


def _platform_config(shop):
    config = dict(settings.MPESA)
    if not (config["SHORTCODE"] and config["PASSKEY"]):
        raise ShopCannotCollect(
            f"{shop.name} collects through the platform account, which this "
            "deployment has not configured (MPESA_SHORTCODE / MPESA_PASSKEY)."
        )
    return config


def _own_config(shop):
    if not shop.mpesa_shortcode:
        raise ShopCannotCollect(f"{shop.name} has not connected an M-Pesa account yet.")

    try:
        consumer_key, consumer_secret, passkey = shop.open_mpesa_credentials()
    except secrets.CannotUnseal as exc:
        # Not `ShopCannotCollect`'s ordinary sentence: this shop believes it is
        # configured and the row says so, but the ciphertext will not open. That
        # is an operator problem — a key dropped from MPESA_CREDENTIAL_KEYS, or a
        # damaged column — and it needs to be loud, because the shop cannot see
        # it and the only symptom is bookings that stop taking deposits.
        logger.error("cannot open m-pesa credentials for shop %s: %s", shop.id, exc)
        raise ShopCannotCollect(
            f"{shop.name}'s stored M-Pesa credentials cannot be read. They must be re-entered."
        ) from exc

    missing = [
        name
        for name, value in (
            ("consumer key", consumer_key),
            ("consumer secret", consumer_secret),
            ("passkey", passkey),
        )
        if not value
    ]
    if missing:
        raise ShopCannotCollect(
            f"{shop.name}'s M-Pesa connection is incomplete — missing the {', '.join(missing)}."
        )

    transaction_type = shop.mpesa_transaction_type or mpesa.PAYBILL
    if transaction_type == mpesa.TILL and not shop.mpesa_till_number:
        # Also a database constraint (`shop_own_till_has_a_till_number`). Here
        # too because the constraint cannot see a shop whose type was changed in
        # the same transaction as something that rolled back, and because
        # `PartyB` defaulting to the store number is the failure that succeeds:
        # Safaricom accepts it, the client pays, and the money is not where the
        # shop is looking.
        raise ShopCannotCollect(
            f"{shop.name} collects by Buy Goods but has no till number, so a deposit "
            "would land against the store number instead."
        )

    return {
        **settings.MPESA,
        "CONSUMER_KEY": consumer_key,
        "CONSUMER_SECRET": consumer_secret,
        "SHORTCODE": shop.mpesa_shortcode,
        "PASSKEY": passkey,
        "TRANSACTION_TYPE": transaction_type,
        "TILL_NUMBER": shop.mpesa_till_number,
    }


def client_for(shop):
    """The Daraja client this shop's pushes go through."""
    return build_client(config_for(shop))
