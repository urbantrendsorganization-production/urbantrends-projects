"""Whose account the deposit lands in.

Every other payment test in this repo asks whether a push happened, what state
the row ended in, and whether a callback was processed once. None of them could
tell you where the money went, because until slice 13 there was only one
answer. `MPESA_SHORTCODE` was environment-level, so a deployment serving two
salons collected both salons' deposits into the same till — fine for a
single-tenant pilot and, for the SaaS front door in CLAUDE.md §1, a salon's
money arriving in somebody else's bank account.

The failure mode is the expensive kind: nothing errors. Safaricom accepts the
push, the client's PIN prompt appears, they pay, the callback confirms the
booking, the screen says paid, and the shop finds out when it reconciles a
week's takings — or does not.

So these tests assert the shortcode on the wire, not the state of the row.
`FakeDarajaClient` records it per push for exactly this reason.
"""

import pytest

from payments.daraja import DarajaUnavailable
from payments.states import PaymentState
from payments.stk import initiate_push
from payments.tests.conftest import hold_at
from shops.models import CollectsVia, Shop

pytestmark = pytest.mark.loadbearing

OWN_SHORTCODE = "5550001"
OWN_TILL = "5550002"


def connect(shop, *, shortcode=OWN_SHORTCODE, transaction_type="", till=""):
    """Give a shop its own M-Pesa. Placeholders — CLAUDE.md §5."""
    shop.collects_via = CollectsVia.OWN
    shop.mpesa_shortcode = shortcode
    shop.mpesa_transaction_type = transaction_type
    shop.mpesa_till_number = till
    shop.seal_mpesa_credentials(
        consumer_key="own-placeholder-key",
        consumer_secret="own-placeholder-secret",
        passkey="own-placeholder-passkey",
    )
    shop.save()
    return shop


class TestThePushGoesToTheShopsOwnTill:
    def test_the_shortcode_on_the_wire_is_the_shops(self, held, fake_daraja, shop_setup):
        connect(shop_setup.shop)

        initiate_push(held)

        assert fake_daraja.pushes[-1]["shortcode"] == OWN_SHORTCODE

    def test_and_not_the_deployments(self, held, fake_daraja, shop_setup, settings):
        """The assertion that would have failed before slice 13, and the only
        one here that could not be satisfied by a push that simply happened."""
        connect(shop_setup.shop)

        initiate_push(held)

        assert fake_daraja.pushes[-1]["shortcode"] != settings.MPESA["SHORTCODE"]

    def test_a_buy_goods_shop_sends_its_till_as_the_destination(
        self, held, fake_daraja, shop_setup
    ):
        """Store number and till number are different numbers. `PartyB` is the
        till; `BusinessShortCode` is the store. Swapping them is a push
        Safaricom accepts and money the shop never sees."""
        connect(
            shop_setup.shop,
            transaction_type="CustomerBuyGoodsOnline",
            till=OWN_TILL,
        )

        initiate_push(held)

        last = fake_daraja.pushes[-1]
        assert last["shortcode"] == OWN_SHORTCODE
        assert last["till_number"] == OWN_TILL
        assert last["transaction_type"] == "CustomerBuyGoodsOnline"

    def test_a_shop_on_the_platform_account_still_uses_the_deployments(
        self, held, fake_daraja, shop_setup, settings
    ):
        """`PLATFORM` is a real destination, not a legacy state. Every shop
        predating slice 13 is on it (`shops/migrations/0004`), and their
        behaviour must be exactly what it was."""
        assert shop_setup.shop.collects_via == CollectsVia.PLATFORM

        initiate_push(held)

        assert fake_daraja.pushes[-1]["shortcode"] == settings.MPESA["SHORTCODE"]


