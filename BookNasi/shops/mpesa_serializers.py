"""Reading and writing a shop's M-Pesa connection.

Separate from `ShopSerializer` on purpose, and the separation is the security
property rather than tidiness. `ShopSerializer` is read by the staff app, the
owner dashboard and the setup screen; a credential field living on it is one
`fields = "__all__"`, one nested serializer, one debug page away from being in
a response nobody meant to widen. A shop's name and its Daraja passkey have
different audiences and now have different serializers.

## Secrets go in and never come out

The three sealed fields are `write_only`. What comes back is
`core.secrets.mask` — eight bullets and the last four characters — which
answers the only question an owner has about a secret they cannot read: *is the
thing I typed still the thing that is stored*. A field they can neither read
nor confirm is a field they re-enter every time they touch the screen, and
re-entering a passkey is how it ends up in a WhatsApp message to themselves.

## Partial updates mean "leave it alone", not "clear it"

An owner correcting a mistyped paybill number PATCHes the shortcode and nothing
else. If an absent passkey meant an empty one, that edit would disconnect the
shop and the next client would get no prompt. So absent is untouched and an
explicit empty string is a deliberate clear — `Shop.seal_mpesa_credentials`
takes `None` for the first and `""` for the second, which is why it has that
signature.
"""

from django.conf import settings
from rest_framework import serializers

from core import mpesa, secrets
from shops.models import CollectsVia, Shop


