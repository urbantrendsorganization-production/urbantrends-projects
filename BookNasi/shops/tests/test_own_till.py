"""Connecting a shop's own M-Pesa, from the screen that does it.

`payments/tests/test_per_shop_till.py` covers where the money goes.
This file covers the surface an owner touches to decide that: who may read and
write it, what comes back out, and the mistakes it refuses to save.

Three of those refusals are worth naming, because each one is a mistake that
otherwise succeeds:

- **A Buy Goods connection with no till number.** Safaricom accepts a push whose
  `PartyB` is the store number. The client pays. The money is not where the
  shop is looking.
- **A till number equal to the store number.** Same outcome, arrived at by
  copying the wrong field off the Safaricom portal.
- **A secret written on a deployment that cannot encrypt it.** Refused before
  anything is stored, rather than in a 500 after the owner has pasted a live
  passkey into a form.
"""

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse

from core import secrets
from orgs.models import Membership, Role
from shops.models import CollectsVia, Shop

pytestmark = pytest.mark.loadbearing

SHORTCODE = "5550001"
TILL = "5550002"
PASSKEY = "placeholder-passkey-value"


def url(shop):
    return reverse("shops:shop-mpesa", args=[shop.organization_id, shop.id])


def disconnect_url(shop):
    return reverse("shops:shop-mpesa-disconnect", args=[shop.organization_id, shop.id])


def connected(shop, **over):
    payload = {
        "collects_via": CollectsVia.OWN,
        "mpesa_shortcode": SHORTCODE,
        "mpesa_transaction_type": "",
        "mpesa_till_number": "",
        **over,
    }
    for field, value in payload.items():
        setattr(shop, field, value)
    shop.seal_mpesa_credentials(
        consumer_key="placeholder-key",
        consumer_secret="placeholder-secret",
        passkey=PASSKEY,
    )
    shop.save()
    return shop


class TestOnlyTheOwner:
    """Stricter than every other endpoint on this shop, and deliberately.

    A manager already sets prices and deposit rules, so they decide how much is
    taken. Where it lands is a different act and a quiet one — the number comes
    back masked, so nobody else on the account could see it had changed.
    """

    def test_the_owner_can_read_it(self, api_client, shop_setup):
        api_client.force_login(shop_setup.org.owner)

        response = api_client.get(url(shop_setup.shop))

        assert response.status_code == 200

    def test_a_manager_cannot(self, api_client, shop_setup, make_user):
        manager = make_user(full_name="Branch Manager")
        Membership.objects.create(
            organization=shop_setup.organization,
            user=manager,
            role=Role.MANAGER,
            accepted_at=shop_setup.shop.created_at,
        )
        api_client.force_login(manager)

        response = api_client.get(url(shop_setup.shop))

        assert response.status_code == 403

    def test_a_stylist_cannot(self, api_client, shop_setup):
        api_client.force_login(shop_setup.org.stylist)

        assert api_client.get(url(shop_setup.shop)).status_code == 403

    def test_a_manager_cannot_write_it_either(self, api_client, shop_setup, make_user):
        """The read being refused is not the protection — a 403 on GET with a
        working PATCH is a lock on the wrong door."""
        manager = make_user(full_name="Branch Manager 2")
        Membership.objects.create(
            organization=shop_setup.organization,
            user=manager,
            role=Role.MANAGER,
            accepted_at=shop_setup.shop.created_at,
        )
        api_client.force_login(manager)

        response = api_client.patch(
            url(shop_setup.shop), {"mpesa_shortcode": "9999999"}, format="json"
        )

        assert response.status_code == 403

    def test_another_orgs_shop_is_a_404_not_a_403(self, api_client, shop_setup, rival_shop):
        api_client.force_login(shop_setup.org.owner)

        assert api_client.get(url(rival_shop.shop)).status_code == 404

    def test_signed_out_is_refused(self, api_client, shop_setup):
        assert api_client.get(url(shop_setup.shop)).status_code in (401, 403)