class TestTwoShopsOnOneDeployment:
    def test_each_ones_deposit_goes_to_its_own_account(
        self, db, fake_daraja, shop_setup, rival_shop
    ):
        """The isolation that is the whole point of the slice.

        A single-shop test cannot see this: one shop with its own credentials
        looks identical whether the resolution is per shop or per process. Two
        shops, two shortcodes, in one process, is the shape that tells them
        apart — and the client cache is keyed by credentials, so this also
        catches a cache that hands the second shop the first one's client.
        """
        connect(shop_setup.shop, shortcode="5550001")
        connect(rival_shop.shop, shortcode="6660001")

        initiate_push(hold_at(shop_setup, 10))
        initiate_push(hold_at(rival_shop, 11))

        assert [push["shortcode"] for push in fake_daraja.pushes[-2:]] == ["5550001", "6660001"]

    def test_one_shops_broken_connection_does_not_stop_the_other(
        self, db, fake_daraja, shop_setup, rival_shop
    ):
        connect(shop_setup.shop)
        rival_shop.shop.collects_via = CollectsVia.OWN
        rival_shop.shop.save()  # no credentials at all

        good = initiate_push(hold_at(shop_setup, 10))
        bad = initiate_push(hold_at(rival_shop, 11))

        assert good.state == PaymentState.PUSHED
        assert bad.state == PaymentState.PUSH_FAILED


class TestAShopThatCannotCollect:
    def test_a_brand_new_shop_cannot_take_a_deposit(self, db, org_a, fake_daraja):
        """The default, and it is deliberately the restrictive one.

        `collects_via` defaults to OWN with nothing filled in, so a shop created
        today cannot push until somebody connects an account. The alternative —
        falling back to the platform till — is the defect this slice exists to
        remove: a half-configured shop collecting a real client's deposit into
        our account, successfully, with every screen reporting a healthy
        booking.
        """
        fresh = Shop.objects.create(organization=org_a.organization, name="New", slug="new-shop")

        assert fresh.collects_via == CollectsVia.OWN
        assert fresh.can_take_deposits is False

    def test_the_payment_fails_rather_than_going_unknown(self, held, shop_setup):
        """`UNKNOWN` means "the prompt may be on the phone and we cannot tell",
        and the reconciliation sweep chases it forever. Nothing was sent here
        and nothing will be until a person changes a setting, so retrying on a
        schedule would only be wrong on a schedule."""
        shop_setup.shop.collects_via = CollectsVia.OWN
        shop_setup.shop.save()

        payment = initiate_push(held)

        assert payment.state == PaymentState.PUSH_FAILED
        assert payment.state != PaymentState.UNKNOWN

    def test_nothing_is_pushed_at_all(self, held, fake_daraja, shop_setup):
        shop_setup.shop.collects_via = CollectsVia.OWN
        shop_setup.shop.save()
        before = len(fake_daraja.pushes)

        initiate_push(held)

        assert len(fake_daraja.pushes) == before

    def test_half_a_connection_is_no_connection(self, held, fake_daraja, shop_setup):
        """A shortcode with no passkey. This is the interrupted-onboarding case,
        and it must not resolve to the platform account."""
        shop_setup.shop.collects_via = CollectsVia.OWN
        shop_setup.shop.mpesa_shortcode = OWN_SHORTCODE
        shop_setup.shop.save()
        before = len(fake_daraja.pushes)

        payment = initiate_push(held)

        assert payment.state == PaymentState.PUSH_FAILED
        assert len(fake_daraja.pushes) == before

    def test_a_platform_shop_on_a_deployment_with_no_platform_till(
        self, held, fake_daraja, shop_setup, settings
    ):
        settings.MPESA = {**settings.MPESA, "SHORTCODE": "", "PASSKEY": ""}
        before = len(fake_daraja.pushes)

        payment = initiate_push(held)

        assert payment.state == PaymentState.PUSH_FAILED
        assert len(fake_daraja.pushes) == before

    def test_unreadable_credentials_do_not_read_as_unconfigured(
        self, held, fake_daraja, shop_setup, settings
    ):
        """A row sealed under a key that has since been dropped.

        It must not push, and it must not push *to the platform account* — the
        shop believes it is connected, and the money would go somewhere neither
        party expects.
        """
        connect(shop_setup.shop)
        settings.MPESA_CREDENTIAL_KEYS = ["2026z:" + _another_key()]
        before = len(fake_daraja.pushes)

        payment = initiate_push(held)

        assert payment.state == PaymentState.PUSH_FAILED
        assert len(fake_daraja.pushes) == before


