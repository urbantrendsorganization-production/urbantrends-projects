"""Paybill and till produce different push bodies, and one field decides.

Daraja offers two STK transaction types and they are not interchangeable:

    CustomerPayBillOnline   PartyB = the paybill number
    CustomerBuyGoodsOnline  PartyB = the **till** number

`BusinessShortCode` is the store / head office number in *both* cases, because
it is what the password is derived from — and for a till it is not the till
number. Getting `PartyB` wrong is the expensive mistake: Safaricom may well
accept the push, the client's PIN prompt appears, they pay, and the money does
not arrive where the shop is looking for it. Nothing errors. Nobody finds out
until somebody reconciles a day's takings.

So these tests assert the body itself rather than "a push happened". The one
that matters is `test_a_till_push_sends_the_till_number_as_party_b`.

The real `DarajaClient` is instantiated here with a plain dict — it is never
otherwise touched by a test, and it is not used to talk to anything. Only the
body-building is exercised; `_post` is never reached.
"""

import pytest

from payments.daraja import PAYBILL, TILL, DarajaClient, DarajaMisconfigured

pytestmark = pytest.mark.loadbearing

STORE = "3000000"
TILL_NUMBER = "9999999"


def config(**over):
    """Placeholders only. CLAUDE.md §5: nothing real, sandbox included."""
    return {
        "BASE_URL": "https://sandbox.safaricom.co.ke",
        "CONSUMER_KEY": "placeholder",
        "CONSUMER_SECRET": "placeholder",
        "SHORTCODE": STORE,
        "PASSKEY": "placeholder",
        "CALLBACK_URL": "https://example.test/api/mpesa/tok/",
        "TIMEOUT_SECONDS": 20,
        "TRANSACTION_TYPE": PAYBILL,
        "TILL_NUMBER": "",
        **over,
    }


def body_from(client):
    """The push body, captured without going near the network."""
    captured = {}

    def fake_post(path, body, *, headers=None):
        captured["path"] = path
        captured["body"] = body
        return {"ResponseCode": "0", "CheckoutRequestID": "ws_CO_1", "MerchantRequestID": "m1"}

    client._post = fake_post
    client._auth = lambda: {"Authorization": "Bearer placeholder"}
    client.push(amount=875, phone="+254712345678", reference="BK-4F7K2Q", description="Deposit")
    return captured["body"]


class TestPaybill:
    def test_it_is_the_default(self):
        """Every existing deployment is a paybill one and must stay working
        without setting anything new."""
        client = DarajaClient(config(TRANSACTION_TYPE=""))

        assert client.transaction_type == PAYBILL

    def test_party_b_is_the_shortcode(self):
        body = body_from(DarajaClient(config()))

        assert body["TransactionType"] == PAYBILL
        assert body["BusinessShortCode"] == STORE
        assert body["PartyB"] == STORE

    def test_no_till_number_is_needed(self):
        client = DarajaClient(config(TILL_NUMBER=""))

        assert client.party_b == STORE


class TestTill:
    def test_a_till_push_sends_the_till_number_as_party_b(self):
        """**The one that matters.**

        `BusinessShortCode` stays the store number because the password is
        derived from it; `PartyB` becomes the till, because that is where the
        client's deposit lands. Sending the store number here is the silent
        failure this whole module exists for.
        """
        body = body_from(DarajaClient(config(TRANSACTION_TYPE=TILL, TILL_NUMBER=TILL_NUMBER)))

        assert body["TransactionType"] == TILL
        assert body["BusinessShortCode"] == STORE, "the password is derived from this"
        assert body["PartyB"] == TILL_NUMBER, "the money lands here"
        assert body["PartyB"] != body["BusinessShortCode"]

    def test_the_password_still_uses_the_store_number(self):
        """Not the till. Daraja rejects a password derived from the till number,
        and the rejection is opaque."""
        import base64

        body = body_from(DarajaClient(config(TRANSACTION_TYPE=TILL, TILL_NUMBER=TILL_NUMBER)))

        decoded = base64.b64decode(body["Password"]).decode()
        assert decoded.startswith(STORE)
        assert not decoded.startswith(TILL_NUMBER)

    def test_a_missing_till_number_refuses_the_push(self):
        """Rather than silently falling back to the shortcode, which would send
        a real client's real money to the wrong account and succeed."""
        client = DarajaClient(config(TRANSACTION_TYPE=TILL, TILL_NUMBER=""))

        with pytest.raises(DarajaMisconfigured) as exc:
            _ = client.party_b
        assert "MPESA_TILL_NUMBER" in str(exc.value)

    def test_whitespace_is_not_a_till_number(self):
        client = DarajaClient(config(TRANSACTION_TYPE=TILL, TILL_NUMBER="   "))

        with pytest.raises(DarajaMisconfigured):
            _ = client.party_b


class TestAThirdTypeIsRefused:
    @pytest.mark.parametrize(
        "bad", ["CustomerBuyGoods", "paybill", "CUSTOMERPAYBILLONLINE", "BuyGoods"]
    )
    def test_only_the_two_daraja_offers(self, bad):
        client = DarajaClient(config(TRANSACTION_TYPE=bad))

        with pytest.raises(DarajaMisconfigured) as exc:
            _ = client.transaction_type
        assert "MPESA_TRANSACTION_TYPE" in str(exc.value)


class TestMisconfigurationIsNotRetried:
    def test_it_fails_the_push_rather_than_leaving_it_unknown(self, db, held, settings):
        """`UNKNOWN` means "the prompt may be on the phone and we cannot tell",
        and the reconciliation sweep chases it. A misconfiguration is not that:
        no push was attempted, and retrying it would be wrong the same way every
        time. `PUSH_FAILED` keeps it out of the sweep.
        """
        from payments.daraja import reset_client
        from payments.states import PaymentState
        from payments.stk import initiate_push

        settings.MPESA_CLIENT = "payments.daraja.DarajaClient"
        settings.MPESA = config(TRANSACTION_TYPE=TILL, TILL_NUMBER="")
        reset_client()

        payment = initiate_push(held)

        payment.refresh_from_db()
        assert payment.state == PaymentState.PUSH_FAILED
        assert payment.state != PaymentState.UNKNOWN
        reset_client()
