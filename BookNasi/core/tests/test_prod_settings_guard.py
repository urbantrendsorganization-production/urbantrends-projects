"""Production must not come up on the local stand-ins.

Three of slice 6's settings are right for local work and silently catastrophic
in production, and none of them fails loudly on its own:

- `MPESA_CLIENT` defaults to `FakeDarajaClient`, which accepts every push and
  confirms bookings without any money moving.
- `MESSAGE_PROVIDER` defaults to `ConsoleProvider`, which sends nothing.
- `MPESA_CALLBACK_TOKEN` defaults to a literal committed in this repository, and
  `payments/views.py` is explicit that this path segment is the only thing
  between the callback endpoint and a forged `ResultCode: 0`.

A deploy that forgets one of them is not a degraded deploy — it is a shop taking
bookings that were never paid for, or an endpoint anyone who can read the repo
can confirm a booking through. So `config/settings/prod.py` refuses to import.

These tests exercise the settings module directly rather than through Django's
setup, because the failure has to happen at import time — before anything is
serving.
"""

import importlib

import pytest

from config.env import MissingSetting

#: Placeholders only. Nothing here is a credential — CLAUDE.md §5 and §11 — and
#: a test that needed a real one would be a test that could not run in CI.
REQUIRED = {
    "DJANGO_SECRET_KEY": "not-the-real-one",
    "DATABASE_URL": "postgres://u:p@localhost:5432/booknasi",
    "ALLOWED_HOSTS": "booknasi.co.ke",
    "MPESA_CALLBACK_TOKEN": "a-real-token",
    "MPESA_CLIENT": "payments.daraja.DarajaClient",
    "MESSAGE_PROVIDER": "notifications.providers.SmsProvider",
    "MPESA_CONSUMER_KEY": "placeholder-key",
    "MPESA_CONSUMER_SECRET": "placeholder-secret",
    "MPESA_SHORTCODE": "000000",
    "MPESA_PASSKEY": "placeholder-passkey",
    "MPESA_CALLBACK_URL": "https://booknasi.co.ke/api/mpesa/tok/",
    "MPESA_TRANSACTION_TYPE": "CustomerPayBillOnline",
    "MPESA_TILL_NUMBER": "",
    # Slice 13. Not a credential either — a Fernet key generated for this file,
    # which encrypts nothing outside it. Production refuses to boot without one
    # because a shop's own passkey would otherwise have nowhere safe to live.
    "MPESA_CREDENTIAL_KEYS": "2026t:0iyRDgKPPXGKa_LVJoaVEjHIH34ozzcE0IN7oIhQAAg=",
}


def _load_prod(monkeypatch, **overrides):
    """Import `config.settings.prod` under a given environment.

    **`base` is reloaded first, and that is not incidental.** `MPESA` is a dict
    built at import time, so reloading only `prod` re-runs its `from .base
    import *` against a module object that still holds the values from whenever
    it was first imported — and every assertion below would then be checking a
    stale dict while appearing to pass.
    """
    for key, value in {**REQUIRED, **overrides}.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    importlib.reload(importlib.import_module("config.settings.base"))
    module = importlib.import_module("config.settings.prod")
    return importlib.reload(module)


class TestTheStandInsAreRefused:
    def test_the_fake_daraja_client_cannot_be_selected(self, monkeypatch):
        with pytest.raises(MissingSetting) as exc:
            _load_prod(monkeypatch, MPESA_CLIENT="payments.daraja.FakeDarajaClient")

        assert "MPESA_CLIENT" in str(exc.value)
        assert "local stand-in" in str(exc.value)

    def test_the_console_message_provider_cannot_be_selected(self, monkeypatch):
        with pytest.raises(MissingSetting) as exc:
            _load_prod(monkeypatch, MESSAGE_PROVIDER="notifications.providers.ConsoleProvider")

        assert "MESSAGE_PROVIDER" in str(exc.value)

    def test_a_real_client_whose_name_contains_fake_is_still_allowed(self, monkeypatch):
        """Named, not sniffed. A denylist of import paths refuses exactly the
        two stand-ins; a substring match on "Fake" would refuse a real client
        somebody unfortunately named, and would quietly allow a third stand-in
        added later."""
        prod = _load_prod(monkeypatch, MPESA_CLIENT="payments.daraja.FakerainDarajaClient")

        assert prod.MPESA_CLIENT == "payments.daraja.FakerainDarajaClient"