class TestReconciliationAsksTheRightAccount:
    def test_the_query_uses_the_shops_credentials(self, held, fake_daraja, shop_setup):
        """A Daraja query authenticates against the shortcode that took the
        push. Asking the platform account about a salon's checkout id is a
        rejection, which `reconcile` would record as "no answer from Safaricom"
        — a payment stuck `UNKNOWN` forever, and a slot released under a client
        who paid.
        """
        from payments.reconcile import reconcile

        connect(shop_setup.shop)
        payment = initiate_push(held)

        reconcile(payment)

        assert fake_daraja.query_shortcodes[-1] == OWN_SHORTCODE

    def test_a_query_for_a_shop_that_disconnected_is_not_retried_forever(
        self, held, fake_daraja, shop_setup
    ):
        from payments.reconcile import reconcile

        connect(shop_setup.shop)
        payment = initiate_push(held)

        shop_setup.shop.collects_via = CollectsVia.OWN
        shop_setup.shop.mpesa_shortcode = ""
        shop_setup.shop.save()
        payment.appointment.shop.refresh_from_db()

        assert reconcile(payment) == "no-credentials"


class TestTheClientCacheIsKeyedByCredentials:
    def test_correcting_a_mistyped_secret_takes_effect_on_the_next_push(
        self, db, shop_setup, settings
    ):
        """A cache keyed by shop would hand back a client holding an OAuth token
        minted with the wrong consumer key, and the correction would appear not
        to work until the process restarted."""
        from payments.daraja import DarajaClient, build_client

        settings.MPESA_CLIENT = "payments.daraja.DarajaClient"
        connect(shop_setup.shop)
        first = build_client(_config_of(shop_setup.shop))

        shop_setup.shop.seal_mpesa_credentials(consumer_secret="corrected-placeholder")
        shop_setup.shop.save()
        second = build_client(_config_of(shop_setup.shop))

        assert isinstance(first, DarajaClient)
        assert first is not second

    def test_the_same_credentials_reuse_one_client(self, db, shop_setup, settings):
        """The reason the cache exists: `DarajaClient` holds an access token,
        and minting one per push doubles the round trips on the leg where the
        whole latency budget lives."""
        from payments.daraja import build_client

        settings.MPESA_CLIENT = "payments.daraja.DarajaClient"
        connect(shop_setup.shop)

        assert build_client(_config_of(shop_setup.shop)) is build_client(
            _config_of(shop_setup.shop)
        )

    def test_the_stand_in_is_shared_across_shops(self, db, shop_setup, rival_shop):
        """One place for a test to arm an error and one list of recorded
        pushes. The config still travels, which is what every assertion above
        depends on."""
        from payments.daraja import build_client

        connect(shop_setup.shop)
        connect(rival_shop.shop, shortcode="6660001")

        assert build_client(_config_of(shop_setup.shop)) is build_client(
            _config_of(rival_shop.shop)
        )


class TestTheErrorIsTheRightKind:
    def test_shop_cannot_collect_is_a_misconfiguration_not_an_outage(self):
        """`DarajaUnavailable` is retried by the sweep; `DarajaMisconfigured` is
        not. Getting this wrong means either a shop's broken connection is
        retried every five minutes forever, or a genuine Safaricom outage is
        written off as a settings problem."""
        from payments.daraja import DarajaMisconfigured
        from payments.tills import ShopCannotCollect

        assert issubclass(ShopCannotCollect, DarajaMisconfigured)
        assert not issubclass(ShopCannotCollect, DarajaUnavailable)


def _another_key():
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


def _config_of(shop):
    from payments.tills import config_for

    shop.refresh_from_db()
    return config_for(shop)
