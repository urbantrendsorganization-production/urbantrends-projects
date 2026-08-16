"""Per-shop M-Pesa credentials, and where the existing shops land.

Reviewed by hand (CLAUDE.md §11). The generated version was correct about the
columns and wrong about the only thing that matters here: `collects_via`
defaults to `own`, so a plain `AddField` would have told every shop already
running that it collects into an account it has never configured. That is the
opposite of true — until this migration their deposits went to the deployment's
till, because that was the only till there was.

So the default is for *new* shops, and `_existing_shops_are_on_the_platform_till`
moves every row that predates this migration to `platform`. It is a statement of
fact about where their money has been going, not a policy choice, which is why
it runs here rather than being left to an owner to notice.

Irreversible in the direction that matters: reversing drops the column, so there
is nothing to restore and nothing to guess. The backwards function is a no-op
rather than a `RunPython.noop` alias so that this comment has somewhere to live.
"""

import core.mpesa
from django.db import migrations, models


def _existing_shops_are_on_the_platform_till(apps, schema_editor):
    Shop = apps.get_model("shops", "Shop")
    # `_base_manager`, not `objects`. `Shop.objects` is `OrgScopedManager`,
    # which refuses an unfiltered query by design (`core/managers.py`) and is
    # not carried onto a historical model in any case — and this is the one
    # place a cross-tenant write is correct, because the fact being recorded is
    # true of every shop on the deployment regardless of who owns it.
    Shop._base_manager.update(collects_via="platform")


def _nothing_to_undo(apps, schema_editor):
    """Reversing this migration drops `collects_via` entirely."""


class Migration(migrations.Migration):
    dependencies = [
        ("orgs", "0003_alter_staffinvite_options_alter_staffinvite_managers"),
        ("shops", "0003_refund_policy"),
    ]

    operations = [
        migrations.AddField(
            model_name="shop",
            name="collects_via",
            field=models.CharField(
                choices=[
                    ("own", "The shop's own M-Pesa"),
                    ("platform", "The BookNasi platform account"),
                ],
                default="own",
                help_text=(
                    "Whose M-Pesa account deposits land in. New shops must connect their own."
                ),
                max_length=8,
            ),
        ),
        migrations.RunPython(
            _existing_shops_are_on_the_platform_till,
            _nothing_to_undo,
            # No `elidable=True`: squashing this away would silently restore the
            # `own` default for the very rows it exists to correct.
        ),
        migrations.AddField(
            model_name="shop",
            name="mpesa_shortcode",
            field=models.CharField(
                blank=True,
                help_text=(
                    "Paybill: the paybill number. Till: the store / head office number, "
                    "which is not the till number. The password is derived from this in "
                    "both cases."
                ),
                max_length=12,
                validators=[core.mpesa.validate_shortcode],
            ),
        ),
        migrations.AddField(
            model_name="shop",
            name="mpesa_till_number",
            field=models.CharField(
                blank=True,
                help_text=(
                    "Where BuyGoods money actually lands. Required when the type is a till."
                ),
                max_length=12,
                validators=[core.mpesa.validate_shortcode],
            ),
        ),
        migrations.AddField(
            model_name="shop",
            name="mpesa_transaction_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("CustomerPayBillOnline", "Paybill"),
                    ("CustomerBuyGoodsOnline", "Till (Buy Goods)"),
                ],
                help_text="Blank means paybill, matching the deployment-level default.",
                max_length=32,
            ),
        ),
        # Ciphertext. `BinaryField` rather than a text column of base64: Fernet
        # produces bytes, and a round trip through a `CharField` is one encoding
        # assumption away from a credential that will not decrypt and cannot be
        # recovered.
        migrations.AddField(
            model_name="shop",
            name="mpesa_consumer_key_enc",
            field=models.BinaryField(blank=True, default=bytes),
        ),
        migrations.AddField(
            model_name="shop",
            name="mpesa_consumer_secret_enc",
            field=models.BinaryField(blank=True, default=bytes),
        ),
        migrations.AddField(
            model_name="shop",
            name="mpesa_passkey_enc",
            field=models.BinaryField(blank=True, default=bytes),
        ),
        migrations.AddField(
            model_name="shop",
            name="mpesa_key_id",
            field=models.CharField(blank=True, editable=False, max_length=32),
        ),
        migrations.AddConstraint(
            model_name="shop",
            constraint=models.CheckConstraint(
                condition=models.Q(("collects_via__in", ["own", "platform"])),
                name="shop_collects_via_known",
            ),
        ),
        # NOT (own AND buy-goods) OR the till number is set. See the model.
        migrations.AddConstraint(
            model_name="shop",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("collects_via", "own"),
                        ("mpesa_transaction_type", "CustomerBuyGoodsOnline"),
                        _negated=True,
                    ),
                    models.Q(("mpesa_till_number", ""), _negated=True),
                    _connector="OR",
                ),
                name="shop_own_till_has_a_till_number",
            ),
        ),
    ]