class ShopMpesaSerializer(serializers.ModelSerializer):
    """The connect-M-Pesa screen, both directions."""

    consumer_key = serializers.CharField(
        write_only=True, required=False, allow_blank=True, max_length=128, trim_whitespace=True
    )
    consumer_secret = serializers.CharField(
        write_only=True, required=False, allow_blank=True, max_length=128, trim_whitespace=True
    )
    passkey = serializers.CharField(
        write_only=True, required=False, allow_blank=True, max_length=256, trim_whitespace=True
    )

    consumer_key_masked = serializers.SerializerMethodField()
    consumer_secret_masked = serializers.SerializerMethodField()
    passkey_masked = serializers.SerializerMethodField()

    is_connected = serializers.BooleanField(source="can_take_deposits", read_only=True)
    #: Whether this deployment has a platform account at all. Without it the
    #: screen cannot tell "you may choose BookNasi's account" from "that choice
    #: exists but would not work", and would offer an option that silently fails.
    platform_available = serializers.SerializerMethodField()
    #: Whether credentials can be stored at all. A deployment with no
    #: `MPESA_CREDENTIAL_KEYS` must say so rather than accept a passkey and
    #: refuse it at the last moment, in a 500, after the owner has pasted it.
    can_store_credentials = serializers.SerializerMethodField()

    class Meta:
        model = Shop
        fields = [
            "collects_via",
            "mpesa_shortcode",
            "mpesa_till_number",
            "mpesa_transaction_type",
            "consumer_key",
            "consumer_secret",
            "passkey",
            "consumer_key_masked",
            "consumer_secret_masked",
            "passkey_masked",
            "is_connected",
            "platform_available",
            "can_store_credentials",
        ]

    # ------------------------------------------------------------------ read

    def _masked(self, shop, field):
        try:
            return secrets.mask(secrets.unseal(getattr(shop, field), shop.mpesa_key_id))
        except (secrets.CannotUnseal, secrets.SealingUnavailable):
            # Something is stored and we cannot open it. Not blank — blank reads
            # as "never set", and an owner seeing an empty field concludes the
            # save did not work and types it again, which is the one thing that
            # would fix it. This says the opposite of nothing.
            return "unreadable"

    def get_consumer_key_masked(self, shop):
        return self._masked(shop, "mpesa_consumer_key_enc")

    def get_consumer_secret_masked(self, shop):
        return self._masked(shop, "mpesa_consumer_secret_enc")

    def get_passkey_masked(self, shop):
        return self._masked(shop, "mpesa_passkey_enc")

    def get_platform_available(self, shop):
        return bool(settings.MPESA["SHORTCODE"] and settings.MPESA["PASSKEY"])

    def get_can_store_credentials(self, shop):
        return secrets.sealing_is_available()

    # ----------------------------------------------------------------- write

    def validate(self, attrs):
        merged = {
            "collects_via": attrs.get("collects_via", self.instance.collects_via),
            "transaction_type": attrs.get(
                "mpesa_transaction_type", self.instance.mpesa_transaction_type
            ),
            "till_number": attrs.get("mpesa_till_number", self.instance.mpesa_till_number),
            "shortcode": attrs.get("mpesa_shortcode", self.instance.mpesa_shortcode),
        }

        # Checked before anything else, including the `PLATFORM` branch below,
        # which returns early. A shop on the platform account may still be
        # saving the keys it is about to switch over to, and putting this after
        # that return meant the write reached `seal` and raised there — a 500,
        # after the owner had already pasted a live passkey into a form, with no
        # way for them to know whether it had been written somewhere on the way.
        writing_a_secret = any(
            attrs.get(field) for field in ("consumer_key", "consumer_secret", "passkey")
        )
        if writing_a_secret and not secrets.sealing_is_available():
            raise serializers.ValidationError(
                {
                    "passkey": (
                        "This deployment cannot store M-Pesa credentials securely "
                        "(MPESA_CREDENTIAL_KEYS is not set). Nothing has been saved."
                    )
                }
            )

        if merged["collects_via"] == CollectsVia.PLATFORM:
            if not self.get_platform_available(self.instance):
                raise serializers.ValidationError(
                    {
                        "collects_via": (
                            "This deployment has no BookNasi M-Pesa account configured, "
                            "so deposits cannot be collected that way."
                        )
                    }
                )
            # Nothing else to check: the shop's own columns may stay filled in,
            # so switching to the platform account and back does not cost an
            # owner their Daraja keys.
            return attrs

        if merged["transaction_type"] == mpesa.TILL and not merged["till_number"]:
            # Also a database constraint and also checked in `payments/tills.py`.
            # Here as well because this is the only one of the three that can
            # say it in a sentence an owner reads before the mistake is saved,
            # and the mistake is the expensive kind: Safaricom accepts a push
            # whose `PartyB` is the store number, the client pays, and the money
            # is not where the shop is looking.
            raise serializers.ValidationError(
                {
                    "mpesa_till_number": (
                        "A Buy Goods connection needs the till number as well as the "
                        "store number. They are different numbers, and money sent to "
                        "the wrong one still leaves the client's phone."
                    )
                }
            )

        if merged["shortcode"] and merged["shortcode"] == merged["till_number"]:
            # Not fatal at Safaricom and occasionally even correct, but far more
            # often the misunderstanding this whole field exists around: the
            # store number and the till number are different numbers, and a shop
            # that types one into both has almost certainly copied the wrong one.
            raise serializers.ValidationError(
                {
                    "mpesa_till_number": (
                        "The till number is the same as the store number. On a Buy Goods "
                        "account these are different — the store number is the one "
                        "Safaricom calls the head office number."
                    )
                }
            )

        return attrs

    def update(self, instance, validated_data):
        # Popped before `super()`: they are not model fields, and a
        # `ModelSerializer` handed one would try to `setattr` the plaintext onto
        # the instance — which is the exact thing `Shop` has methods instead of
        # attributes to prevent.
        plaintext = {
            "consumer_key": validated_data.pop("consumer_key", None),
            "consumer_secret": validated_data.pop("consumer_secret", None),
            "passkey": validated_data.pop("passkey", None),
        }
        shop = super().update(instance, validated_data)
        if any(value is not None for value in plaintext.values()):
            shop.seal_mpesa_credentials(**plaintext)
            shop.save(
                update_fields=[
                    "mpesa_consumer_key_enc",
                    "mpesa_consumer_secret_enc",
                    "mpesa_passkey_enc",
                    "mpesa_key_id",
                    "updated_at",
                ]
            )
        return shop