class TestSecretsGoInAndDoNotComeOut:
    def test_the_passkey_is_never_in_the_response(self, api_client, shop_setup):
        api_client.force_login(shop_setup.org.owner)

        response = api_client.patch(
            url(shop_setup.shop),
            {
                "collects_via": "own",
                "mpesa_shortcode": SHORTCODE,
                "consumer_key": "placeholder-key",
                "consumer_secret": "placeholder-secret",
                "passkey": PASSKEY,
            },
            format="json",
        )

        assert response.status_code == 200
        assert PASSKEY not in str(response.data)
        assert "placeholder-secret" not in str(response.data)

    def test_what_comes_back_is_the_tail_and_nothing_else(self, api_client, shop_setup):
        """Enough to answer "is the thing I typed still the thing that is
        stored". A field an owner can neither read nor confirm is a field they
        re-enter every visit, and re-entering a passkey is how it ends up in a
        WhatsApp message to themselves."""
        connected(shop_setup.shop)
        api_client.force_login(shop_setup.org.owner)

        response = api_client.get(url(shop_setup.shop))

        assert response.data["passkey_masked"] == secrets.mask(PASSKEY)
        assert response.data["passkey_masked"].endswith(PASSKEY[-4:])
        assert PASSKEY not in response.data["passkey_masked"]

    def test_an_unset_secret_masks_to_nothing(self, api_client, shop_setup):
        """ "Not set" and "set, hidden" have to look different, or the screen
        cannot tell an owner what is left to do."""
        api_client.force_login(shop_setup.org.owner)

        response = api_client.get(url(shop_setup.shop))

        assert response.data["passkey_masked"] == ""

    def test_the_plaintext_is_not_an_attribute_on_the_model(self, db, shop_setup):
        """One `model_to_dict`, one `__all__` serializer, one debug page away
        from a log otherwise. Reading it is a method call somebody has to write
        out, and `payments/tills.py` is the only caller."""
        connected(shop_setup.shop)

        assert not hasattr(shop_setup.shop, "mpesa_passkey")
        assert PASSKEY not in str(shop_setup.shop.__dict__)

    def test_it_is_encrypted_in_the_column(self, db, shop_setup):
        connected(shop_setup.shop)
        shop_setup.shop.refresh_from_db()

        assert PASSKEY.encode() not in bytes(shop_setup.shop.mpesa_passkey_enc)
        assert shop_setup.shop.open_mpesa_credentials()[2] == PASSKEY


class TestPartialUpdates:
    def test_editing_the_shortcode_alone_leaves_the_passkey_alone(self, api_client, shop_setup):
        """An owner correcting a mistyped paybill sends nothing else. If absent
        meant empty, that edit would disconnect the shop and the next client
        would get no prompt."""
        connected(shop_setup.shop)
        api_client.force_login(shop_setup.org.owner)

        api_client.patch(url(shop_setup.shop), {"mpesa_shortcode": "5559999"}, format="json")

        shop_setup.shop.refresh_from_db()
        assert shop_setup.shop.mpesa_shortcode == "5559999"
        assert shop_setup.shop.open_mpesa_credentials()[2] == PASSKEY

    def test_an_explicit_blank_clears_it(self, api_client, shop_setup):
        """Absent and empty differ, and both are reachable. Without the second,
        a leaked passkey could not be removed without deleting the shop."""
        connected(shop_setup.shop)
        api_client.force_login(shop_setup.org.owner)

        api_client.patch(url(shop_setup.shop), {"passkey": ""}, format="json")

        shop_setup.shop.refresh_from_db()
        assert shop_setup.shop.open_mpesa_credentials()[2] == ""
        assert shop_setup.shop.can_take_deposits is False

    def test_switching_to_the_platform_and_back_keeps_the_keys(self, api_client, shop_setup):
        """Otherwise trying the platform account for a fortnight costs an owner
        their Daraja credentials and a trip back to the Safaricom portal."""
        connected(shop_setup.shop)
        api_client.force_login(shop_setup.org.owner)

        api_client.patch(url(shop_setup.shop), {"collects_via": "platform"}, format="json")
        api_client.patch(url(shop_setup.shop), {"collects_via": "own"}, format="json")

        shop_setup.shop.refresh_from_db()
        assert shop_setup.shop.can_take_deposits is True