class TestTheSecretsAreRequired:
    @pytest.mark.parametrize(
        "name",
        ["MPESA_CALLBACK_TOKEN", "MPESA_CLIENT", "MESSAGE_PROVIDER"],
    )
    def test_a_missing_setting_stops_the_import(self, monkeypatch, name):
        with pytest.raises(MissingSetting) as exc:
            _load_prod(monkeypatch, **{name: None})

        assert name in str(exc.value)

    def test_the_committed_callback_token_is_not_inherited_from_base(self, monkeypatch):
        """The base default is a literal in the repository. Production must
        carry its own or refuse to start — falling back here is the difference
        between an authenticated callback and a public one."""
        prod = _load_prod(monkeypatch, MPESA_CALLBACK_TOKEN="a-real-token")

        assert prod.MPESA_CALLBACK_TOKEN == "a-real-token"

        with pytest.raises(MissingSetting):
            _load_prod(monkeypatch, MPESA_CALLBACK_TOKEN="")


class TestPaybillAndTill:
    """The two STK modes, and the one that has a second required setting.

    A till deployment sending the *store* number as `PartyB` is the failure this
    guards: Safaricom may accept it, the prompt appears, the client pays, and
    the money does not arrive where the shop is looking. `daraja.py` refuses the
    push; this refuses the deploy, which is the cheaper of the two.
    """

    def test_paybill_needs_no_till_number(self, monkeypatch):
        prod = _load_prod(monkeypatch, MPESA_TRANSACTION_TYPE="CustomerPayBillOnline")

        assert prod.MPESA["TRANSACTION_TYPE"] == "CustomerPayBillOnline"

    def test_till_without_a_till_number_stops_the_deploy(self, monkeypatch):
        with pytest.raises(MissingSetting) as exc:
            _load_prod(
                monkeypatch,
                MPESA_TRANSACTION_TYPE="CustomerBuyGoodsOnline",
                MPESA_TILL_NUMBER="",
            )

        assert "MPESA_TILL_NUMBER" in str(exc.value)

    def test_till_with_one_is_allowed(self, monkeypatch):
        prod = _load_prod(
            monkeypatch,
            MPESA_TRANSACTION_TYPE="CustomerBuyGoodsOnline",
            MPESA_TILL_NUMBER="000111",
        )

        assert prod.MPESA["TILL_NUMBER"] == "000111"

    def test_a_third_transaction_type_is_refused(self, monkeypatch):
        """There are two. A typo here is a rejection at Safaricom carrying an
        error code the client never sees the inside of."""
        with pytest.raises(MissingSetting) as exc:
            _load_prod(monkeypatch, MPESA_TRANSACTION_TYPE="CustomerBuyGoods")

        assert "MPESA_TRANSACTION_TYPE" in str(exc.value)

    @pytest.mark.parametrize(
        "name",
        ["MPESA_CONSUMER_KEY", "MPESA_CONSUMER_SECRET", "MPESA_SHORTCODE", "MPESA_PASSKEY"],
    )
    def test_every_credential_is_required(self, monkeypatch, name):
        """`base.py` defaults each to "" so local work needs no M-Pesa account.
        Production without them is a shop that cannot take a deposit."""
        with pytest.raises(MissingSetting) as exc:
            _load_prod(monkeypatch, **{name: ""})

        assert name.replace("MPESA_", "") in str(exc.value)
