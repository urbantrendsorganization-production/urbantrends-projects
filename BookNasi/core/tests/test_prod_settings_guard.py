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

REQUIRED = {
    "DJANGO_SECRET_KEY": "not-the-real-one",
    "DATABASE_URL": "postgres://u:p@localhost:5432/booknasi",
    "ALLOWED_HOSTS": "booknasi.co.ke",
    "MPESA_CALLBACK_TOKEN": "a-real-token",
    "MPESA_CLIENT": "payments.daraja.DarajaClient",
    "MESSAGE_PROVIDER": "notifications.providers.SmsProvider",
}


def _load_prod(monkeypatch, **overrides):
    """Import `config.settings.prod` under a given environment."""
    for key, value in {**REQUIRED, **overrides}.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
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