class TestTheMistakesItRefuses:
    def test_buy_goods_with_no_till_number(self, api_client, shop_setup):
        connected(shop_setup.shop)
        api_client.force_login(shop_setup.org.owner)

        response = api_client.patch(
            url(shop_setup.shop),
            {"mpesa_transaction_type": "CustomerBuyGoodsOnline"},
            format="json",
        )

        assert response.status_code == 400
        assert "mpesa_till_number" in response.data

    def test_a_till_number_equal_to_the_store_number(self, api_client, shop_setup):
        connected(shop_setup.shop)
        api_client.force_login(shop_setup.org.owner)

        response = api_client.patch(
            url(shop_setup.shop),
            {"mpesa_transaction_type": "CustomerBuyGoodsOnline", "mpesa_till_number": SHORTCODE},
            format="json",
        )

        assert response.status_code == 400

    def test_a_shortcode_with_a_space_in_it(self, api_client, shop_setup):
        """The mistake that is otherwise silent: a stray character changes the
        derived password and produces an authentication failure nobody would
        connect to a form field."""
        api_client.force_login(shop_setup.org.owner)

        response = api_client.patch(
            url(shop_setup.shop), {"mpesa_shortcode": "555 001"}, format="json"
        )

        assert response.status_code == 400

    def test_the_platform_account_cannot_be_chosen_when_there_is_none(
        self, api_client, shop_setup, settings
    ):
        settings.MPESA = {**settings.MPESA, "SHORTCODE": "", "PASSKEY": ""}
        api_client.force_login(shop_setup.org.owner)

        response = api_client.patch(
            url(shop_setup.shop), {"collects_via": "platform"}, format="json"
        )

        assert response.status_code == 400
        assert "collects_via" in response.data

    def test_a_secret_is_refused_when_the_deployment_cannot_encrypt(
        self, api_client, shop_setup, settings
    ):
        """Refused before anything is stored. The alternative is a 500 after an
        owner has pasted a live passkey into a form, with no way to know whether
        it was written somewhere in the clear on the way."""
        settings.MPESA_CREDENTIAL_KEYS = []
        api_client.force_login(shop_setup.org.owner)

        response = api_client.patch(url(shop_setup.shop), {"passkey": PASSKEY}, format="json")

        assert response.status_code == 400
        shop_setup.shop.refresh_from_db()
        assert not shop_setup.shop.mpesa_passkey_enc

    def test_the_database_refuses_a_buy_goods_row_with_no_till(self, db, shop_setup):
        """Also a serializer rule. Here too because the serializer is one of
        three ways a row is written — the admin and a shell are the others —
        and this is the one that cannot be bypassed."""
        shop = shop_setup.shop
        shop.collects_via = CollectsVia.OWN
        shop.mpesa_transaction_type = "CustomerBuyGoodsOnline"
        shop.mpesa_till_number = ""

        with pytest.raises(IntegrityError), transaction.atomic():
            shop.save()


class TestDisconnect:
    def test_it_clears_everything(self, api_client, shop_setup):
        connected(shop_setup.shop)
        api_client.force_login(shop_setup.org.owner)

        response = api_client.post(disconnect_url(shop_setup.shop))

        assert response.status_code == 200
        shop_setup.shop.refresh_from_db()
        assert shop_setup.shop.mpesa_shortcode == ""
        assert shop_setup.shop.open_mpesa_credentials() == ("", "", "")
        assert shop_setup.shop.mpesa_key_id == ""
        assert shop_setup.shop.can_take_deposits is False

    def test_only_the_owner_can(self, api_client, shop_setup):
        connected(shop_setup.shop)
        api_client.force_login(shop_setup.org.stylist)

        assert api_client.post(disconnect_url(shop_setup.shop)).status_code == 403

    def test_it_works_on_a_deployment_that_cannot_encrypt(self, api_client, shop_setup, settings):
        """The one action a shop whose keys leaked needs most must not be the
        one that raises because a key is missing."""
        connected(shop_setup.shop)
        settings.MPESA_CREDENTIAL_KEYS = []
        api_client.force_login(shop_setup.org.owner)

        assert api_client.post(disconnect_url(shop_setup.shop)).status_code == 200


class TestReadinessSaysSo:
    def test_a_shop_with_no_till_is_not_bookable(self, db, org_a):
        from shops.readiness import report_for

        shop = Shop.objects.create(organization=org_a.organization, name="New", slug="new-till")
        report = report_for(shop)

        check = next(row for row in report["checks"] if row["key"] == "collects")
        assert check["done"] is False
        assert check["action"] == "mpesa"

    def test_it_names_the_paybill_once_connected(self, db, shop_setup):
        from shops.readiness import report_for

        connected(shop_setup.shop)
        report = report_for(shop_setup.shop)

        check = next(row for row in report["checks"] if row["key"] == "collects")
        assert check["done"] is True
        assert SHORTCODE in check["detail"]

    def test_a_half_connection_says_nothing_was_collected_wrongly(self, db, shop_setup):
        """The sentence exists because it is the owner's first fear on seeing a
        warning about money, and the answer is genuinely reassuring: a shop is
        never quietly switched to somebody else's till."""
        from shops.readiness import report_for

        shop_setup.shop.collects_via = CollectsVia.OWN
        shop_setup.shop.mpesa_shortcode = SHORTCODE
        shop_setup.shop.save()

        report = report_for(shop_setup.shop)
        check = next(row for row in report["checks"] if row["key"] == "collects")

        assert check["done"] is False
        assert "wrong account" in check["detail"]

    def test_a_platform_deployment_with_no_till_blames_itself(self, db, shop_setup, settings):
        """Our misconfiguration, not the owner's. Telling them to go and connect
        something would send them looking for a screen that would not help."""
        from shops.readiness import report_for

        settings.MPESA = {**settings.MPESA, "SHORTCODE": "", "PASSKEY": ""}

        report = report_for(shop_setup.shop)
        check = next(row for row in report["checks"] if row["key"] == "collects")

        assert check["done"] is False
        assert "support" in check["detail"].lower()
